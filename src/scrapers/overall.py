"""女性全体ランキング スクレイパー (Playwright版)。

ブラウザで実際にwomenタブのページをロードし、サイトと同じデータを取得する。
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


def fetch_overall_ranking(
    top_n: int = 200,
    gender: str = "F",
    request_interval_seconds: float = 2.0,
    timeout_ms: int = 60000,
) -> list[dict]:
    """女性全体ランキング上位N件をブラウザ経由で取得する。"""
    url = (
        f"https://global.musinsa.com/jp/trending/items"
        f"?gender={gender}&page=1&toggleCountry=jp"
    )
    logger.info("Loading overall page: %s", url)

    captured: list[tuple[str, list[
