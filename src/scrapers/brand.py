"""ブランド独自ランキング スクレイパー v7 - 拡張抽出版。"""
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
    """HTMLから商品データを抽出する。data-goods-no 属性を基準に商品カードを切り分ける。"""
    # data-goods-no="..." を持つDOM要素を順番に列挙
    pattern = re.compile(r'data-goods-no=["\'](\d+)["\']')
    seen: set[str] = set()
    ordered: list[tuple[str, int]] = []
    for m in pattern.finditer(html):
        gid = m.group(1)
        if gid in seen:
            continue
        seen.add(gid)
        ordered.append((gid, m.start()))

    # フォールバック: data-goods-no が見つからなければURL基準
    if not ordered:
        for m in re.finditer(r'/jp/goods/(\d+)', html):
            gid = m.group(1)
            if gid in seen:
                continue
            seen.add(gid)
            ordered.append((gid, m.start()))

    logger.info(
        "brand=%s: found %d product positions",
        brand_slug, len(ordered),
    )

    if not ordered:
        return []

    # 初回(mucent)だけ、最初の商品セクションをログに出して構造確認
    if brand_slug.lower() == "mucent" and len(ordered) >= 2:
        first_gid, first_pos = ordered[0]
        first_section = html[first_pos:ordered[1][1]]
        logger.warning(
            "[DIAG] brand=%s first product section (gid=%s, %d chars):",
            brand_slug, first_gid, len(first_section),
        )
        clean = first_section.replace("\n", " ")
        for j in range(0, min(len(clean), 2400), 250):
            logger.warning("  %s", clean[j:j + 250])

    items = []
    for i, (gid, pos) in enumerate(ordered):
        if i + 1 < len(ordered):
            section = html[pos:ordered[i + 1][1]]
        else:
            section = html[pos:pos + 5000]

        # 商品名: 複数パターンを試す
        name = None
        for pat in [
            r'data-goods-name=["\']([^"\']+)["\']',
            r'<img[^>]+alt=["\']([^"\']+)["\']',
            r'data-name=["\']([^"\']+)["\']',
            r'<p[^>]*class="[^"]*goods?[-_]?name[^"]*"[^>]*>([^<]+)</p>',
        ]:
            m = re.search(pat, section, re.IGNORECASE)
            if m:
                v = m.group(1).strip()
                if v and len(v) < 200:
                    name = v
                    break

        # 画像URL
        img_url = None
        img_m = re.search(
            r'<img[^>]+src=["\']([^"\']*image\.msscdn\.net[^"\']+)["\']',
            section, re.IGNORECASE,
        )
        if img_m:
            img_url = img_m.group(1)

        # 価格(セール後 = 最後の ¥xxx)
        price_matches = re.findall(r'¥\s*([\d,]+)', section)
        price = None
        normal_price = None
        if price_matches:
            try:
                price = int(price_matches[-1].replace(",", ""))
                normal_price = (
                    int(price_matches[0].replace(",", ""))
                    if len(price_matches) >= 2 else price
                )
            except ValueError:
                pass

        # セール率
        sale_rate = None
        rate_m = re.search(r'(\d{1,2})\s*%(?:\s*OFF)?', section)
        if rate_m:
            try:
                v = int(rate_m.group(1))
                if 0 < v < 100:
                    sale_rate = v
            except ValueError:
                pass

        # お気に入り数: 複数パターン
        like_count = None
        for pat in [
            r'data-like-count=["\'](\d+)["\']',
            r'data-favorite-count=["\'](\d+)["\']',
            r'data-likes?=["\'](\d+)["\']',
            r'"likeCount"\s*:\s*(\d+)',
            r'aria-label=["\']?(?:いいね|お気に入り|likes?)[^"\']*?(\d+)',
        ]:
            m = re.search(pat, section, re.IGNORECASE)
            if m:
                try:
                    like_count = int(m.group(1))
                    break
                except ValueError:
                    continue

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

    # 抽出できた項目数のサマリ
    if items:
        sample = items[0]
        logger.info(
            "brand=%s: sample item - name=%s, image=%s, price=%s, likes=%s",
            brand_slug,
            (sample.get("goodsName") or "")[:30],
            "OK" if sample.get("imageUrl") else "MISSING",
            sample.get("price"),
            sample.get("likeCount") or "MISSING",
        )

    logger.info(
        "brand=%s period=%s: returning %d items",
        brand_slug, period, len(items),
    )
    return items[:top_n]
