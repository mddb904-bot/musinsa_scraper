"""ブランド独自ランキング スクレイパー v8 - 歯抜け対策強化版。"""
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
    """商品画像URLを複数パターンで探す。"""
    # 様々な属性名を試す (lazy loading 対応)
    for attr in ["src", "data-src", "data-original", "data-lazy-src", "data-original-src"]:
        m = re.search(
            rf'<img[^>]+\b{attr}=["\']([^"\']*image\.msscdn\.net[^"\']+)["\']',
            section, re.IGNORECASE,
        )
        if m:
            return m.group(1)
    # srcset: "url1 1x, url2 2x" 形式から最初のURLを取る
    m = re.search(
        r'srcset=["\']([^"\']*image\.msscdn\.net[^"\']+)',
        section, re.IGNORECASE,
    )
    if m:
        return m.group(1).split(" ")[0].split(",")[0]
    # 任意の image.msscdn.net URL を最終手段で探す
    m = re.search(
        r'["\']([^"\']*image\.msscdn\.net/[^"\']+\.(?:jpg|jpeg|png|webp))["\']',
        section, re.IGNORECASE,
    )
    if m:
        return m.group(1)
    return None


def _extract_name(section: str) -> str | None:
    """商品名を複数パターンで探す。"""
    for pat in [
        r'data-goods-name=["\']([^"\']+)["\']',
        r'data-name=["\']([^"\']+)["\']',
        r'data-product-name=["\']([^"\']+)["\']',
        r'<img[^>]+alt=["\']([^"\']+)["\']',
        r'<p[^>]*class="[^"]*(?:goods|product)[-_]?name[^"]*"[^>]*>([^<]+)</p>',
        r'<span[^>]*class="[^"]*(?:goods|product)[-_]?name[^"]*"[^>]*>([^<]+)</span>',
    ]:
        m = re.search(pat, section, re.IGNORECASE)
        if m:
            v = m.group(1).strip()
            if v and len(v) < 200 and not v.startswith("¥"):
                return v
    return None


def _extract_prices(section: str) -> tuple[int | None, int | None, int | None]:
    """(price, normal_price, sale_rate) を返す。"""
    price = None
    normal_price = None
    sale_rate = None

    # ¥xxx を全て探す
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

    # フォールバック: data-price 属性
    if price is None:
        for pat in [r'data-price=["\']?(\d+)', r'data-sale-price=["\']?(\d+)']:
            m = re.search(pat, section)
            if m:
                try:
                    price = int(m.group(1))
                    break
                except ValueError:
                    continue

    # セール率
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
    """お気に入り数を複数パターンで探す。"""
    for pat in [
        r'data-like-count=["\']?(\d+)',
        r'data-favorite-count=["\']?(\d+)',
        r'data-likes?=["\']?(\d+)',
        r'"likeCount"\s*:\s*(\d+)',
        r'"favoriteCount"\s*:\s*(\d+)',
        r'aria-label=["\']?(?:いいね|お気に入り|likes?)[^"\']*?(\d+)',
        r'[♡♥❤]\s*([\d,]+)',
    ]:
        m = re.search(pat, s
