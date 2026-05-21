"""ブランド独自ランキング スクレイパー v5 - HTML DOM抽出 + 診断ダンプ。"""
from __future__ import annotations

import logging
import re
import time

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)


_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _dump_html_samples(html: str, brand_slug: str) -> None:
    """goodsNo出現箇所の周辺を診断ダンプ。"""
    positions = []
    search_start = 0
    while len(positions) < 3:
        idx = html.find("goodsNo", search_start)
        if idx < 0:
            break
        positions.append(idx)
        search_start = idx + 1

    for i, pos in enumerate(positions, 1):
        start = max(0, pos - 200)
        end = min(len(html), pos + 600)
        sample = html[start:end].replace("\n", " ").replace("  ", " ")
        logger.warning(
            "[DIAG] brand=%s goodsNo #%d at offset=%d, total=%d:",
            brand_slug, i, pos, len(html),
        )
        # 250文字ずつ分割してログ
        for j in range(0, len(sample), 250):
            logger.warning("  %s", sample[j:j+250])


def _extract_from_html(html: str, brand_slug: str) -> list[dict]:
    """HTMLから商品データを抽出する(URLパターン中心)。"""
    # /jp/goods/<数字> の出現順 = ランキング順
    pattern = re.compile(r'/jp/goods/(\d+)')
    seen: set[str] = set()
    ordered_with_pos: list[tuple[str, int]] = []
    for m in pattern.finditer(html):
        gid = m.group(1)
        if gid in seen:
            continue
        seen.add(gid)
        ordered_with_pos.append((gid, m.start()))

    logger.info(
        "brand=%s: extracted %d unique goodsNo from URL patterns",
        brand_slug, len(ordered_with_pos),
    )

    if not ordered_with_pos:
        return []

    # 各商品の周辺HTMLから画像URLと価格を抽出
    items = []
    for gid, pos in ordered_with_pos:
        # 各商品の周辺2500文字を切り出して属性を探す
        section = html[pos:pos + 3000]

        img_url = None
        img_m = re.search(
            r'<img[^>]+src=["\']([^"\']*image\.msscdn\.net[^"\']+)["\']',
            section, re.IGNORECASE,
        )
        if img_m:
            img_url = img_m.group(1)

        price = None
        price_m = re.search(r'¥\s*([\d,]+)', section)
        if price_m:
            try:
                price = int(price_m.group(1).replace(",", ""))
            except ValueError:
                price = None

        items.append({
            "goodsNo": gid,
            "brandId": brand_slug,
            "brandName": brand_slug.upper(),
            "imageUrl": img_url,
            "price": price,
            # 他のフィールドはNULL
        })

    return items


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

        time.sleep(5)

        for i in range(15):
            page.mouse.wheel(0, 5000)
            time.sleep(0.5)

        try:
            html = page.content()
        except Exception as e:
            logger.warning("page.content() failed: %s", e)

        browser.close()

    logger.info("brand=%s: HTML size=%d bytes", brand_slug, len(html))

    # 最初のブランド(mucent)の最初のperiod(weekly)時にHTMLサンプルをダンプ
    # → 構造解析用の診断情報
    if brand_slug.lower() == "mucent" and period == "weekly":
        _dump_html_samples(html, brand_slug)

    # HTML抽出
    items = _extract_from_html(html, brand_slug)

    logger.info(
        "brand=%s period=%s: returning %d items",
        brand_slug, period, len(items),
    )
    return items[:top_n]
