"""ブランド独自ランキング スクレイパー (高速Playwright版 v2)。

ブランドページが呼ぶ全JSONレスポンスを取得し、商品の brandId で
そのブランドの商品だけを抽出する。
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


def fetch_brand_ranking(
    brand_slug: str,
    period: str = "weekly",
    top_n: int = 200,
    timeout_ms: int = 20000,
    request_interval_seconds: float = 1.5,
) -> list[dict]:
    """ブランドの weekly/monthly ランキングをブラウザ経由で取得する。"""
    if period not in ("weekly", "monthly"):
        raise ValueError(f"period must be 'weekly' or 'monthly', got: {period}")

    url = f"https://global.musinsa.com/jp/brands/{brand_slug}/trending?period={period}"
    logger.info("Loading brand page: brand=%s period=%s", brand_slug, period)

    captured: list[tuple[str, list[dict]]] = []
    brand_lower = brand_slug.lower()

    def on_response(response: Response) -> None:
        try:
            if response.request.resource_type not in ("fetch", "xhr"):
                return
            ct = response.headers.get("content-type", "")
            if "application/json" not in ct:
                return
            body = response.json()
        except Exception:
            return
        items = find_goods_in_obj(body)
        if items and len(items) >= 1:
            # URLフィルタなし: 全てのgoodsInfoListを保持
            # 商品レベルで brand_id を見て後でフィルタする
            captured.append((response.url, items))
            logger.info(
                "[CAPTURE] brand=%s %d items from %s",
                brand_slug, len(items), response.url[:200],
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
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception as e:
            logger.warning("page.goto: %s", e)

        # 初期APIコール待ち
        time.sleep(3)

        # スクロール
        prev_count = 0
        for i in range(15):
            page.mouse.wheel(0, 5000)
            time.sleep(0.6)
            current_count = sum(len(items) for _, items in captured)
            if current_count >= top_n * 2:  # ブランドフィルタで半分減る想定で多めに
                break
            if current_count == prev_count and i > 3:
                logger.info(
                    "brand=%s period=%s: no new captured items after scroll %d",
                    brand_slug, period, i,
                )
                break
            prev_count = current_count

        browser.close()

    # 重複排除 + brand_id でフィルタ
    seen_ids: set[str] = set()
    results: list[dict] = []
    skipped_other_brand = 0
    for _, items in captured:
        for item in items:
            gid = str(item.get("goodsNo") or "")
            if not gid or gid in seen_ids:
                continue
            seen_ids.add(gid)
            # ブランドが一致する商品のみ採用
            item_brand = str(item.get("brandId") or "").lower()
            if item_brand and item_brand != brand_lower:
                skipped_other_brand += 1
                continue
            results.append(item)
            if len(results) >= top_n:
                break
        if len(results) >= top_n:
            break

    logger.info(
        "brand=%s period=%s: captured_total=%d, this_brand=%d, other_brand_skipped=%d",
        brand_slug, period, len(seen_ids), len(results), skipped_other_brand,
    )
    return results[:top_n]
