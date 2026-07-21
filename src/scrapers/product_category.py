"""商品の中カテゴリを、商品詳細ページを開いて取得する（方法A/B）。

ランキングAPIにも商品ページの各JSON APIにも「中カテゴリ名」は含まれず、
商品情報はサーバー側でHTMLに埋め込まれる。そこで:

  B（名前）: ページの構造化データ ld+json（schema.org BreadcrumbList）から
             パンくずを取り出し、中カテゴリ名を得る。
  A（コード）: 通信URLに含まれる itemCategoryCode（例 001001）を確保する保険。

`_category` には名前（取れれば）を、取れなければコードを入れる。
重い処理（商品ごとに1ページ開く）なので呼び出し側フラグで on/off する。
"""
from __future__ import annotations

import json
import logging
import re

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_ITEM_CAT_RE = re.compile(r"itemCategoryCode=(\d+)")


def _extract_breadcrumb_from_ldjson(ld_texts: list[str]) -> list[str]:
    """ld+json の BreadcrumbList から名前リスト（ルート→末端）を取り出す。"""
    for text in ld_texts:
        try:
            data = json.loads(text)
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        # @graph を持つ形式にも対応
        expanded = []
        for o in objs:
            if isinstance(o, dict) and isinstance(o.get("@graph"), list):
                expanded.extend(o["@graph"])
            else:
                expanded.append(o)
        for o in expanded:
            if not isinstance(o, dict):
                continue
            if o.get("@type") == "BreadcrumbList" and isinstance(o.get("itemListElement"), list):
                names = []
                for el in o["itemListElement"]:
                    if not isinstance(el, dict):
                        continue
                    name = el.get("name")
                    if not name and isinstance(el.get("item"), dict):
                        name = el["item"].get("name")
                    if name:
                        names.append(str(name).strip())
                if names:
                    return names
    return []


def _iter_ldjson_objects(ld_texts: list[str]):
    """ld+json 群を @graph 展開して個々のオブジェクトを列挙する。"""
    for text in ld_texts:
        try:
            data = json.loads(text)
        except Exception:
            continue
        objs = data if isinstance(data, list) else [data]
        for o in objs:
            if isinstance(o, dict) and isinstance(o.get("@graph"), list):
                for g in o["@graph"]:
                    yield g
            else:
                yield o


def _mid_from_path(cat: str) -> str:
    """'A > B > C' や 'A/B/C' のようなカテゴリ表記から末端（中カテゴリ）を取り出す。"""
    for sep in (">", "＞", "/", "|"):
        if sep in cat:
            parts = [p.strip() for p in cat.split(sep) if p.strip()]
            if parts:
                return parts[-1]
    return cat.strip()


def _extract_product_category(ld_texts: list[str]) -> str | None:
    """schema.org Product の category 項目からカテゴリ名を取り出す。"""
    for o in _iter_ldjson_objects(ld_texts):
        if not isinstance(o, dict):
            continue
        t = o.get("@type")
        is_product = t == "Product" or (isinstance(t, list) and "Product" in t)
        if not is_product:
            continue
        cat = o.get("category")
        if isinstance(cat, dict):
            cat = cat.get("name")
        if isinstance(cat, str) and cat.strip():
            return _mid_from_path(cat)
    return None


def _pick_mid_from_breadcrumb(names: list[str]) -> str | None:
    """パンくず（ルート→末端）から中カテゴリ名を選ぶ。

    先頭の「ホーム」的な要素や性別（レディース/メンズ）を除き、最も末端（具体的）を採用。
    """
    if not names:
        return None
    drop = {"ホーム", "Home", "HOME", "トップ画面", "ホーム画面",
            "レディース", "メンズ", "WOMEN", "MEN", "キッズ", "KIDS"}
    filtered = [n for n in names if n and n not in drop]
    seq = filtered or names
    return seq[-1]  # 最も具体的なカテゴリ（＝商品の中カテゴリ）


def _resolve_category_name(page, code: str, timeout_ms: int, log_detail: bool) -> str | None:
    """カテゴリページ /jp/category/{code} を開いてカテゴリ名を取得する。"""
    url = f"https://global.musinsa.com/jp/category/{code}?toggleCountry=jp"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(1500)
    except Exception as e:
        logger.warning("category page fetch failed for %s: %s", code, e)
        return None

    ld_texts = []
    try:
        ld_texts = page.evaluate(
            """() => Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
                .map(s => s.textContent).filter(Boolean)"""
        ) or []
    except Exception:
        ld_texts = []
    breadcrumb = _extract_breadcrumb_from_ldjson(ld_texts)

    title = ""
    h1 = ""
    try:
        title = page.title() or ""
        h1 = page.evaluate(
            """() => { const h = document.querySelector('h1, h2, [class*="title" i]');
                       return h ? (h.innerText || '').trim() : ''; }"""
        ) or ""
    except Exception:
        pass

    if log_detail:
        logger.info("  code %s: breadcrumb=%s, title=%r, h1=%r", code, breadcrumb, title[:60], h1[:40])

    name = _pick_mid_from_breadcrumb(breadcrumb)
    if not name and h1 and len(h1) <= 30:
        name = h1
    if not name and title:
        # サイト名等のサフィックスを除去
        name = re.split(r"[|\-–—:｜]", title)[0].strip() or None
    return name


def enrich_items_with_category(
    items: list[dict],
    *,
    request_interval_seconds: float = 1.0,
    timeout_ms: int = 20000,
    log_samples: int = 3,
    category_limit: int = 0,
) -> None:
    """items に in-place で `_category`（中カテゴリ名 or コード）を付与する。"""
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

    logger.info("Category enrichment: opening %d product pages (of %d items)...",
                len(goods_ids), len(items))

    seen_code: dict[str, str] = {"code": ""}

    def on_request(request) -> None:
        m = _ITEM_CAT_RE.search(request.url)
        if m:
            seen_code["code"] = m.group(1)

    goods_code: dict[str, str] = {}   # goodsNo -> itemCategoryCode
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=_USER_AGENT, locale="ja-JP")
        page = context.new_page()
        page.on("request", on_request)

        # --- フェーズ1: 各商品ページを開いて itemCategoryCode を集める ---
        for idx, g in enumerate(goods_ids):
            seen_code["code"] = ""
            url = f"https://global.musinsa.com/jp/goods/{g}?toggleCountry=jp"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(2000)
            except Exception as e:
                logger.warning("category fetch failed for goods %s: %s", g, e)
                page.wait_for_timeout(int(request_interval_seconds * 1000))
                continue

            code = seen_code["code"]
            if code:
                goods_code[g] = code
            if idx < log_samples:
                logger.info("goods %s: itemCategoryCode=%s", g, code or "(none)")
            if (idx + 1) % 25 == 0:
                logger.info("  code progress: %d/%d", idx + 1, len(goods_ids))
            page.wait_for_timeout(int(request_interval_seconds * 1000))

        # --- フェーズ2: ユニークなカテゴリコードを名前に変換（使い回し）---
        unique_codes = sorted(set(goods_code.values()))
        logger.info("Resolving %d unique category codes to names...", len(unique_codes))
        code_name: dict[str, str] = {}
        for j, code in enumerate(unique_codes):
            name = _resolve_category_name(page, code, timeout_ms, log_detail=j < log_samples)
            if name:
                code_name[code] = name
            page.wait_for_timeout(int(request_interval_seconds * 1000))

        browser.close()

    by_name = 0
    by_code = 0
    for it in items:
        g = str(it.get("goodsNo") or "")
        code = goods_code.get(g)
        if not code:
            continue
        name = code_name.get(code)
        if name:
            it["_category"] = name
            by_name += 1
        else:
            it["_category"] = code   # 名前解決に失敗したらコードのまま
            by_code += 1

    logger.info("Category enrichment done: %d by name, %d by code(fallback), of %d products",
                by_name, by_code, len(goods_ids))
