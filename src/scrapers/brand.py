"""ブランド独自ランキング スクレイパー v10 - data-product-id 境界方式。"""
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
    for attr in ["src", "data-src", "data-original", "data-lazy-src"]:
        m = re.search(
            rf'<img[^>]+\b{attr}=["\']([^"\']*image\.msscdn\.net[^"\']+)["\']',
            section, re.IGNORECASE,
        )
        if m:
            return m.group(1)
    m = re.search(r'srcset=["\']([^"\']*image\.msscdn\.net[^"\']+)', section, re.IGNORECASE)
    if m:
        return m.group(1).split(" ")[0].split(",")[0]
    return None


def _safe_int(s: str | None) -> int | None:
    if not s:
        return None
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def _extract_from_html(html: str, brand_slug: str) -> list[dict]:
    """<li data-product-id="N"> 要素の属性から商品データを抽出する。

    MUSINSAのHTML構造:
    <li data-product-id="N" data-product-name="..." data-like-count="X"
        data-price="Y" data-original-price="Z" data-discount-rate="W"
        data-index="ランク" ...>
      <div>
        <img src="画像URL"> ... (li ボディ)
      </div>
    </li>
    """
    seen: set[str] = set()
    products: list[dict] = []

    for m in re.finditer(r'\bdata-product-id=["\'](\d+)["\']', html):
        gid = m.group(1)
        if gid in seen:
            continue
        seen.add(gid)
        pos = m.start()

        # data-product-id の前にある <li ... を逆方向検索
        li_start = -1
        for tag in ['<li ', '<li\t', '<li\n', '<li\r']:
            found = html.rfind(tag, max(0, pos - 3000), pos)
            if found > li_start:
                li_start = found
        if li_start < 0:
            continue

        # <li> 開始タグの末尾 > を検索
        gt_pos = html.find('>', pos)
        if gt_pos < 0:
            continue

        li_opening = html[li_start:gt_pos + 1]

        def _a(pattern: str) -> str | None:
            r = re.search(pattern, li_opening)
            return r.group(1) if r else None

        name = _a(r'data-product-name=["\']([^"\']+)["\']')
        like_count = _safe_int(_a(r'data-like-count=["\'](\d+)["\']'))
        price = _safe_int(_a(r'data-price=["\'](\d+)["\']'))
        normal_price = _safe_int(_a(r'data-original-price=["\'](\d+)["\']'))
        sale_rate = _safe_int(_a(r'data-discount-rate=["\'](\d+)["\']'))
        rank_index = _safe_int(_a(r'data-index=["\'](\d+)["\']'))

        # <li> ボディから画像URLを取得
        next_li_m = re.search(r'<li[\s>]', html[gt_pos + 1:gt_pos + 7000])
        body_end = gt_pos + 1 + next_li_m.start() if next_li_m else gt_pos + 6000
        li_body = html[gt_pos + 1:body_end]
        img_url = _extract_image_url(li_body)

        products.append({
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
            "_rank_index": rank_index if rank_index is not None else 9999,
        })

    # ランク順にソート
    products.sort(key=lambda x: x["_rank_index"])
    for p in products:
        p.pop("_rank_index", None)

    total = len(products)
    missing = {
        k: sum(1 for p in products if not p.get(k))
        for k in ("goodsName", "imageUrl", "price", "likeCount")
    }
    logger.info(
        "brand=%s: extracted %d products. missing: name=%d, image=%d, price=%d, like=%d",
        brand_slug, total,
        missing["goodsName"], missing["imageUrl"],
        missing.get("price", 0), missing["likeCount"],
    )
    return products


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
        for i in range(20):
            page.mouse.wheel(0, 2000)  # 小さいスクロール幅で確実に
            time.sleep(1.5)            # React描画待ち
        # スクロール後、追加で描画を待つ
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        time.sleep(2)
        try:
            html = page.content()
        except Exception as e:
            logger.warning("page.content() failed: %s", e)
        browser.close()

    logger.info("brand=%s: HTML size=%d bytes", brand_slug, len(html))
    items = _extract_from_html(html, brand_slug)
    logger.info("brand=%s period=%s: returning %d items", brand_slug, period, len(items))
    return items[:top_n]
