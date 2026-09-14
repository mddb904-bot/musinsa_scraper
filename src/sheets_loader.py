"""Googleスプレッドシートへの追記(日本語対応版)。

タブ名・見出し行を日本語で表示。A列はユーザー予約。
"""
from __future__ import annotations

import functools
import logging
import os
import random
import time
from typing import Iterable

import gspread
import requests

logger = logging.getLogger(__name__)


# ============================================================
# 一時的なAPIエラーのリトライ (Google側の 503/500/429 等を吸収)
# ============================================================

# リトライ対象とするHTTPステータス(サーバー側の一時的な不調・混雑)
_TRANSIENT_STATUS = {429, 500, 502, 503, 504}
# 総試行回数(初回 + リトライ)。既定5回 = 最大4回リトライ。
_MAX_ATTEMPTS = int(os.environ.get("SHEETS_MAX_RETRIES", "5"))
# バックオフの基準秒数。2 → 2, 4, 8, 16秒 と指数的に待つ。
_BASE_DELAY = float(os.environ.get("SHEETS_RETRY_BASE_DELAY", "2"))


def _is_transient(exc: Exception) -> bool:
    """一時的(=再試行で回復し得る)エラーかどうかを判定する。"""
    if isinstance(exc, gspread.exceptions.APIError):
        try:
            return exc.response.status_code in _TRANSIENT_STATUS
        except Exception:  # noqa: BLE001 - response が無い等は非一時扱い
            return False
    # ネットワークの瞬断・タイムアウトも一時的として扱う
    return isinstance(
        exc,
        (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ),
    )


def _retry_transient(func):
    """gspreadのHTTP呼び出しを一時エラー時に指数バックオフで再試行する。"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        attempt = 0
        while True:
            try:
                return func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                attempt += 1
                if attempt >= _MAX_ATTEMPTS or not _is_transient(exc):
                    raise
                delay = _BASE_DELAY * (2 ** (attempt - 1))
                delay += random.uniform(0, delay * 0.1)  # ジッターで同時再試行を分散
                logger.warning(
                    "Sheets API transient error (%s); retrying %d/%d in %.1fs",
                    type(exc).__name__, attempt, _MAX_ATTEMPTS - 1, delay,
                )
                time.sleep(delay)

    return wrapper


def _install_retry(gc: gspread.Client) -> gspread.Client:
    """gspreadクライアントの全API呼び出しに一時エラー再試行を仕込む。

    HTTPクライアント層(全ての読み書きが通る単一経路)をラップするため、
    open/worksheet/update/resize 等どのAPI呼び出しでもリトライが効く。
    """
    http_client = getattr(gc, "http_client", None)
    request = getattr(http_client, "request", None)
    if request is not None and not getattr(request, "_retry_wrapped", False):
        wrapped = _retry_transient(request)
        wrapped._retry_wrapped = True  # 二重ラップ防止
        http_client.request = wrapped
    else:
        logger.debug("gspread retry not installed (unexpected client shape)")
    return gc


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


def _end_col_letter(n_cols: int) -> str:
    return gspread.utils.rowcol_to_a1(
        1, _DATA_COL_START + n_cols - 1
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
    columns_jp: list[str] | None = None,
) -> int:
    """日本語ヘッダーを保証し、B列から最終データ行の次に追記する。"""
    columns_jp = columns_jp if columns_jp is not None else _COLUMNS_JP
    last_row = _find_last_data_row(ws)
    end_col = _end_col_letter(len(columns_jp))

    if last_row == 0:
        # 空シート: B1に日本語ヘッダーを書く
        logger.info("Sheet '%s' is empty, writing header at B1", ws.title)
        ws.update(f"B1:{end_col}1", [columns_jp], value_input_option="RAW")
        start_row = 2
    else:
        # B1のヘッダーを確認し、日本語でなければ上書き
        row_1 = ws.row_values(1)
        current_header = row_1[1:1 + len(columns_jp)] if len(row_1) > 1 else []
        if current_header != columns_jp:
            logger.info("Sheet '%s': updating header to Japanese", ws.title)
            ws.update(f"B1:{end_col}1", [columns_jp], value_input_option="RAW")
        start_row = max(last_row + 1, 2)

    if not rows_values:
        return 0

    end_row = start_row + len(rows_values) - 1

    # グリッド上限対策: 追記先がシートの行数/列数を超える場合は先に拡張する
    needed_cols = _DATA_COL_START + len(columns_jp) - 1
    if end_row > ws.row_count or needed_cols > ws.col_count:
        new_rows = max(end_row + 200, ws.row_count)  # 余裕を持たせて毎回の拡張を避ける
        new_cols = max(needed_cols, ws.col_count)
        logger.info(
            "Sheet '%s': resizing grid to rows=%d, cols=%d (was rows=%d, cols=%d)",
            ws.title, new_rows, new_cols, ws.row_count, ws.col_count,
        )
        ws.resize(rows=new_rows, cols=new_cols)

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
        return _install_retry(gspread.service_account(filename=creds_path))
    logger.info("Authenticating gspread with default location")
    return _install_retry(gspread.service_account())


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


# ============================================================
# ブランドランキング(ブランド単位・日次) 用
# ============================================================

_BRAND_COLUMNS = [
    "date_key", "rank", "brand_id", "brand_name",
    "brand_url", "is_musinsa_exclusive", "scraped_at",
]

_BRAND_COLUMNS_JP = [
    "取得日",          # date_key
    "順位",            # rank
    "ブランドID",       # brand_id
    "ブランド名",       # brand_name
    "ブランドURL",      # brand_url
    "MUSINSA独占",     # is_musinsa_exclusive
    "取得日時",         # scraped_at
]

_BRAND_TAB_NAME = "ブランドランキング"


def _brand_row_to_list(row: dict) -> list:
    out: list = []
    for c in _BRAND_COLUMNS:
        v = row.get(c)
        if c == "is_musinsa_exclusive":
            # True→「独占」 / False(非独占)・None(判定不能)→空欄
            out.append("独占" if v else "")
        else:
            out.append("" if v is None else v)
    return out


def load_brand_rows_to_sheets(
    rows: Iterable[dict],
    spreadsheet_id: str | None = None,
) -> None:
    """ブランドランキングを専用タブ(ブランドランキング)に追記する。"""
    rows_list = list(rows)
    if not rows_list:
        logger.info("No brand rows to load to Sheets, skipping")
        return

    spreadsheet_id = spreadsheet_id or os.environ.get("GSHEETS_SPREADSHEET_ID")
    if not spreadsheet_id:
        raise RuntimeError("Spreadsheet ID not specified")

    gc = _get_gspread_client()
    sh = gc.open_by_key(spreadsheet_id)
    logger.info("Writing brand ranking to spreadsheet: title='%s'", sh.title)

    ws = _ensure_worksheet(sh, _BRAND_TAB_NAME)
    values = [_brand_row_to_list(r) for r in rows_list]
    _smart_append(ws, values, columns_jp=_BRAND_COLUMNS_JP)
