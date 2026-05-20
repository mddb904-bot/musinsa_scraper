"""BigQueryへのデータロード。"""
from __future__ import annotations

import logging
import os

from google.cloud import bigquery

logger = logging.getLogger(__name__)


def load_rows_to_bigquery(rows: list[dict], table: str | None = None) -> None:
    """共通スキーマの行リストをBigQueryに挿入する。

    Args:
        rows: parser.normalize_goods() で正規化済みの行リスト
        table: 'project.dataset.table' 形式。省略時は環境変数 BQ_TABLE を使用。
    """
    if not rows:
        logger.info("No rows to load to BigQuery, skipping")
        return

    table = table or os.environ.get("BQ_TABLE")
    if not table:
        raise RuntimeError("BigQuery table not specified (set BQ_TABLE env var)")

    client = bigquery.Client()
    table_ref = client.get_table(table)

    errors = client.insert_rows_json(table_ref, rows)
    if errors:
        raise RuntimeError(f"BigQuery insert errors: {errors}")

    logger.info("Inserted %d rows into %s", len(rows), table)
