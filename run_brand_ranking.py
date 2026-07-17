"""エントリポイント: ブランドランキング(ブランド単位・日次)を取得して
BigQueryとスプレッドシートに書き込む。

商品ランキング (src.main) とは独立。専用テーブル brand_ranking と
専用シート「ブランドランキング」に書き込む。

実行例:
    python -m src.run_brand_ranking                 # 通常(独占判定あり)
    python -m src.run_brand_ranking --dry-run       # 取得のみ・書き込みなし
    python -m src.run_brand_ranking --skip-exclusive # 独占判定を省略(高速)
    python -m src.run_brand_ranking --top-n 50      # 上位50件だけ
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

from .parser import normalize_brand
from .scrapers.brand_ranking import fetch_brand_ranking_list
from .bigquery_loader import load_brand_rows_to_bigquery
from .sheets_loader import load_brand_rows_to_sheets
from .notifier import notify_failure, notify_success


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("musinsa.brand")

JST = timezone(timedelta(hours=9))


def _load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _today_jst_iso() -> str:
    return datetime.now(JST).date().isoformat()


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def run(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    cfg: dict = {}
    if config_path.exists():
        cfg = _load_config(config_path) or {}
    br_cfg = cfg.get("brand_ranking", {}) or {}

    top_n = args.top_n if args.top_n is not None else int(br_cfg.get("top_n", 100))
    interval = float(br_cfg.get("request_interval_seconds", 1.0))
    detect_exclusive = bool(br_cfg.get("detect_exclusive", True)) and not args.skip_exclusive

    date_key = _today_jst_iso()
    scraped_at = _now_utc_iso()

    try:
        items = fetch_brand_ranking_list(
            top_n=top_n,
            detect_exclusive=detect_exclusive,
            request_interval_seconds=interval,
        )
    except Exception as e:
        logger.exception("Failed to fetch brand ranking")
        notify_failure(str(e), context="brand ranking")
        return 2

    rows = [normalize_brand(b, date_key=date_key, scraped_at_iso=scraped_at) for b in items]
    logger.info("Brand ranking rows collected: %d", len(rows))

    if args.dump_sample and rows:
        logger.info("=== brand[0]: %s", json.dumps(rows[0], ensure_ascii=False))

    if args.dry_run:
        logger.info("--dry-run: skipping writes. Sample: %s", rows[0] if rows else None)
        return 0

    if not rows:
        logger.warning("No brand rows collected; nothing to write")
        notify_failure("brandList が取得できませんでした", context="brand ranking")
        return 3

    if not args.no_bq:
        try:
            load_brand_rows_to_bigquery(rows)
        except Exception as e:
            logger.exception("BigQuery brand load failed")
            notify_failure(str(e), context="brand ranking BigQuery load")
            return 4

    if not args.no_sheets:
        try:
            load_brand_rows_to_sheets(rows)
        except Exception as e:
            logger.exception("Sheets brand load failed")
            notify_failure(str(e), context="brand ranking Sheets load")
            return 5

    if args.notify_on_success:
        excl = sum(1 for r in rows if r.get("is_musinsa_exclusive"))
        notify_success({"brand_ranking": len(rows), "うち独占": excl})

    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="MUSINSAブランドランキング取得(日次)")
    p.add_argument("--config", default="config/targets.yaml")
    p.add_argument("--top-n", type=int, default=None, help="上位N件(未指定はconfig値)")
    p.add_argument("--skip-exclusive", action="store_true", help="MUSINSA独占判定を省略(高速)")
    p.add_argument("--dry-run", action="store_true", help="取得のみ。BQ/Sheetsに書き込まない")
    p.add_argument("--no-bq", action="store_true", help="BigQueryへの書き込みをスキップ")
    p.add_argument("--no-sheets", action="store_true", help="スプレッドシートへの書き込みをスキップ")
    p.add_argument("--dump-sample", action="store_true", help="先頭1件をログ出力")
    p.add_argument("--notify-on-success", action="store_true", help="成功時もSlack通知")
    args = p.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
