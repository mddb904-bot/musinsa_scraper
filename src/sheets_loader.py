"""Googleスプレッドシートへの追記(スマート追記版)。

最後にデータが入っている行を探して、その次から書き込む。
手動でデータを消した場合も、消された後に正しく続きを書く。
"""
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


def _find_last_data_row(ws: gspread.Worksheet) -> int:
    """データが入っている最後の行番号(1-indexed)を返す。空なら0。"""
    all_values = ws.get_all_values()
    last = 0
    for i, row in enumerate(all_values):
        if any(c.strip() for c in row):
            last = i + 1
    return last


def _smart_append(
    ws: gspread.Worksheet,
    header: list[str],
    rows_values: list[list],
) -> int:
    """ヘッダーを保証しつつ、最後のデータ行の次から書き込む。"""
    last_row = _find_last_data_row(ws)

    if last_row == 0:
        # シートが空: ヘッダーを書いてから データ書き込み
        logger.info("Sheet '%s' is empty, writing header at A1", ws.title)
        ws.update("A1", [header], value_input_option="RAW")
        start_row = 2
    else:
        # ヘッダー(1行目)を確認
        first_row = ws.row_values(1)
        if first_row != header:
            logger.warning(
                "Sheet '%s' header mismatch, overwriting row 1",
                ws.title,
            )
            ws.update("A1", [header], value_input_option="RAW")
        start_row = max(last_row + 1, 2)

    if not rows_values:
        return 0

    num_rows = len(rows_values)
    num_cols = len(header)
    end_row = start_row + num_rows - 1
    end_col_a1 = gspread.utils.rowcol_to_a1(1, num_cols).rstrip("0123456789")
    range_str = f"A{start_row}:{end_col_a1}{end_row}"

    ws.update(range_str, rows_values, value_input_option="RAW")
    logger.info(
        "Wrote %d rows to sheet '%s' (range: %s)",
        num_rows, ws.title, range_str,
    )
    return num_rows


def _ensure_worksheet(sh: gspread.Spreadsheet, title: str) -> gspread.Worksheet:
    try:
        return sh.worksheet(title)
    except gspread.WorksheetNotFound:
        logger.info("Creating new worksheet: '%s'", title)
        return sh.add_worksheet(title=title, rows=2000, cols=len(_COLUMNS))


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
        _smart_append(ws, _COLUMNS, values)
