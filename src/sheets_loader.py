"""ブランド独自ランキング スクレイパー (API直接アクセス版)。

MUSINSAのトレンドAPIに brandIds パラメータを渡すことで、ブランド単位の
weekly / monthly ランキングを取得する。Playwrightより圧倒的に高速。
"""
from __future__ import annotations

import logging
import time

import requests

from ..parser import find_goods_in_obj

logger = logging.getLogger(__name__)


_API_URL = "https://global.musinsa.com/api/global/trending/v2/items"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def fetch_brand_ranking(
    brand_slug: str,
    period: str = "weekly",
    top_n: int = 200,
    timeout: int = 30,
    request_interval_seconds: float = 1.5,
) -> list[dict]:
    """ブランドの weekly/monthly ランキング上位N件を取得する。

    Args:
        brand_slug: URLスラッグ (例: 'mucent')
        period: 'weekly' または 'monthly'
        top_n: 取得上位件数
        timeout: HTTPタイムアウト(秒)
        request_interval_seconds: ページ間のリクエスト間隔

    Returns:
        商品オブジェクト (MUSINSA API形式) のリスト
    """
    if period not in ("weekly", "monthly"):
        raise ValueError(f"period must be 'weekly' or 'monthly', got: {period}")

    headers = {
        "User-Agent": _USER_AGENT,
        "Accept": "application/json",
        "Accept-Language": "ja,en;q=0.9",
        "Referer": f"https://global.musinsa.com/jp/brands/{brand_slug}/trending?period={period}",
    }

    results: list[dict] = []
    seen_ids: set[str] = set()
    page = 1

    while len(results) < top_n:
        params = {
            "brandIds": brand_slug,
            "period": period,
            "gender": "F",
            "page": page,
            "size": 150,
            "countryCode": "jp",
            "toggleCountry": "jp",
            "includeSoldout": "false",
            "excludeComingSoonGoods": "true",
        }
        logger.info(
            "brand=%s period=%s page=%d - fetching API",
            brand_slug, period, page,
        )

        try:
            resp = requests.get(_API_URL, params=params, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            logger.error("Request failed: %s", e)
            raise

        if resp.status_code != 200:
            logger.error(
                "API error: status=%d url=%s body=%s",
                resp.status_code, resp.url, resp.text[:500],
            )
            resp.raise_for_status()

        try:
            data = resp.json()
        except ValueError as e:
            logger.error(
                "JSON decode failed for brand=%s period=%s: %s, body=%s",
                brand_slug, period, e, resp.text[:500],
            )
            break

        items = find_goods_in_obj(data) or []
        if not items:
            logger.warning(
                "brand=%s period=%s page=%d: no goods items in response",
                brand_slug, period, page,
            )
            if isinstance(data, dict):
                logger.info("Top-level response keys: %s", list(data.keys())[:15])
            break

        added = 0
        for item in items:
            gid = str(item.get("goodsNo") or "")
            if not gid or gid in seen_ids:
                continue
            seen_ids.add(gid)
            results.append(item)
            added += 1
            if len(results) >= top_n:
                break

        logger.info(
            "brand=%s period=%s page=%d: added %d items (total=%d)",
            brand_slug, period, page, added, len(results),
        )

        if added == 0:
            # 同じ商品しか返ってこなくなった = 最終ページ
            break

        page += 1
        if len(results) < top_n:
            time.sleep(request_interval_seconds)

    logger.info(
        "brand=%s period=%s: returning %d items",
        brand_slug, period, len(results),
    )
    return results[:top_n]
