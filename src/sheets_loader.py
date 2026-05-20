"""Googleスプレッドシートへのデータ追記。

ranking_type ごとに別シート(overall / brand_weekly / brand_monthly)に追記する。
"""
from __future__ import annotations

import logging
import os
from typing import Iterable

import gspread

logger = logging.getLogger(__name__)


# BigQueryのカラム順と一致させる
_COLUMNS = [
    "date_key",
    "ranking_type",
    "brand_name",
    "brand_id",
    "rank",
    "product_id",
    "product_name",
    "category",
    "image_url",
    "price",
    "normal_price",
    "sale_rate",
    "favorite_count",
    "listing_date",
    "product_url",
    "product_brand_name",
    "product_brand_id",
    "scraped_at",
]


def _row_to_list(row: dict) -> list:
    return [row.get(c) if row.get(c) is not None else "" for c in _COLUMNS]


def _ensure_worksheet(sh: gspread.Spreadsheet, title: str) -> gspread.Worksheet:
    try:
        ws = sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=1000, cols=len(_COLUMNS))
        ws.append_row(_COLUMNS, value_input_option="RAW")
        return ws
    # ヘッダー行が無ければ追加
    first_row = ws.row_values(1)
    if not first_row:
        ws.append_row(_COLUMNS, value_input_option="RAW")
    return ws


def load_rows_to_sheets(
    rows: Iterable[dict],
    spreadsheet_id: str | None = None,
) -> None:
    """共通スキーマの行リストをGoogleスプレッドシートに追記する。

    ranking_type ごとに別シートに振り分ける。
    """
    rows_list = list(rows)
    if not rows_list:
        logger.info("No rows to load to Sheets, skipping")
        return

    spreadsheet_id = spreadsheet_id or os.environ.get("GSHEETS_SPREADSHEET_ID")
    if not spreadsheet_id:
        raise RuntimeError("Spreadsheet ID not specified (set GSHEETS_SPREADSHEET_ID env var)")

    gc = gspread.service_account()  # GOOGLE_APPLICATION_CREDENTIALS を参照
    sh = gc.open_by_key(spreadsheet_id)

    # ranking_type ごとにグループ化
    by_type: dict[str, list[dict]] = {}
    for r in rows_list:
        by_type.setdefault(r.get("ranking_type", "unknown"), []).append(r)

    for rtype, group in by_type.items():
        ws = _ensure_worksheet(sh, rtype)
        values = [_row_to_list(r) for r in group]
        ws.append_rows(values, value_input_option="RAW")
        logger.info("Appended %d rows to sheet '%s'", len(values), rtype)
