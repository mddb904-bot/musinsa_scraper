"""ブランド独自ランキング スクレイパー v4。

Playwrightでページを完全レンダリングした後、HTMLから複数パターンを試して
商品データを抽出する。
"""
from __future__ import annotations

import json as json_lib
import logging
import re
import time

from playwright.sync_api import sync_playwright

from ..parser import find_goods_in_obj, extract_goods_list_from_html

logger = logging.getLogger(__name__)


_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _extract_items_from_html(html: str, brand_slug: str) -> list[dict]:
    """複数の埋め込みパターンを試してHTMLから商品データを抽出する。"""
    # Strategy 1: const goodsList = "..." (既存パターン)
    try:
        items = extract_goods_list_from_html(html)
        if items:
            logger.info("brand=%s: Extracted %d items via goodsList pattern", brand_slug, len(items))
            return items
    except Exception:
        pass

    # Strategy 2: <script id="__NEXT_DATA__"> (Next.js)
    m = re.search(
        r'<script[^>]*id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html, re.DOTALL,
    )
    if m:
        try:
            data = json_lib.loads(m.group(1))
            items = find_goods_in_obj(data)
            if items:
                logger.info("brand=%s: Extracted %d items via __NEXT_DATA__", brand_slug, len(items))
                return items
        except Exception as e:
            logger.debug("__NEXT_DATA__ parse failed: %s", e)

    # Strategy 3: 任意の <script type="application/json"> から goods データ
    for m in re.finditer(
        r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL,
    ):
        try:
            data = json_lib.loads(m.group(1))
            items = find_goods_in_obj(data)
            if items:
                logger.info(
                    "brand=%s: Extracted %d items via application/json script",
                    brand_slug, len(items),
                )
                return items
        except Exception:
            continue

    # Strategy 4: window.__INITIAL_STATE__ など
    for var_name in ["__INITIAL_STATE__", "__PRELOADED_STATE__", "__NUXT__", "__APOLLO_STATE__"]:
        m = re.search(
            rf'window\.{re.escape(var_name)}\s*=\s*(\{{.*?\}});?\s*</script>',
            html, re.DOTALL,
        )
        if m:
            try:
                data = json_lib.loads(m.group(1))
                items = find_goods_in_obj(data)
                if items:
                    logger.info(
                        "brand=%s: Extracted %d items via window.%s",
                        brand_slug, len(items), var_name,
                    )
                    return items
            except Exception:
                continue

    # Strategy 5: 最後の手段 - HTML 内のキーワードを報告
    logger.warning(
        "[DEBUG] brand=%s: No extraction strategy worked. HTML keyword presence:",
        brand_slug,
    )
    for kw in ["__NEXT_DATA__", "goodsNo", "goodsInfoList", "goodsList", "brandId", "rankingList"]:
        logger.warning("  '%s' in HTML: %s", kw, kw in html)

    return []


def fetch_brand_ranking(
    brand_slug: str,
    period: str = "weekly",
    top_n: int = 200,
    timeout_ms: int = 30000,
    request_interval_seconds: float = 1.5,
) -> list[dict]:
    if period not in ("weekly", "monthly"):
        raise ValueError(f"period must be 'weekly' or 'monthly', got: {period}")

    url = f"https://global.musinsa.com/jp/brands/{brand_slug}/trending?period={period}"
    logger.info("Loading brand page: brand=%s period=%s", brand_slug, period)

    brand_lower = brand_slug.lower()
    html = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=_USER_AGENT,
            locale="ja-JP",
            viewport={"width": 1280, "height": 1800},
        )
        page = context.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception as e:
            logger.warning("page.goto: %s", e)

        # JS実行待ち
        time.sleep(5)

        # スクロールしてlazy-load発火
        for i in range(15):
            page.mouse.wheel(0, 5000)
            time.sleep(0.5)

        # レンダリング後のHTMLを取得
        try:
            html = page.content()
            logger.info("brand=%s: page HTML size=%d bytes", brand_slug, len(html))
        except Exception as e:
            logger.warning("page.content() failed: %s", e)

        browser.close()

    # HTMLから商品データを抽出
    raw_items = _extract_items_from_html(html, brand_slug)

    # 重複排除 + ブランドフィルタ
    seen_ids: set[str] = set()
    results: list[dict] = []
    skipped = 0
    for item in raw_items:
        gid = str(item.get("goodsNo") or "")
        if not gid or gid in seen_ids:
            continue
        seen_ids.add(gid)
        item_brand = str(item.get("brandId") or "").lower()
        if item_brand and item_brand != brand_lower:
            skipped += 1
            continue
        results.append(item)
        if len(results) >= top_n:
            break

    logger.info(
        "brand=%s period=%s: extracted=%d, this_brand=%d, other_skipped=%d",
        brand_slug, period, len(raw_items), len(results), skipped,
    )
    return results[:top_n]
