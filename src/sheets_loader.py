"""Googleスプレッドシートへの追記(日本語対応版)。

タブ名・見出し行を日本語で表示。A列はユーザー予約。
"""
from __future__ import annotations

import logging
import os
from typing import Iterable

import gspread

logger = logging.getLogger(__name__)


# --- 内部カラム名(BigQuery/データ処理用) ---
_COLUMNS = [
    "date_key", "ranking_type", "brand_name", "brand_id", "rank",
    "product_id", "product_name", "category", "image_url",
    "price", "normal_price", "sale_rate", "favorite_count",
    "listing_date", "product_url", "product_brand_name",
    "product_brand_id", "scraped_at",
]

# --- スプレッドシート表示用の日本語ヘッダー (_COLUMNS と順番・件数を一致させる) ---
_COLUMNS_JP = [
    "取得日",           # date_key
    "ランキング種類",    # ranking_type
    "ブランド名",        # brand_name
    "ブランドID",        # brand_id
    "順位",             # rank
    "商品ID",           # product_id
    "商品名",           # product_name
    "カテゴリ",          # category
    "商品画像URL",       # image_url
    "価格（セール後）",  # price
    "プロパー価格",      # normal_price
    "割引率(%)",         # sale_rate
    "お気に入り数",      # favorite_count
    "サムネ掲載日",      # listing_date
    "商品URL",          # product_url
    "商品ブランド名",    # product_brand_name
    "商品ブランドID",    # product_brand_id
    "取得日時",          # scraped_at
]

# --- ranking_type 値 → 日本語タブ名 ---
_TAB_NAME_MAP = {
    "overall":       "全体ランキング",
    "brand_weekly":  "ブランド別（週間）",
    "brand_monthly": "ブランド別（月間）",
}

_DATA_COL_START = 2  # B列スタート (A列はユーザー予約)


def _row_to_list(row: dict) -> list:
    return [row.get(c) if row.get(c) is not None else "" for c in _COLUMNS]


def _end_col_letter() -> str:
    return gspread.utils.rowcol_to_a1(
        1, _DATA_COL_START + len(_COLUMNS) - 1
    ).rstrip("0123456789")


def _find_last_data_row(ws: gspread.Worksheet) -> int:
    """B列以降にデータが入っている最後の行番号を返す(A列は無視)。"""
    all_values = ws.get_all_values()
    last = 0
    for i, row in enumerate(all_values):
        if len(row) > 1 and any(c.strip() for c in row[1:]):
            last = i + 1
    return last


def _smart_append(
    ws: gspread.Worksheet,
    rows_values: list[list],
) -> int:
    """日本語ヘッダーを保証し、B列から最終データ行の次に追記する。"""
    last_row = _find_last_data_row(ws)
    end_col = _end_col_letter()

    if last_row == 0:
        # 空シート: B1に日本語ヘッダーを書く
        logger.info("Sheet '%s' is empty, writing header at B1", ws.title)
        ws.update(f"B1:{end_col}1", [_COLUMNS_JP], value_input_option="RAW")
        start_row = 2
    else:
        # B1のヘッダーを確認し、日本語でなければ上書き
        row_1 = ws.row_values(1)
        current_header = row_1[1:1 + len(_COLUMNS_JP)] if len(row_1) > 1 else []
        if current_header != _COLUMNS_JP:
            logger.info("Sheet '%s': updating header to Japanese", ws.title)
            ws.update(f"B1:{end_col}1", [_COLUMNS_JP], value_input_option="RAW")
        start_row = max(last_row + 1, 2)

    if not rows_values:
        return 0

    end_row = start_row + len(rows_values) - 1
    range_str = f"B{start_row}:{end_col}{end_row}"
    ws.update(range_str, rows_values, value_input_option="RAW")
    logger.info(
        "Wrote %d rows to sheet '%s' (range: %s)",
        len(rows_values), ws.title, range_str,
    )
    return len(rows_values)


def _ensure_worksheet(
    sh: gspread.Spreadsheet,
    title: str,
    old_title: str | None = None,
) -> gspread.Worksheet:
    """日本語タブを取得または作成する。旧英語名タブがあれば自動リネーム。"""
    # 日本語タブを探す
    try:
        return sh.worksheet(title)
    except gspread.WorksheetNotFound:
        pass

    # 旧英語名タブがあればリネーム(データも引き継ぎ)
    if old_title:
        try:
            ws = sh.worksheet(old_title)
            ws.update_title(title)
            logger.info("Renamed worksheet '%s' → '%s'", old_title, title)
            return ws
        except gspread.WorksheetNotFound:
            pass

    # 新規作成
    logger.info("Creating new worksheet: '%s'", title)
    return sh.add_worksheet(title=title, rows=2000, cols=len(_COLUMNS) + 1)


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
    logger.info("Writing to spreadsheet: title='%s'", sh.title)

    by_type: dict[str, list[dict]] = {}
    for r in rows_list:
        by_type.setdefault(r.get("ranking_type", "unknown"), []).append(r)

    for rtype, group in by_type.items():
        tab_name = _TAB_NAME_MAP.get(rtype, rtype)
        ws = _ensure_worksheet(sh, tab_name, old_title=rtype)
        values = [_row_to_list(r) for r in group]
        _smart_append(ws, values)
