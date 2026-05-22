"""ブランド独自ランキング スクレイパー v9 - data-goods-nm 対応 + 完全診断ダンプ。"""
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


def _extract_image_url(section: str) -> str | None:
    for attr in ["src", "data-src", "data-original", "data-lazy-src", "data-original-src"]:
        m = re.search(
            rf'<img[^>]+\b{attr}=["\']([^"\']*image\.msscdn\.net[^"\']+)["\']',
            section, re.IGNORECASE,
        )
        if m:
            return m.group(1)
    m = re.search(
        r'srcset=["\']([^"\']*image\.msscdn\.net[^"\']+)',
        section, re.IGNORECASE,
    )
    if m:
        return m.group(1).split(" ")[0].split(",")[0]
    m = re.search(
        r'["\']([^"\']*image\.msscdn\.net/[^"\']+\.(?:jpg|jpeg|png|webp))["\']',
        section, re.IGNORECASE,
    )
    if m:
        return m.group(1)
    return None


def _extract_name(section: str) -> str | None:
    # 1. MUSINSAの実際の属性: data-goods-nm が最優先
    m = re.search(r'data-goods-nm=["\']([^"\']+)["\']', section)
    if m:
        v = m.group(1).strip()
        if v and len(v) < 200:
            return v
    # 2. <img alt="..."> の "undefined_" プレフィックスを除去
    m = re.search(r'<img[^>]+alt=["\']([^"\']+)["\']', section, re.IGNORECASE)
    if m:
        v = m.group(1).strip()
        if v.startswith("undefined_"):
            v = v[len("undefined_"):].strip()
        if v and len(v) < 200:
            return v
    # 3. その他フォールバック
    for pat in [
        r'data-goods-name=["\']([^"\']+)["\']',
        r'data-name=["\']([^"\']+)["\']',
        r'data-product-name=["\']([^"\']+)["\']',
    ]:
        m = re.search(pat, section, re.IGNORECASE)
        if m:
            v = m.group(1).strip()
            if v and len(v) < 200:
                return v
    return None


def _extract_prices(section: str) -> tuple[int | None, int | None, int | None]:
    price = None
    normal_price = None
    sale_rate = None
    price_matches = re.findall(r'¥\s*([\d,]+)', section)
    if price_matches:
        try:
            price = int(price_matches[-1].replace(",", ""))
            normal_price = (
                int(price_matches[0].replace(",", ""))
                if len(price_matches) >= 2 else price
            )
        except ValueError:
            pass
    if price is None:
        for pat in [r'data-price=["\']?(\d+)', r'data-sale-price=["\']?(\d+)']:
            m = re.search(pat, section)
            if m:
                try:
                    price = int(m.group(1))
                    break
                except ValueError:
                    continue
    rate_m = re.search(r'(\d{1,2})\s*%(?:\s*OFF)?', section)
    if rate_m:
        try:
            v = int(rate_m.group(1))
            if 0 < v < 100:
                sale_rate = v
        except ValueError:
            pass
    return price, normal_price, sale_rate


def _extract_like_count(section: str) -> int | None:
    for pat in [
        r'data-like-count=["\']?(\d+)',
        r'data-favorite-count=["\']?(\d+)',
        r'data-likes=["\']?(\d+)',
        r'"likeCount"\s*:\s*(\d+)',
        r'"favoriteCount"\s*:\s*(\d+)',
        r'aria-label=["\']?(?:いいね|お気に入り|likes?)[^"\']*?(\d+)',
        r'[♡♥❤]\s*([\d,]+)',
        # 追加: GTM クラス や like/wish/favorite クラスの近く
        r'class="[^"]*(?:like|wish|favorite)[-_]?(?:count|num)[^"]*"[^>]*>([\d,]+)',
        r'gtm-like[^>]*>([\d,]+)',
    ]:
        m = re.search(pat, section, re.IGNORECASE)
        if m:
            try:
                v = m.group(1).replace(",", "")
                return int(v)
            except ValueError:
                continue
    return None


def _extract_from_html(html: str, brand_slug: str) -> list[dict]:
    pattern = re.compile(r'data-goods-no=["\'](\d+)["\']')
    seen: set[str] = set()
    ordered: list[tuple[str, int]] = []
    for m in pattern.finditer(html):
        gid = m.group(1)
        if gid in seen:
            continue
        seen.add(gid)
        ordered.append((gid, m.start()))

    if not ordered:
        for m in re.finditer(r'/jp/goods/(\d+)', html):
            gid = m.group(1)
            if gid in seen:
                continue
            seen.add(gid)
            ordered.append((gid, m.start()))

    logger.info("brand=%s: found %d product positions", brand_slug, len(ordered))

    if not ordered:
        return []

    # mucent の最初の商品セクションを「全部」ダンプ(構造確認用)
    if brand_slug.lower() == "mucent" and len(ordered) >= 2:
        first_gid, first_pos = ordered[0]
        first_section = html[first_pos:ordered[1][1]]
        logger.warning(
            "[DIAG] brand=%s FULL first product section (gid=%s, total=%d chars):",
            brand_slug, first_gid, len(first_section),
        )
        clean = first_section.replace("\n", " ")
        for j in range(0, len(clean), 250):
            logger.warning("  [%d] %s", j, clean[j:j + 250])

    items = []
    missing_stats = {"name": 0, "image": 0, "price": 0, "like": 0}
    for i, (gid, pos) in enumerate(ordered):
        if i + 1 < len(ordered):
            section = html[pos:ordered[i + 1][1]]
        else:
            section = html[pos:pos + 5000]

        name = _extract_name(section)
        img_url = _extract_image_url(section)
        price, normal_price, sale_rate = _extract_prices(section)
        like_count = _extract_like_count(section)

        if not name:
            missing_stats["name"] += 1
        if not img_url:
            missing_stats["image"] += 1
        if price is None:
            missing_stats["price"] += 1
        if like_count is None:
            missing_stats["like"] += 1

        items.append({
            "goodsNo": gid,
            "goodsName": name,
            "brandId": brand_slug,
            "brandName": brand_slug.upper(),
            "imageUrl": img_url,
            "price": price,
            "normalPrice": normal_price,
            "saleRate": sale_rate,
            "likeCount": like_count,
            "landingUrl": f"/jp/goods/{gid}",
        })

    total = len(items)
    logger.info(
        "brand=%s: extraction stats out of %d - missing: name=%d, image=%d, price=%d, like=%d",
        brand_slug, total,
        missing_stats["name"], missing_stats["image"],
        missing_stats["price"], missing_stats["like"],
    )

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
