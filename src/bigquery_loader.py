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


def _derive_brand_table(table: str | None = None) -> str:
    """ブランドランキング用テーブル名を決定する。

    優先順: 引数 > 環境変数 BQ_BRAND_TABLE > BQ_TABLE のテーブル名を
    'brand_ranking' に差し替えたもの (project.dataset は流用)。
    """
    table = table or os.environ.get("BQ_BRAND_TABLE")
    if table:
        return table
    base = os.environ.get("BQ_TABLE")
    if not base:
        raise RuntimeError(
            "Brand table not specified (set BQ_BRAND_TABLE or BQ_TABLE env var)"
        )
    parts = base.split(".")
    parts[-1] = "brand_ranking"
    return ".".join(parts)


def load_brand_rows_to_bigquery(rows: list[dict], table: str | None = None) -> None:
    """ブランドランキングの行リストをBigQueryにバッチロードする。"""
    if not rows:
        logger.info("No brand rows to load to BigQuery, skipping")
        return

    table = _derive_brand_table(table)
    client = bigquery.Client()

    # is_musinsa_exclusive は「独占(True) or NULL」で保持する。
    # 非独占(False)・判定不能(None) はいずれも NULL にする(列型は BOOL のまま)。
    load_rows = [
        {**r, "is_musinsa_exclusive": (True if r.get("is_musinsa_exclusive") else None)}
        for r in rows
    ]

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION],
    )

    logger.info("Loading %d brand rows into %s via batch load job", len(rows), table)
    job = client.load_table_from_json(load_rows, table, job_config=job_config)
    job.result()

    if job.errors:
        raise RuntimeError(f"BigQuery brand load errors: {job.errors}")

    logger.info("Loaded %d brand rows successfully", len(rows))
