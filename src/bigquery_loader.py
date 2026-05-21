"""BigQueryへのデータロード(バッチロード版)。

ストリーミングバッファに溜まらないため、書き込み直後でも DELETE/UPDATE できる。
"""
from __future__ import annotations

import logging
import os

from google.cloud import bigquery

logger = logging.getLogger(__name__)


def load_rows_to_bigquery(rows: list[dict], table: str | None = None) -> None:
    """共通スキーマの行リストをBigQueryにバッチロードする。

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

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION],
    )

    logger.info("Loading %d rows into %s via batch load job", len(rows), table)
    job = client.load_table_from_json(rows, table, job_config=job_config)
    job.result()  # 完了まで待つ

    if job.errors:
        raise RuntimeError(f"BigQuery load errors: {job.errors}")

    logger.info("Loaded %d rows successfully", len(rows))
