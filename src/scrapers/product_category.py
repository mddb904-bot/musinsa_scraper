"""商品の中カテゴリを、商品詳細ページを開いて取得する（方法A）。

ランキングAPIのレスポンスには中カテゴリが含まれないため、商品詳細ページ
(/jp/goods/{goodsNo}) を開いて中カテゴリ（category2Depth 相当）を取得する。

カテゴリ情報がページのどこ（傍受JSON / 埋め込み __NEXT_DATA__ 等）に入るか
確定させるため、最初の数商品では「カテゴリを含むデータ源の生スニペット」を
ログ出力する診断モードを備える。抽出は、キー/パスに 'categor' を含み値が
カテゴリ名らしいスカラーを候補化し、中カテゴリらしさでスコア選択する。

重い処理（商品ごとに1ページ開く）なので、呼び出し側のフラグで on/off する。
"""
from __future__ import annotations

import json
import logging

from playwright.sync_api import sync_playwright, Response

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _walk_scalars(obj, path: str = ""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                yield from _walk_scalars(v, f"{path}.{k}")
            else:
                yield (path, str(k), v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, (dict, list)):
                yield from _walk_scalars(v, f"{path}[{i}]")


def _looks_like_category_name(value) -> bool:
    if not isinstance(value, str):
        return False
    s = value.strip()
    if not s or len(s) > 30:
        return False
    if s.lower() in ("true", "false", "null", "none"):
        return False
    if s.startswith(("http", "#", "/")) or "/" in s or "." in s:
        return False
    return True


def _category_candidates(data) -> list[tuple[str, str, str]]:
    hits: list[tuple[str, str, str]] = []
    for path, key, value in _walk_scalars(data):
        if not _looks_like_category_name(value):
            continue
        if "categor" in key.lower() or "categor" in path.lower():
            hits.append((path, key, value.strip()))
    return hits


def _score(path: str, key: str) -> int:
    t = f"{path}.{key}".lower()
    s = 0
    if any(x in t for x in ("2depth", "depth2", "category2", "middle", "second", "medium")):
        s += 100
    if "name" in t:
        s += 20
    if any(x in t for x in ("3depth", "depth3", "category3", "small")):
        s += 5
    if any(x in t for x in ("1depth", "depth1", "category1", "large", "first")):
        s -= 50
    if "brand" in t:
        s -= 1000
    if any(x in t for x in ("code", "id", "url", "link", "version", "enabled", "menu", "yn", "count")):
        s -= 200
    return s


def _pick_mid_category(candidates: list[tuple[str, str, str]]) -> str | None:
    if not candidates:
        return None
    best = max(candidates, key=lambda c: _score(c[0], c[1]))
    return best[2] if _score(best[0], best[1]) > 0 else None


def enrich_items_with_category(
    items: list[dict],
    *,
    request_interval_seconds: float = 1.0,
    timeout_ms: int = 20000,
    log_samples: int = 2,
    category_limit: int = 0,
) -> None:
    """items に in-place で `_category`（中カテゴリ）を付与する。

    データ源（傍受JSON / __NEXT_DATA__ / application/json スクリプト）を横断して
    カテゴリ候補を集める。最初の log_samples 件では、カテゴリを含む生データの
    スニペットをログ出力して項目位置を特定できるようにする。
    category_limit > 0 なら先頭N件のユニーク商品だけを対象（動作確認用）。
    """
    if not items:
        return

    unique: dict[str, str | None] = {}
    for it in items:
        g = str(it.get("goodsNo") or "")
        if g:
            unique.setdefault(g, None)

    goods_ids = list(unique.keys())
    if category_limit and category_limit > 0:
        goods_ids = goods_ids[:category_limit]
        logger.info("Category enrichment: LIMITED to first %d unique products (test mode)", len(goods_ids))

    logger.info(
        "Category enrichment: opening %d product pages (of %d items)...",
        len(goods_ids), len(items),
    )

    # 傍受した JSON レスポンス (url, parsed_body, raw_text) を貯める
    responses: list[tuple[str, object, str]] = []

    def on_response(response: Response) -> None:
        try:
            if "application/json" not in response.headers.get("content-type", ""):
                return
            text = response.text()
            body = json.loads(text)
        except Exception:
            return
        responses.append((response.url, body, text))

    got = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=_USER_AGENT, locale="ja-JP")
        page = context.new_page()
        page.on("response", on_response)

        for idx, g in enumerate(goods_ids):
            responses.clear()
            url = f"https://global.musinsa.com/jp/goods/{g}?toggleCountry=jp"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(2000)
                # 遅延ロードの商品詳細API等を発火させる
                try:
                    page.mouse.wheel(0, 2500)
                except Exception:
                    pass
                page.wait_for_timeout(2500)
            except Exception as e:
                logger.warning("category fetch failed for goods %s: %s", g, e)
                page.wait_for_timeout(int(request_interval_seconds * 1000))
                continue

            # 埋め込み JSON (__NEXT_DATA__ / application/json)
            embedded: list[str] = []
            try:
                embedded = page.evaluate(
                    """() => {
                        const out = [];
                        const nd = document.getElementById('__NEXT_DATA__');
                        if (nd && nd.textContent) out.push(nd.textContent);
                        document.querySelectorAll('script[type="application/json"]').forEach(s => {
                            if (s.textContent) out.push(s.textContent);
                        });
                        return out;
                    }"""
                ) or []
            except Exception:
                embedded = []

            # 全データ源から候補を集める
            sources: list[tuple[str, object]] = [(u, b) for (u, b, _t) in responses]
            for i, blob in enumerate(embedded):
                try:
                    sources.append((f"embedded[{i}]", json.loads(blob)))
                except Exception:
                    pass

            candidates: list[tuple[str, str, str]] = []
            for _src, body in sources:
                candidates.extend(_category_candidates(body))

            # --- 診断ログ: 最初の数件だけ ---
            if idx < log_samples:
                logger.info("goods %s: %d json responses, %d embedded json blobs",
                            g, len(responses), len(embedded))
                # 全レスポンスURLを列挙（商品詳細APIを特定するため）
                for u, _b, _t in responses:
                    logger.info("    URL: %s", u[:130])
                # 商品詳細っぽいレスポンス(goods/product/detail)の中身をダンプ
                for u, _b, text in responses:
                    ul = u.lower()
                    if any(x in ul for x in ("goods", "product", "detail")) and str(g) in u:
                        logger.info("  [GOODS %s] snippet: %s", u.split("?")[0][-70:], text[:2500])
                # カテゴリという語を含むデータ源の生スニペット
                for u, _b, text in responses:
                    if "categor" in text.lower():
                        logger.info("  [resp %s] snippet: %s", u.split("?")[0][-60:], text[:800])
                logger.info("  category candidates: %s",
                            sorted({(k, v) for (_p, k, v) in candidates})[:20])

            cat = _pick_mid_category(candidates)
            unique[g] = cat
            if cat:
                got += 1

            if (idx + 1) % 25 == 0:
                logger.info("  category progress: %d/%d", idx + 1, len(goods_ids))
            page.wait_for_timeout(int(request_interval_seconds * 1000))

        browser.close()

    for it in items:
        g = str(it.get("goodsNo") or "")
        if unique.get(g):
            it["_category"] = unique[g]

    logger.info("Category enrichment done: %d/%d products got a mid-category", got, len(goods_ids))
