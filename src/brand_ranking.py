"""ブランドランキング スクレイパー (ブランド単位・日次)。

女性商品ランキングとは別系統。ブランドの順位表を取得する。

取得元API (ページ読み込み時に発火するのを Playwright で傍受):
    https://global.musinsa.com/api/global/trending/v2/brands
        ?countryCode=JP&languageCode=ja&toggleCountry=jp&categoryCode=

レスポンス data.brandList[] の各要素:
    - rank        … 順位
    - id          … ブランドID(slug)
    - name        … ブランド名
    - landingUrl  … /jp/brands/{slug}

「MUSINSA 独占」フラグはこのAPIには含まれないため、各ブランドページを
開いてバッジのテキスト有無で判定する (案A)。styled-components のクラス名は
デプロイごとに変わるので、"MUSINSA 独占" というテキストをアンカーにする。
"""
from __future__ import annotations

import logging
import time

from playwright.sync_api import sync_playwright, Response

logger = logging.getLogger(__name__)


_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_LIST_PAGE_URL = "https://global.musinsa.com/jp/trending/brands?toggleCountry=jp"
_API_MARKER = "trending/v2/brands"


def _abs_brand_url(landing: str | None) -> str | None:
    if not landing:
        return None
    if landing.startswith("/"):
        return f"https://global.musinsa.com{landing}"
    return landing


def _detect_exclusive(page, brand_url: str | None, timeout_ms: int) -> bool | None:
    """ブランドページを開いて「MUSINSA 独占」バッジの有無を判定する。

    Returns:
        True  … 独占バッジあり
        False … バッジなし(ページは正常に読めた)
        None  … ページを読めず判定不能
    """
    if not brand_url:
        return None
    try:
        page.goto(brand_url, wait_until="domcontentloaded", timeout=timeout_ms)
        time.sleep(1.5)
        text = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
    except Exception as e:
        logger.warning("exclusive check failed for %s: %s", brand_url, e)
        return None

    # 全角/半角スペースを除去して「MUSINSA独占」で判定
    normalized = text.replace(" ", "").replace("\u3000", "")
    if "MUSINSA独占" in normalized:
        return True
    return False


def fetch_brand_ranking_list(
    top_n: int = 100,
    detect_exclusive: bool = True,
    request_interval_seconds: float = 1.0,
    timeout_ms: int = 30000,
    exclusive_timeout_ms: int = 20000,
) -> list[dict]:
    """ブランドランキング上位N件を取得する。

    Returns: [{rank, brand_id, brand_name, brand_url, is_musinsa_exclusive}, ...]
    (rank 昇順)
    """
    captured: list[list[dict]] = []

    def on_response(response: Response) -> None:
        try:
            if _API_MARKER not in response.url:
                return
            body = response.json()
        except Exception:
            return
        bl = ((body or {}).get("data") or {}).get("brandList")
        if isinstance(bl, list) and bl:
            captured.append(bl)
            logger.info("Captured brandList: %d brands from %s", len(bl), response.url[:120])

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=_USER_AGENT,
            locale="ja-JP",
            viewport={"width": 1280, "height": 1800},
        )
        page = context.new_page()
        page.on("response", on_response)

        logger.info("Loading brand ranking page: %s", _LIST_PAGE_URL)
        try:
            page.goto(_LIST_PAGE_URL, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception as e:
            logger.warning("page.goto: %s", e)

        # APIレスポンスが傍受されるまで待つ
        for _ in range(20):
            if captured:
                break
            time.sleep(0.5)

        # まだなら軽くスクロールして再発火を促す
        if not captured:
            try:
                page.mouse.wheel(0, 3000)
                time.sleep(2)
            except Exception:
                pass

        brand_list = captured[0] if captured else []
        if not brand_list:
            logger.error("brandList not captured (page structure or API may have changed)")

        results: list[dict] = []
        for b in brand_list:
            results.append({
                "rank": b.get("rank"),
                "brand_id": b.get("id"),
                "brand_name": b.get("name"),
                "brand_url": _abs_brand_url(b.get("landingUrl")),
                "is_musinsa_exclusive": None,
            })

        # rank 昇順に整列して上位N件
        results.sort(key=lambda r: r["rank"] if r["rank"] is not None else 9999)
        results = results[:top_n]

        # 案A: 各ブランドページを開いて独占フラグを判定
        if detect_exclusive and results:
            logger.info("Detecting MUSINSA-exclusive flag across %d brand pages...", len(results))
            excl = 0
            for i, r in enumerate(results, 1):
                r["is_musinsa_exclusive"] = _detect_exclusive(
                    page, r["brand_url"], exclusive_timeout_ms
                )
                if r["is_musinsa_exclusive"]:
                    excl += 1
                if i % 20 == 0:
                    logger.info("  exclusive check progress: %d/%d", i, len(results))
                time.sleep(request_interval_seconds)
            logger.info("Exclusive detection done: %d/%d flagged exclusive", excl, len(results))

        browser.close()

    logger.info("Brand ranking: returning %d brands", len(results))
    return results
