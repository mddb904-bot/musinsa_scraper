"""ブランドランキング: BigQuery から「シートに未反映の日付」だけを Sheets に追記する。

グリッド上限エラー(修正済み)で Sheets に入らなかった日を、重複なく埋めるための
一回限りのバックフィル。BigQuery には**書き込まない**(参照のみ)ので重複しない。

手順:
  1. スプレッドシート「ブランドランキング」タブの最終取得日(date_key)を調べる。
  2. BigQuery の brand_ranking から、その日付より新しい行だけを取得。
  3. Sheets にだけ追記する(既存の load_brand_rows_to_sheets を使用)。

実行:
  python -m src.backfill_brand_sheets --dry-run   # 何件・どの日付を入れるか表示のみ
  python -m src.backfill_brand_sheets             # 実際に Sheets へ追記
"""
from __future__ import annotations

import logging
import os
import sys
from collections import Counter

from google.cloud import bigquery

from .bigquery_loader import _derive_brand_table
from .sheets_loader import (
    _BRAND_TAB_NAME,
    _get_gspread_client,
    load_brand_rows_to_sheets,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("musinsa.backfill")


def _sheet_max_date_key() -> str | None:
    """「ブランドランキング」タブの B列(取得日)の最大値を返す。無ければ None。"""
    spreadsheet_id = os.environ.get("GSHEETS_SPREADSHEET_ID")
    if not spreadsheet_id:
        raise RuntimeError("GSHEETS_SPREADSHEET_ID not set")
    gc = _get_gspread_client()
    sh = gc.open_by_key(spreadsheet_id)
    try:
        ws = sh.worksheet(_BRAND_TAB_NAME)
    except Exception:
        logger.info("Sheet tab '%s' not found; will backfill everything", _BRAND_TAB_NAME)
        return None
    col_b = ws.col_values(2)  # B列 = 取得日(date_key)。1行目はヘッダー。
    dates = [c.strip() for c in col_b[1:] if c.strip() and c.strip()[0].isdigit()]
    return max(dates) if dates else None


def _fetch_rows_after(date_key: str | None) -> list[dict]:
    table = _derive_brand_table()
    client = bigquery.Client()
    cols = "date_key, rank, brand_id, brand_name, brand_url, is_musinsa_exclusive, scraped_at"
    if date_key:
        sql = (
            f"SELECT {cols} FROM `{table}` "
            "WHERE date_key > DATE(@d) ORDER BY date_key, rank"
        )
        cfg = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("d", "DATE", date_key)]
        )
        job = client.query(sql, job_config=cfg)
    else:
        job = client.query(f"SELECT {cols} FROM `{table}` ORDER BY date_key, rank")

    rows: list[dict] = []
    for r in job:
        rows.append({
            "date_key": r["date_key"].isoformat() if r["date_key"] else None,
            "rank": r["rank"],
            "brand_id": r["brand_id"],
            "brand_name": r["brand_name"],
            "brand_url": r["brand_url"],
            "is_musinsa_exclusive": r["is_musinsa_exclusive"],
            "scraped_at": (
                r["scraped_at"].strftime("%Y-%m-%d %H:%M:%S") if r["scraped_at"] else None
            ),
        })
    return rows


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    max_date = _sheet_max_date_key()
    logger.info("Sheet '%s' last date_key: %s", _BRAND_TAB_NAME, max_date or "(empty)")

    rows = _fetch_rows_after(max_date)
    by_date = Counter(r["date_key"] for r in rows)
    logger.info("BigQuery rows to backfill (date_key > %s): %d", max_date, len(rows))
    logger.info("Breakdown by date: %s", dict(sorted(by_date.items())))

    if not rows:
        logger.info("Nothing to backfill. Sheet is already up to date.")
        return

    if dry_run:
        logger.info("--dry-run: no writes. Sample row: %s", rows[0])
        return

    load_brand_rows_to_sheets(rows)  # Sheets のみ。BigQuery には書き込まない。
    logger.info("Backfill complete: appended %d rows to '%s'", len(rows), _BRAND_TAB_NAME)


if __name__ == "__main__":
    main()
