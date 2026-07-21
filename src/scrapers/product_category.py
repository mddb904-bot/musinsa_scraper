"""商品の中カテゴリを、商品詳細ページを開いて取得する（方法A）。

ランキングAPIのレスポンスには中カテゴリが含まれず、商品ページでは
カテゴリがサーバー側でHTMLに埋め込まれる（SSR: isCategorySsrEnabled）ため、
別JSON通信の傍受では取れない。そこで商品詳細ページに埋め込まれた
`__NEXT_DATA__`（および application/json スクリプト）を読み、
その中からカテゴリ名（category2Depth 相当＝中カテゴリ）を抽出する。
パンくず(breadcrumb)のテキストもフォールバック兼確認用に拾う。

重い処理（商品ごとに1ページ開く）なので、呼び出し側のフラグで on/off する。
最初の数商品については候補をログ出力し、実データで項目名を確認できるようにする。
"""
from __future__ import annotations

import json
import logging

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _walk_scalars(obj, path: str = ""):
    """ネストした dict/list を再帰的に走査し、(path, key, value) を列挙する。"""
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
    """パス or キー名に 'categor' を含み、値がカテゴリ名らしいものを列挙する。"""
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


def _extract_from_page(page, log_detail: bool) -> str | None:
    """現在開いているページから中カテゴリ名を抽出する。"""
    # 1) __NEXT_DATA__ と application/json スクリプトを集める
    blobs: list[str] = []
    try:
        blobs = page.evaluate(
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
        blobs = []

    candidates: list[tuple[str, str, str]] = []
    for blob in blobs:
        try:
            data = json.loads(blob)
        except Exception:
            continue
        candidates.extend(_category_candidates(data))

    # 2) パンくず(breadcrumb)候補テキスト（フォールバック兼確認用）
    crumbs = []
    try:
        crumbs = page.evaluate(
            """() => {
                const sel = 'nav a, [class*="readcrumb" i] a, [class*="readcrumb" i] li, ol li a';
                return Array.from(document.querySelectorAll(sel))
                    .map(e => (e.innerText || '').trim())
                    .filter(t => t && t.length <= 20).slice(0, 20);
            }"""
        ) or []
    except Exception:
        crumbs = []

    if log_detail:
        uniq = sorted({(p, k, v) for (p, k, v) in candidates}, key=lambda c: -_score(c[0], c[1]))
        logger.info("  NEXT_DATA category candidates (top): %s", uniq[:12])
        logger.info("  breadcrumb texts: %s", crumbs)

    return _pick_mid_category(candidates)


def enrich_items_with_category(
    items: list[dict],
    *,
    request_interval_seconds: float = 1.0,
    timeout_ms: int = 20000,
    log_samples: int = 3,
    category_limit: int = 0,
) -> None:
    """items（商品オブジェクトのリスト）に in-place で `_category`（中カテゴリ）を付与する。

    goodsNo で重複排除し、ユニークな商品ごとに1回だけ詳細ページを開く。
    category_limit > 0 の場合は先頭 N 件のユニーク商品だけを対象にする（動作確認用）。
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

    got = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=_USER_AGENT, locale="ja-JP")
        page = context.new_page()

        for idx, g in enumerate(goods_ids):
            url = f"https://global.musinsa.com/jp/goods/{g}?toggleCountry=jp"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(1500)
            except Exception as e:
                logger.warning("category fetch failed for goods %s: %s", g, e)
                unique[g] = None
                page.wait_for_timeout(int(request_interval_seconds * 1000))
                continue

            if idx < log_samples:
                logger.info("goods %s:", g)
            cat = _extract_from_page(page, log_detail=idx < log_samples)
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

    logger.info(
        "Category enrichment done: %d/%d products got a mid-category",
        got, len(goods_ids),
    )
