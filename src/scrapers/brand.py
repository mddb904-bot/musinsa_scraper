"""ブランド独自ランキング スクレイパー v6 - 価格抽出修正版。"""
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


def _extract_from_html(html: str, brand_slug: str) -> list[dict]:
    """HTMLから商品データを抽出する。"""
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

    # 各商品の周辺HTMLから属性を抽出
    items = []
    for i, (gid, pos) in enumerate(ordered_with_pos):
        # 次の商品の開始位置までを切り出す (なければ末尾までだが範囲を制限)
        if i + 1 < len(ordered_with_pos):
            next_pos = ordered_with_pos[i + 1][1]
            section = html[pos:next_pos]
        else:
            section = html[pos:pos + 3000]

        # 画像URL
        img_url = None
        img_m = re.search(
            r'<img[^>]+src=["\']([^"\']*image\.msscdn\.net[^"\']+)["\']',
            section, re.IGNORECASE,
        )
        if img_m:
            img_url = img_m.group(1)

        # 価格抽出: ¥価格 を全部拾って、後ろにあるものを採用
        # 定価 → 割引率 → セール後 の順で出るため、最後の数値=セール後価格
        price_matches = re.findall(r'¥\s*([\d,]+)', section)
        price = None
        normal_price = None
        sale_rate = None
        if price_matches:
            try:
                # 最後の価格 = セール後価格 (セールしてない場合は定価と同じ)
                price = int(price_matches[-1].replace(",", ""))
                # 複数価格があれば最初が定価
                if len(price_matches) >= 2:
                    normal_price = int(price_matches[0].replace(",", ""))
                else:
                    normal_price = price
            except ValueError:
                pass

        # セール率 (例: "10%" "20%" などの数字%パターン)
        # 価格の近くに 数字% があれば割引率と判定
        rate_m = re.search(r'(\d{1,2})\s*%\s*OFF|(\d{1,2})\s*%', section)
        if rate_m:
            try:
                rate_str = rate_m.group(1) or rate_m.group(2)
                rate_val = int(rate_str)
                if 0 < rate_val < 100:
                    sale_rate = rate_val
            except (ValueError, TypeError):
                pass

        items.append({
            "goodsNo": gid,
            "brandId": brand_slug,
            "brandName": brand_slug.upper(),
            "imageUrl": img_url,
            "price": price,                # セール後 (なければ定価と同じ)
            "normalPrice": normal_price,   # 定価
            "saleRate": sale_rate,         # セール率(%)
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

    items = _extract_from_html(html, brand_slug)

    logger.info(
        "brand=%s period=%s: returning %d items",
        brand_slug, period, len(items),
    )
    return items[:top_n]
