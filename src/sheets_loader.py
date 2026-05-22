"""Googleスプレッドシートへのデータ追記(カラム整合性チェック付き)。"""
from __future__ import annotations

import logging
import os
from typing import Iterable

import gspread

logger = logging.getLogger(__name__)


_COLUMNS = [
    "date_key", "ranking_type", "brand_name", "brand_id", "rank",
    "product_id", "product_name", "category", "image_url",
    "price", "normal_price", "sale_rate", "favorite_count",
    "listing_date", "product_url", "product_brand_name",
    "product_brand_id", "scraped_at",
]


def _row_to_list(row: dict) -> list:
    return [row.get(c) if row.get(c) is not None else "" for c in _COLUMNS]


def _ensure_worksheet(sh: gspread.Spreadsheet, title: str) -> gspread.Worksheet:
    """ワークシートを取得し、ヘッダー行が正しいことを保証する。"""
    try:
        ws = sh.worksheet(title)
        logger.info("Found existing worksheet: '%s'", title)
    except gspread.WorksheetNotFound:
        logger.info("Creating new worksheet: '%s'", title)
        ws = sh.add_worksheet(title=title, rows=1000, cols=len(_COLUMNS))
        ws.update("A1", [_COLUMNS], value_input_option="RAW")
        return ws

    # 既存タブのヘッダー行を確認
    first_row = ws.row_values(1)
    if first_row != _COLUMNS:
        logger.warning(
            "Worksheet '%s' header mismatch. Existing=%s, Expected=%s. Overwriting header.",
            title, first_row[:3] + ['...'] if first_row else [],
            _COLUMNS[:3] + ['...'],
        )
        # ヘッダー行(1行目)を強制的にカラム名で上書き
        ws.update("A1", [_COLUMNS], value_input_option="RAW")
    return ws


def _get_gspread_client() -> gspread.Client:
    creds_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if creds_path and os.path.exists(creds_path):
        logger.info("Authenticating gspread with key file: %s", creds_path)
        return gspread.service_account(filename=creds_path)
    logger.info("Authenticating gspread with default location")
    return gspread.service_account()


def load_rows_to_sheets(
    rows: Iterable[dict],
    spreadsheet_id: str | None = None,
) -> None:
    rows_list = list(rows)
    if not rows_list:
        logger.info("No rows to load to Sheets, skipping")
        return

    spreadsheet_id = spreadsheet_id or os.environ.get("GSHEETS_SPREADSHEET_ID")
    if not spreadsheet_id:
        raise RuntimeError("Spreadsheet ID not specified")

    gc = _get_gspread_client()
    sh = gc.open_by_key(spreadsheet_id)

    logger.info(
        "Writing to spreadsheet: title='%s' url='%s'",
        sh.title, sh.url,
    )

    by_type: dict[str, list[dict]] = {}
    for r in rows_list:
        by_type.setdefault(r.get("ranking_type", "unknown"), []).append(r)

    for rtype, group in by_type.items():
        ws = _ensure_worksheet(sh, rtype)
        values = [_row_to_list(r) for r in group]
        ws.append_rows(values, value_input_option="RAW")
        logger.info("Appended %d rows to sheet '%s'", len(values), rtype)
