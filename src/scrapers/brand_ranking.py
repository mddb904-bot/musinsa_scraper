"""ブランドランキング スクレイパー (ブランド単位・日次)。

女性商品ランキングとは別系統。ブランドの順位表を取得する。

取得元は、ページ読み込み時に発火するトレンドAPIのレスポンスを Playwright で
傍受して得る。従来は以下の1本に固定依存していた:
    https://global.musinsa.com/api/global/trending/v2/brands
        ?countryCode=JP&languageCode=ja&toggleCountry=jp&categoryCode=
    → data.brandList[]

しかしMUSINSA側の仕様変更(APIバージョンやキー名、SSR化など)で上記が取れなく
なると全滅する作りだったため、本実装では以下のように堅牢化している:
  1. brand/trending/ranking 系のJSONレスポンスを幅広く捕捉
  2. その中から「ブランド一覧らしい配列」を再帰的に自動発見(キー名の揺れに対応)
  3. XHRで取れない場合はページHTML内の埋め込みJSON(__NEXT_DATA__等)からも抽出
  4. それでも取れない場合は、実際に叩かれたAPIのURL/キーを診断ログに出力

各要素からは rank / id(slug) / name / landingUrl を柔軟なキー対応で取り出す。

「MUSINSA 独占」フラグはこのAPIには含まれないため、各ブランドページを開いて
バッジのテキスト有無で判定する(案A)。styled-components のクラス名はデプロイ
ごとに変わるので、"MUSINSA 独占" というテキストをアンカーにする。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

from playwright.sync_api import sync_playwright, Response

logger = logging.getLogger(__name__)


_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_LIST_PAGE_URL = "https://global.musinsa.com/jp/trending/brands?toggleCountry=jp"

# MUSINSAはCloudflareのBot保護(マネージドチャレンジ)を有効化しており、素の
# ヘッドレスChromiumは「Attention Required!」画面で弾かれる。実ブラウザ相当に
# 振る舞う(=ヘッドフル+自動化フィンガープリント除去)ことでチャレンジの自動通過を狙う。
#   - CIでは xvfb 上でヘッドフル起動する(ワークフロー側で xvfb-run)。
#   - BRAND_HEADLESS=1 を指定した場合のみヘッドレス(デバッグ用)。
_HEADLESS = os.environ.get("BRAND_HEADLESS", "0").lower() not in ("", "0", "false", "no")

_LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--start-maximized",
]

# 自動化検知を弱めるための初期化スクリプト(navigator.webdriver 等を実ブラウザ風に)
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['ja-JP','ja','en-US','en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
window.chrome = window.chrome || { runtime: {} };
try {
  const _q = window.navigator.permissions && window.navigator.permissions.query;
  if (_q) {
    window.navigator.permissions.query = (p) =>
      (p && p.name === 'notifications')
        ? Promise.resolve({ state: Notification.permission })
        : _q(p);
  }
} catch (e) {}
"""

_EXTRA_HEADERS = {
    "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
    "sec-ch-ua": '"Chromium";v="120", "Not(A:Brand";v="24", "Google Chrome";v="120"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Upgrade-Insecure-Requests": "1",
}


def _looks_like_challenge(page) -> bool:
    """Cloudflareのチャレンジ/ブロック画面が表示中かを判定する。"""
    try:
        title = (page.title() or "").lower()
    except Exception:  # noqa: BLE001
        title = ""
    if "attention required" in title or "just a moment" in title:
        return True
    try:
        html = (page.content() or "").lower()
    except Exception:  # noqa: BLE001
        return False
    return (
        "cdn-cgi/challenge-platform" in html
        or "cf-chl" in html
        or "checking your browser" in html
    )

# --- ブランド要素のキー名揺れ対応(優先順に探す) ---
_RANK_KEYS = ("rank", "ranking", "rankNo", "rank_no", "rankingNo")
_ID_KEYS = ("id", "brandId", "brand_id", "brandCode", "brand_code", "code", "slug")
_NAME_KEYS = ("name", "brandName", "brand_name", "brandNameEng", "nameEng", "title")
_URL_KEYS = ("landingUrl", "landing_url", "url", "linkUrl", "link_url", "link")
# 商品(goods)要素を誤検出しないための除外キー
_PRODUCT_MARKER_KEYS = ("goodsNo", "goodsName", "goodsInfoList")


def _first_key(d: dict, keys: tuple[str, ...]):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None


def _looks_like_brand_item(d) -> bool:
    """dict が「ブランドランキングの1件」らしいかを判定する。

    商品(goods)要素と区別するため、goodsNo/goodsName を持つものは除外する。
    名前系キーがあり、かつ 順位系 or ブランドID系 のどちらかを持てばブランドとみなす。
    """
    if not isinstance(d, dict):
        return False
    if any(k in d for k in _PRODUCT_MARKER_KEYS):
        return False
    has_name = _first_key(d, _NAME_KEYS) is not None
    has_rank_or_id = (
        _first_key(d, _RANK_KEYS) is not None or _first_key(d, _ID_KEYS) is not None
    )
    return has_name and has_rank_or_id


def _score_brand_list(lst) -> int:
    """配列が「ブランド一覧」らしい度合いを件数で返す(0なら非該当)。"""
    if not isinstance(lst, list) or not lst:
        return 0
    good = sum(1 for it in lst if _looks_like_brand_item(it))
    # 過半数がブランド要素なら採用
    return good if good >= max(1, len(lst) // 2) else 0


def _find_brand_list(obj) -> list | None:
    """任意のJSON構造から「ブランド一覧らしい配列」を再帰的に探す。

    優先度:
      1. キー名が明示的に brandList / brand_list の配列
      2. ヒューリスティック(_score_brand_list)で最良の配列
    """
    # 1) 明示キー優先
    explicit = _find_by_key_names(obj, ("brandList", "brand_list", "brandRankList"))
    if explicit is not None and _score_brand_list(explicit) > 0:
        return explicit

    # 2) ヒューリスティックで全走査し、最もスコアの高い配列を返す
    best: list | None = None
    best_score = 0

    def walk(node):
        nonlocal best, best_score
        if isinstance(node, list):
            s = _score_brand_list(node)
            if s > best_score:
                best, best_score = node, s
            for it in node:
                if isinstance(it, (list, dict)):
                    walk(it)
        elif isinstance(node, dict):
            for v in node.values():
                if isinstance(v, (list, dict)):
                    walk(v)

    walk(obj)
    return best


def _find_by_key_names(obj, key_names: tuple[str, ...]) -> list | None:
    """指定キー名の配列を再帰的に探して最初の1つを返す。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in key_names and isinstance(v, list):
                return v
        for v in obj.values():
            r = _find_by_key_names(v, key_names)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for it in obj:
            r = _find_by_key_names(it, key_names)
            if r is not None:
                return r
    return None


def _abs_brand_url(landing) -> str | None:
    if not landing or not isinstance(landing, str):
        return None
    if landing.startswith("/"):
        return f"https://global.musinsa.com{landing}"
    return landing


def _map_brand_item(b: dict) -> dict:
    """ブランド要素(キー名の揺れあり)を共通スキーマに写像する。"""
    return {
        "rank": _first_key(b, _RANK_KEYS),
        "brand_id": _first_key(b, _ID_KEYS),
        "brand_name": _first_key(b, _NAME_KEYS),
        "brand_url": _abs_brand_url(_first_key(b, _URL_KEYS)),
        "is_musinsa_exclusive": None,
    }


def _extract_brand_list_from_html(html: str) -> list | None:
    """ページHTMLの埋め込みJSON(__NEXT_DATA__ 等)からブランド一覧を探す。

    APIが別リクエストで飛ばず、データがSSR/RSCでHTMLに埋め込まれている場合の保険。
    """
    if not html:
        return None

    # 1) __NEXT_DATA__ を丸ごとパースして探す
    m = re.search(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    if m:
        try:
            data = json.loads(m.group(1))
            found = _find_brand_list(data)
            if found and _score_brand_list(found) > 0:
                logger.info("brandList found in __NEXT_DATA__ (%d items)", len(found))
                return found
        except Exception as e:  # noqa: BLE001
            logger.debug("failed to parse __NEXT_DATA__: %s", e)

    # 2) "brandList": [ ... ] を素朴なブラケット対応で切り出す
    idx = html.find('"brandList"')
    if idx != -1:
        arr = _slice_json_array(html, html.find("[", idx))
        if arr is not None:
            try:
                found = json.loads(arr)
                if _score_brand_list(found) > 0:
                    logger.info(
                        "brandList found via inline literal (%d items)", len(found)
                    )
                    return found
            except Exception as e:  # noqa: BLE001
                logger.debug("failed to parse inline brandList: %s", e)

    return None


def _slice_json_array(s: str, start: int) -> str | None:
    """s[start] が '[' のとき、対応する ']' までの部分文字列を返す。"""
    if start < 0 or start >= len(s) or s[start] != "[":
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    return None


def _detect_exclusive(page, brand_url: str | None, timeout_ms: int) -> bool | None:
    """ブランドページを開いて「MUSINSA 独占」バッジの有無を判定する。

    Returns:
        True  … 独占バッジあり
        False … バッジなし(ページは正常に読めた)
        None  … ページを読めず判定不能
    """
    if not brand_url:
        return None
    try:
        page.goto(brand_url, wait_until="domcontentloaded", timeout=timeout_ms)
        time.sleep(1.5)
        text = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
    except Exception as e:
        logger.warning("exclusive check failed for %s: %s", brand_url, e)
        return None

    # 全角/半角スペースを除去して「MUSINSA独占」で判定
    normalized = text.replace(" ", "").replace("　", "")
    if "MUSINSA独占" in normalized:
        return True
    return False


def fetch_brand_ranking_list(
    top_n: int = 100,
    detect_exclusive: bool = True,
    request_interval_seconds: float = 1.0,
    timeout_ms: int = 30000,
    exclusive_timeout_ms: int = 20000,
) -> list[dict]:
    """ブランドランキング上位N件を取得する。

    Returns: [{rank, brand_id, brand_name, brand_url, is_musinsa_exclusive}, ...]
    (rank 昇順)
    """
    # 捕捉したAPIレスポンス候補: (url, parsed_json)
    candidates: list[tuple[str, object]] = []
    # 診断用: 見えた XHR/fetch リクエスト一覧 (rtype, url, content-type)
    seen_requests: list[tuple[str, str, str]] = []

    def on_response(response: Response) -> None:
        url = response.url
        try:
            req = response.request
            rtype = req.resource_type if req is not None else ""
        except Exception:  # noqa: BLE001
            rtype = ""
        try:
            ctype = (response.headers or {}).get("content-type", "")
        except Exception:  # noqa: BLE001
            ctype = ""

        # 診断: XHR/fetch は URL を全部記録しておく(新APIの特定に使う)
        if rtype in ("xhr", "fetch"):
            seen_requests.append((rtype, url, ctype))

        # JSONっぽいレスポンスは URL パスに依存せず本文を読み、ブランド一覧を探す。
        # (APIが別名パスや別ホストへ移動していても捕捉できるようにする)
        is_jsonish = (
            "json" in ctype.lower() or rtype in ("xhr", "fetch") or url.endswith(".json")
        )
        if not is_jsonish:
            return
        try:
            body = response.json()
        except Exception:  # noqa: BLE001
            return
        found = _find_brand_list(body)
        if found and _score_brand_list(found) > 0:
            candidates.append((url, found))
            logger.info(
                "Captured brand list: %d brands from %s", len(found), url[:150]
            )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=_HEADLESS, args=_LAUNCH_ARGS)
        context = browser.new_context(
            user_agent=_USER_AGENT,
            locale="ja-JP",
            timezone_id="Asia/Tokyo",
            viewport={"width": 1280, "height": 1800},
            extra_http_headers=_EXTRA_HEADERS,
        )
        # 自動化フィンガープリントを弱める(全ページ共通で先に注入)
        try:
            context.add_init_script(_STEALTH_JS)
        except Exception as e:  # noqa: BLE001
            logger.debug("add_init_script failed: %s", e)
        page = context.new_page()
        page.on("response", on_response)

        logger.info(
            "Loading brand ranking page (headless=%s): %s", _HEADLESS, _LIST_PAGE_URL
        )
        try:
            page.goto(_LIST_PAGE_URL, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception as e:
            logger.warning("page.goto: %s", e)

        # Cloudflareのマネージドチャレンジが出ている場合、実ブラウザなら数秒〜十数秒で
        # 自動通過して本来のページに遷移する。通過(またはデータ捕捉)まで待つ。
        if _looks_like_challenge(page):
            logger.warning("Cloudflare challenge detected; waiting for auto clearance...")
            for _ in range(40):  # 最長 ~40秒
                if candidates or not _looks_like_challenge(page):
                    break
                page.wait_for_timeout(1000)
            if _looks_like_challenge(page) and not candidates:
                logger.warning("Challenge still present after wait; reloading once")
                try:
                    page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
                except Exception as e:  # noqa: BLE001
                    logger.warning("reload failed: %s", e)
                for _ in range(20):
                    if candidates or not _looks_like_challenge(page):
                        break
                    page.wait_for_timeout(1000)
            if not _looks_like_challenge(page):
                logger.info("Cloudflare challenge cleared")

        # APIレスポンスが傍受されるまで待つ。
        # 注意: Playwright sync API では time.sleep() 中は response イベントが
        # ディスパッチされない(Python側のイベントループが回らない)ため、
        # ブラウザが応答を受信済みでも on_response が発火しない。
        # page.wait_for_timeout() はイベントループを回すので、待機はこちらを使う。
        for _ in range(30):  # 最長 ~15秒
            if candidates:
                break
            page.wait_for_timeout(500)

        # まだなら軽くスクロールして再発火を促し、さらに待つ
        if not candidates:
            try:
                page.mouse.wheel(0, 3000)
                page.wait_for_timeout(2000)
            except Exception:
                pass
            for _ in range(10):
                if candidates:
                    break
                page.wait_for_timeout(500)

        brand_list = candidates[0][1] if candidates else None

        # フォールバック: XHRで取れなければ、HTML埋め込みJSONから抽出を試みる
        html = ""
        if not brand_list:
            logger.warning(
                "No brand list captured via XHR; trying HTML-embedded JSON fallback"
            )
            try:
                html = page.content()
            except Exception as e:  # noqa: BLE001
                html = ""
                logger.warning("page.content() failed: %s", e)
            brand_list = _extract_brand_list_from_html(html)

        # それでもダメなら診断情報を残す(新しいAPI構造の特定に使う)
        if not brand_list:
            logger.error(
                "brandList not captured (page structure or API may have changed)"
            )
            try:
                title = page.title()
            except Exception:  # noqa: BLE001
                title = "?"
            _log_diagnostics(seen_requests, html, title)
            brand_list = []

        results: list[dict] = [_map_brand_item(b) for b in brand_list if isinstance(b, dict)]

        # rank 昇順に整列して上位N件(rank が無い要素は元の順序を保つよう末尾寄せ)
        results.sort(key=lambda r: _rank_sort_key(r["rank"]))
        results = results[:top_n]

        # 案A: 各ブランドページを開いて独占フラグを判定
        if detect_exclusive and results:
            logger.info("Detecting MUSINSA-exclusive flag across %d brand pages...", len(results))
            excl = 0
            for i, r in enumerate(results, 1):
                r["is_musinsa_exclusive"] = _detect_exclusive(
                    page, r["brand_url"], exclusive_timeout_ms
                )
                if r["is_musinsa_exclusive"]:
                    excl += 1
                if i % 20 == 0:
                    logger.info("  exclusive check progress: %d/%d", i, len(results))
                time.sleep(request_interval_seconds)
            logger.info("Exclusive detection done: %d/%d flagged exclusive", excl, len(results))

        browser.close()

    logger.info("Brand ranking: returning %d brands", len(results))
    return results


def _rank_sort_key(rank) -> int:
    try:
        return int(rank)
    except (TypeError, ValueError):
        return 9999


def _log_diagnostics(
    seen_requests: list[tuple[str, str, str]],
    html: str,
    title: str,
) -> None:
    """失敗時に、実際に叩かれた XHR/fetch とHTMLの状態を診断ログに出す。

    ローカルからサイトへ到達できない環境では、このログが新しいAPI構造や
    SSR化・ボットブロックを特定する唯一の手がかりになる。
    """
    # --- 1) XHR/fetch の全URL(重複除去) ---
    uniq: list[tuple[str, str, str]] = []
    seen = set()
    for rtype, url, ctype in seen_requests:
        if url in seen:
            continue
        seen.add(url)
        uniq.append((rtype, url, ctype))
    if not uniq:
        logger.error(
            "DIAGNOSTIC: no XHR/fetch requests were observed at all. "
            "The page likely renders data server-side or blocks headless browsers."
        )
    else:
        logger.error("DIAGNOSTIC: observed %d XHR/fetch request(s):", len(uniq))
        for rtype, url, ctype in uniq[:60]:
            logger.error("  - [%s] %s (%s)", rtype, url[:220], ctype[:40])

    # --- 2) HTML側のシグナル(データが埋め込まれているか/ブロックされていないか) ---
    html = html or ""
    lower = html.lower()
    signals = {
        "html_len": len(html),
        "title": (title or "")[:80],
        "has___NEXT_DATA__": "__next_data__" in lower,
        "has_next_f_stream": "self.__next_f" in html,
        "has_brandList_literal": '"brandlist"' in lower,
        "count_/brands/": html.count("/brands/"),
        "looks_blocked": any(
            k in lower for k in ("captcha", "are you a robot", "access denied", "px-captcha", "perimeterx", "cloudflare")
        ),
    }
    logger.error("DIAGNOSTIC: HTML signals: %s", signals)
