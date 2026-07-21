"""商品の中カテゴリを、商品詳細ページを開いて取得する（方法A）。

ランキングAPIのレスポンスには中カテゴリが含まれないため、各商品の
詳細ページ (/jp/goods/{goodsNo}) を開き、ページ読み込み時に発火する
JSON レスポンスから「カテゴリ情報（category2Depth 相当＝中カテゴリ）」を
抽出する。重い処理（商品ごとに1ページ開く）なので、呼び出し側の
フラグで on/off する想定。

styled-components 等でクラス名が変わっても壊れないよう、JSON のキー名に
"categor" を含む項目を再帰的に探し、中カテゴリらしきものを選ぶ方式にしている。
最初の数商品については見つかった候補をログ出力し、実データで確認できるようにする。
"""
from __future__ import annotations

import logging

from playwright.sync_api import sync_playwright, Response

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _find_category_fields(obj, path: str = "") -> list[tuple[str, str, object]]:
    """キー名に 'categor' を含む（値がスカラーの）項目を (path, key, value) で列挙する。"""
    hits: list[tuple[str, str, object]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if (
                "categor" in str(k).lower()
                and not isinstance(v, (dict, list))
                and v not in (None, "")
            ):
                hits.append((path, str(k), v))
            hits.extend(_find_category_fields(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:10]):
            hits.extend(_find_category_fields(v, f"{path}[{i}]"))
    return hits


def _score_field(key: str) -> int:
    """中カテゴリ（第2階層の名称）らしさをスコア化する。"""
    kl = key.lower()
    s = 0
    if any(t in kl for t in ("2depth", "depth2", "category2", "middle", "second")):
        s += 100
    if "name" in kl:
        s += 10
    if any(t in kl for t in ("1depth", "depth1", "category1", "large", "first")):
        s -= 50
    if "brand" in kl:
        s -= 1000
    if "code" in kl or "id" in kl:
        s -= 20
    return s


def _pick_mid_category(fields: list[tuple[str, str, object]]) -> str | None:
    """候補から中カテゴリ（category2Depth 相当）の名称を選ぶ。"""
    named = [
        (p, k, v)
        for (p, k, v) in fields
        if isinstance(v, str) and not v.isdigit()
    ]
    if not named:
        return None
    best = max(named, key=lambda item: _score_field(item[1]))
    return best[2] if _score_field(best[1]) > -50 else None


def enrich_items_with_category(
    items: list[dict],
    *,
    request_interval_seconds: float = 1.0,
    timeout_ms: int = 20000,
    log_samples: int = 3,
) -> None:
    """items（商品オブジェクトのリスト）に in-place で `_category`（中カテゴリ）を付与する。

    goodsNo で重複排除し、ユニークな商品ごとに1回だけ詳細ページを開く。
    取得できなかった商品は `_category` を付与しない（= None のまま）。
    """
    if not items:
        return

    unique: dict[str, str | None] = {}
    for it in items:
        g = str(it.get("goodsNo") or "")
        if g:
            unique.setdefault(g, None)

    logger.info(
        "Category enrichment: opening %d unique product pages (of %d items)...",
        len(unique), len(items),
    )

    captured: dict[str, list] = {"fields": []}

    def on_response(response: Response) -> None:
        try:
            if "application/json" not in response.headers.get("content-type", ""):
                return
            body = response.json()
        except Exception:
            return
        captured["fields"].extend(_find_category_fields(body))

    got = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=_USER_AGENT, locale="ja-JP")
        page = context.new_page()
        page.on("response", on_response)

        for idx, g in enumerate(unique):
            captured["fields"] = []
            url = f"https://global.musinsa.com/jp/goods/{g}?toggleCountry=jp"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                # イベントループを回して category を含む JSON 応答を取りこぼさない
                for _ in range(6):
                    page.wait_for_timeout(500)
            except Exception as e:
                logger.warning("category fetch failed for goods %s: %s", g, e)

            fields = captured["fields"]
            if idx < log_samples:
                candidates = sorted({(k, str(v)) for (_, k, v) in fields})
                logger.info("goods %s category candidates: %s", g, candidates[:20])

            cat = _pick_mid_category(fields)
            unique[g] = cat
            if cat:
                got += 1

            if (idx + 1) % 25 == 0:
                logger.info("  category progress: %d/%d", idx + 1, len(unique))
            page.wait_for_timeout(int(request_interval_seconds * 1000))

        browser.close()

    for it in items:
        g = str(it.get("goodsNo") or "")
        if unique.get(g):
            it["_category"] = unique[g]

    logger.info(
        "Category enrichment done: %d/%d unique products got a mid-category",
        got, len(unique),
    )
