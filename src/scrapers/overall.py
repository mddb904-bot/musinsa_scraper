"""女性全体ランキング スクレイパー (Playwright版)。

ブラウザで実際にwomenタブのページをロードし、サイトと同じデータを取得する。
"""
from __future__ import annotations

import logging
import time

from playwright.sync_api import sync_playwright, Response

from ..parser import find_goods_in_obj

logger = logging.getLogger(__name__)


_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def fetch_overall_ranking(
    top_n: int = 200,
    gender: str = "F",
    request_interval_seconds: float = 2.0,
    timeout_ms: int = 60000,
) -> list[dict]:
    """女性全体ランキング上位N件をブラウザ経由で取得する。"""
    url = (
        f"https://global.musinsa.com/jp/trending/items"
        f"?gender={gender}&page=1&toggleCountry=jp"
    )
    logger.info("Loading overall page: %s", url)

    captured: list[tuple[str, list[dict]]] = []

    def on_response(response: Response) -> None:
        try:
            if response.request.resource_type not in ("fetch", "xhr", "document"):
                return
            ct = response.headers.get("content-type", "")
            if "application/json" not in ct and "text/html" not in ct:
                return
            if "application/json" in ct:
                body = response.json()
            else:
                # SSR HTML から goodsList を抽出
                from ..parser import extract_goods_list_from_html
                html = response.text()
                try:
                    items = extract_goods_list_from_html(html)
                    if items:
                        captured.append((response.url, items))
                        logger.info(
                            "Captured %d items from SSR HTML: %s",
                            len(items), response.url[:120],
                        )
                except Exception:
                    pass
                return
        except Exception as e:
            return
        items = find_goods_in_obj(body)
        if items and len(items) >= 5:
            # 女性向けデータのみフィルタ
            if f"gender={gender}" in response.url or "gender=F" in response.url:
                captured.append((response.url, items))
                logger.info(
                    "Captured %d items from API: %s",
                    len(items), response.url[:120],
                )

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
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        except Exception as e:
            logger.warning("page.goto: %s", e)

        # スクロールして遅延ロードを発火
        prev_count = 0
        for i in range(50):
            page.mouse.wheel(0, 5000)
            try:
                page.wait_for_load_state("networkidle", timeout=4000)
            except Exception:
                pass
            time.sleep(0.6)
            current_count = sum(len(items) for _, items in captured)
            if current_count >= top_n:
                break
            if current_count == prev_count and i > 5:
                logger.info("No new items after scroll %d, stopping", i)
                break
            prev_count = current_count

        browser.close()

    # 受信した順に重複排除 (= サイトの表示順 = ランキング順)
    seen_ids: set[str] = set()
    results: list[dict] = []
    for resp_url, items in captured:
        for item in items:
            gid = str(item.get("goodsNo") or "")
            if not gid or gid in seen_ids:
                continue
            seen_ids.add(gid)
            results.append(item)
            if len(results) >= top_n:
                break
        if len(results) >= top_n:
            break

    logger.info("Overall: collected %d, returning top %d", len(results), min(top_n, len(results)))
    return results[:top_n]
