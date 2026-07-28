# -*- coding: utf-8 -*-
"""Google Sheets の読み書き。

既存タブを壊さない操作だけを用意している。
行の削除・タブの削除は意図的に実装していない。
"""

import json

import gspread
from google.oauth2.service_account import Credentials

from . import config

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

_client = None


def get_client():
    global _client
    if _client is None:
        if config.SERVICE_ACCOUNT_JSON.strip():
            info = json.loads(config.SERVICE_ACCOUNT_JSON)
            creds = Credentials.from_service_account_info(info, scopes=SCOPES)
        else:
            creds = Credentials.from_service_account_file(
                config.SERVICE_ACCOUNT_FILE, scopes=SCOPES
            )
        _client = gspread.authorize(creds)
    return _client


def get_spreadsheet():
    return get_client().open_by_key(config.SPREADSHEET_ID)


def col_letter(index_zero_based):
    """0始まりの列番号を A1 記法の列文字に変換する。"""
    n = index_zero_based + 1
    letters = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def get_or_create_tab(title, header):
    """タブが無ければヘッダー付きで作る。あれば既存をそのまま返す。

    既存タブのヘッダーは書き換えない。列が足りない場合は警告だけ返す。
    """
    sh = get_spreadsheet()
    try:
        ws = sh.worksheet(title)
        created = False
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=1000, cols=max(len(header), 26))
        ws.update(values=[header], range_name="A1")
        created = True
    return ws, created


def read_all(title):
    """タブ全体を辞書のリストで返す。各行に _row（1始まりのシート行番号）を付ける。"""
    sh = get_spreadsheet()
    ws = sh.worksheet(title)
    values = ws.get_all_values()
    if not values:
        return [], []
    header = values[0]
    rows = []
    for i, raw in enumerate(values[1:], start=2):
        raw = raw + [""] * (len(header) - len(raw))
        row = dict(zip(header, raw))
        row["_row"] = i
        rows.append(row)
    return header, rows


def append_dicts(title, dicts, columns):
    """末尾に追記する。既存行には触れない。"""
    if not dicts:
        return 0
    sh = get_spreadsheet()
    ws = sh.worksheet(title)
    rows = [[str(d.get(c, "")) for c in columns] for d in dicts]
    ws.append_rows(rows, value_input_option="RAW")
    return len(rows)


def update_fields(title, updates, columns):
    """既存行の一部セルだけを更新する。

    updates: [(row_number, {column_name: value}), ...]
    指定されなかったセルは触らない。
    """
    if not updates:
        return 0
    sh = get_spreadsheet()
    ws = sh.worksheet(title)
    index_of = {c: i for i, c in enumerate(columns)}
    payload = []
    for row_no, fields in updates:
        for col_name, value in fields.items():
            if col_name not in index_of:
                continue
            a1 = "%s%d" % (col_letter(index_of[col_name]), row_no)
            payload.append({"range": a1, "values": [[str(value)]]})
    if not payload:
        return 0
    ws.batch_update(payload, value_input_option="RAW")
    return len(payload)


def existing_article_ids(title):
    """重複判定用に article_id の集合を返す。"""
    header, rows = read_all(title)
    if not header:
        return set()
    return {r.get("article_id", "") for r in rows if r.get("article_id")}
