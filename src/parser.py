"""HTML/JSON から商品データを抽出する共通ロジック。"""
from __future__ import annotations

import re
import json
from datetime import date
from typing import Any


# 画像URLパスから掲載日(YYYY-MM-DD)を推定する正規表現
_LISTING_DATE_RE = re.compile(r"/goods_img/(\d{8})/")


def extract_goods_list_from_html(html: str) -> list[dict]:
    """SSR配信されたHTMLから `const goodsList = "..."` の中身を取り出してパース。

    女性全体ランキング (`/jp/trending/items`) はHTMLに商品データが埋め込まれている。
    """
    m = re.search(r'const\s+goodsList\s*=\s*"', html)
    if not m:
        raise ValueError("goodsList not found in HTML (page structure may have changed)")
    start = m.end()
    i = start
    end = -1
    while i < len(html):
        c = html[i]
        if c == "\\":
            i += 2
            continue
        if c == '"':
            end = i
            break
        i += 1
    if end < 0:
        raise ValueError("Could not find closing quote of goodsList literal")
    raw = html[start:end]
    # JS文字列リテラルのアンエスケープ (\uXXXX は json.loads が処理)
    unescaped = raw.replace("\\/", "/").replace('\\"', '"').replace("\\\\", "\\")
    data = json.loads(unescaped)
    return data.get("goodsInfoList", []) or []


def find_goods_in_obj(obj: Any) -> list[dict] | None:
    """任意のJSONオブジェクトから再帰的に goodsInfoList を探す。

    ブランドページのAPIレスポンス(Playwrightで取得)はネスト構造の可能性があるため。
    """
    if isinstance(obj, dict):
        if "goodsInfoList" in obj and isinstance(obj["goodsInfoList"], list):
            return obj["goodsInfoList"]
        for v in obj.values():
            r = find_goods_in_obj(v)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for item in obj:
            r = find_goods_in_obj(item)
            if r is not None:
                return r
    return None


def _extract_listing_date(image_url: str) -> str | None:
    if not image_url:
        return None
    m = _LISTING_DATE_RE.search(image_url)
    if not m:
        return None
    s = m.group(1)
    try:
        # YYYY-MM-DD として妥当か検証(ISO形式の date を一度生成)
        return date(int(s[:4]), int(s[4:6]), int(s[6:8])).isoformat()
    except ValueError:
        return None


def _normalize_image_url(image_url: str | None) -> str | None:
    if not image_url:
        return None
    if image_url.startswith("//"):
        return f"https:{image_url}"
    if image_url.startswith("/"):
        return f"https://image.msscdn.net{image_url}"
    return image_url


def normalize_goods(
    raw: dict,
    *,
    rank: int,
    ranking_type: str,
    brand_name: str,
    brand_id: str | None,
    date_key: str,
    scraped_at_iso: str,
) -> dict:
    """商品オブジェクトをBigQuery/Sheets用の共通スキーマに変換する。"""
    image_url = _normalize_image_url(raw.get("imageUrl") or raw.get("image"))
    landing = raw.get("landingUrl") or ""
    product_url = f"https://global.musinsa.com{landing}" if landing.startswith("/") else landing

    return {
        "date_key": date_key,
        "ranking_type": ranking_type,
        "brand_name": brand_name,
        "brand_id": brand_id,
        "rank": rank,
        "product_id": str(raw.get("goodsNo") or ""),
        "product_name": raw.get("goodsName"),
        "category": None,  # 商品オブジェクトに直接フィールドなし
        "image_url": image_url,
        "price": _to_int(raw.get("price")),
        "normal_price": _to_int(raw.get("normalPrice")),
        "sale_rate": _to_int(raw.get("saleRate")),
        "favorite_count": _to_int(raw.get("likeCount")),
        "listing_date": _extract_listing_date(image_url or ""),
        "product_url": product_url or None,
        "product_brand_name": raw.get("brandName"),
        "product_brand_id": raw.get("brandId"),
        "scraped_at": scraped_at_iso,
    }


def _to_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
