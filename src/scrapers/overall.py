"""女性全体ランキング (`/jp/trending/items`) スクレイパー。

HTMLに商品データが埋め込まれているSSR配信のため requests のみで完結する。
"""
from __future__ import annotations

import logging
import time

import requests

from ..parser import extract_goods_list_from_html

logger = logging.getLogger(__name__)


_BASE_URL = "https://global.musinsa.com/jp/trending/items"
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def fetch_overall_ranking(
    top_n: int = 200,
    gender: str = "F",
    request_interval_seconds: float = 2.0,
    timeout: int = 30,
) -> list[dict]:
    """女性全体ランキングの上位 N 件を取得する。

    1ページに約150件含まれるため、必要に応じて2ページ目以降を取得して結合する。
    """
    headers = {
        "User-Agent": _USER_AGENT,
        "Accept-Language": "ja,en;q=0.9",
    }

    results: list[dict] = []
    page = 1
    seen_goods_ids: set[str] = set()

    while len(results) < top_n:
        params = {"gender": gender, "page": page}
        logger.info("Fetching overall ranking page=%d", page)

        resp = requests.get(_BASE_URL, params=params, headers=headers, timeout=timeout)
        resp.raise_for_status()

        page_items = extract_goods_list_from_html(resp.text)
        if not page_items:
            logger.warning("page=%d returned no items, stopping", page)
            break

        added = 0
        for item in page_items:
            gid = str(item.get("goodsNo") or "")
            if not gid or gid in seen_goods_ids:
                continue
            seen_goods_ids.add(gid)
            results.append(item)
            added += 1
            if len(results) >= top_n:
                break

        logger.info("page=%d: added %d items (total=%d)", page, added, len(results))

        # 次ページの商品IDが全部既知ならループ終了 (=最終ページ)
        if added == 0:
            break

        page += 1
        if len(results) < top_n:
            time.sleep(request_interval_seconds)

    return results[:top_n]
