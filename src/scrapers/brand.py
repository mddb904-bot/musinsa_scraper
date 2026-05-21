"""ブランド独自ランキング スクレイパー (デバッグ強化版 v3)。"""
from __future__ import annotations

import json as json_lib
import logging
import time

from playwright.sync_api import sync_playwright, Response

from ..parser import find_goods_in_obj, extract_goods_list_from_html

logger = logging.getLogger(__name__)


_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


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
    logger.info("Loading brand page: brand=%s period=%s url=%s", brand_slug, period, url)

    captured: list[tuple[str, list[dict]]] = []
    all_xhr: list[tuple[str, str, int, int]] = []  # (url, ct, status, body_len)
    brand_lower = brand_slug.lower()

    def on_response(response: Response) -> None:
        try:
            rtype = response.request.resource_type
            if rtype not in ("fetch", "xhr"):
                return
            url_str = response.url
            try:
                ct = response.headers.get("content-type", "")
            except Exception:
                ct = ""
            status = response.status
            body_len = 0
            json_data = None
            if "application/json" in ct or "text/json" in ct:
                try:
                    text = response.text()
                    body_len = len(text)
                    if text:
                        json_data = json_lib.loads(text)
                except Exception:
                    pass
            all_xhr.append((url_str, ct[:60], status, body_len))

            if json_data is not None:
                items = find_goods_in_obj(json_data)
                if items:
                    logger.info(
                        "[CAPTURE] brand=%s %d items from %s (body=%d)",
                        brand_slug, len(items), url_str[:180], body_len,
                    )
                    captured.append((url_str, items))
        except Exception as e:
            logger.debug("on_response error: %s", e)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=_USER_AGENT,
            locale="ja-JP",
            viewport={"width": 1280, "height": 1800},
        )
        page = context.new_page()
        page.on("response", on_response)

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception as e:
            logger.warning("page.goto: %s", e)

        # 初期APIコール待ち (長めに5秒)
        time.sleep(5)

        prev_count = 0
        for i in range(20):
            page.mouse.wheel(0, 5000)
            time.sleep(0.8)
            current_count = sum(len(items) for _, items in captured)
            if current_count >= top_n * 2:
                break
            if current_count == prev_count and i > 5:
                logger.info(
                    "brand=%s period=%s: no new items after scroll %d",
                    brand_slug, period, i,
                )
                break
            prev_count = current_count

        # フォールバック: HTMLから抽出を試す
        if not captured:
            try:
                html = page.content()
                logger.info(
                    "brand=%s: HTML extraction fallback (page=%d bytes)",
                    brand_slug, len(html),
                )
                try:
                    items = extract_goods_list_from_html(html)
                    if items:
                        captured.append(("html-fallback", items))
                        logger.info("HTML extracted %d items", len(items))
                except Exception:
                    pass
            except Exception as e:
                logger.warning("page.content() failed: %s", e)

        # 失敗時: 全XHR URL を WARN レベルで出す (ログに必ず残る)
        if not captured:
            logger.warning(
                "[DEBUG] brand=%s period=%s NO ITEMS - %d XHR responses:",
                brand_slug, period, len(all_xhr),
            )
            for i, (u, ct, status, blen) in enumerate(all_xhr[:25]):
                logger.warning(
                    "  [%d] status=%d ct=%s len=%d url=%s",
                    i, status, ct, blen, u[:180],
                )

        browser.close()

    seen_ids: set[str] = set()
    results: list[dict] = []
    skipped = 0
    for _, items in captured:
        for item in items:
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
        if len(results) >= top_n:
            break

    logger.info(
        "brand=%s period=%s: captured_total=%d, this_brand=%d, skipped=%d",
        brand_slug, period, len(seen_ids), len(results), skipped,
    )
    return results[:top_n]
