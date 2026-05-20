"""ブランド独自ランキング (`/jp/brands/{slug}/trending?period=...`) スクレイパー。

ブランドページは完全クライアントサイドレンダリング(CSR)のため、
Playwrightで実ブラウザを起動し、ページが内部的に叩くAPIレスポンスを
ネットワーク傍受して `goodsInfoList` を取得する。
"""
from __future__ import annotations

import logging
import time
from typing import Any

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
    timeout_ms: int = 30000,
) -> list[dict]:
    """ブランドページからランキング上位N件を取得する。

    Args:
        brand_slug: URLスラッグ (例: 'mucent')
        period: 'weekly' または 'monthly'
        top_n: 取得上位件数
        timeout_ms: ページロードタイムアウト(ミリ秒)

    Returns:
        商品オブジェクト(MUSINSA API形式)のリスト
    """
    if period not in ("weekly", "monthly"):
        raise ValueError(f"period must be 'weekly' or 'monthly', got: {period}")

    url = f"https://global.musinsa.com/jp/brands/{brand_slug}/trending?period={period}"
    logger.info("Loading brand page: %s", url)

    collected: list[dict] = []
    seen_ids: set[str] = set()

    def on_response(response: Response) -> None:
        """全ネットワークレスポンスを傍受し、goodsInfoList を含むJSONを拾う。"""
        try:
            ct = response.headers.get("content-type", "")
            if "application/json" not in ct:
                return
            body = response.json()
        except Exception:
            return
        items = find_goods_in_obj(body)
        if not items:
            return
        for it in items:
            gid = str(it.get("goodsNo") or "")
            if not gid or gid in seen_ids:
                continue
            seen_ids.add(gid)
            collected.append(it)
        logger.debug("Captured %d items from %s", len(items), response.url[:80])

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=_USER_AGENT,
            locale="ja-JP",
            viewport={"width": 1280, "height": 1600},
        )
        page = context.new_page()
        page.on("response", on_response)

        try:
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        except Exception as e:
            logger.warning("page.goto raised %s, continuing with captured data", e)

        # 必要件数に達するまで下スクロールを繰り返してlazy-loadingを発火させる
        max_scrolls = 30
        for i in range(max_scrolls):
            if len(collected) >= top_n:
                break
            prev = len(collected)
            page.mouse.wheel(0, 4000)
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            time.sleep(1.0)
            if len(collected) == prev:
                # データが増えなくなったら終了
                logger.info("No more items after scroll #%d (total=%d)", i + 1, len(collected))
                break

        browser.close()

    logger.info(
        "brand=%s period=%s: collected %d items (returning top %d)",
        brand_slug, period, len(collected), min(top_n, len(collected)),
    )
    return collected[:top_n]
