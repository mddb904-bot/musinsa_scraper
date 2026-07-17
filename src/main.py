"""エントリポイント: 全ランキングを取得してBigQueryとスプレッドシートに書き込む。

実行例:
    # 全部 (デフォルト)
    python -m src.main

    # 一部のみテスト実行
    python -m src.main --skip-brand          # 全体だけ
    python -m src.main --skip-overall        # ブランドだけ
    python -m src.main --dry-run             # 取得だけして書き込みしない
    python -m src.main --no-bq --no-sheets   # ロード先を絞る
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml

from .parser import normalize_goods
from .scrapers.overall import fetch_overall_ranking
from .scrapers.brand import fetch_brand_ranking
from .bigquery_loader import load_rows_to_bigquery
from .sheets_loader import load_rows_to_sheets
from .notifier import notify_failure, notify_success


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("musinsa")

# 日本時間 (Asia/Tokyo)
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
    if not config_path.exists():
        logger.error("Config not found: %s", config_path)
        return 1
    cfg = _load_config(config_path)

    date_key = _today_jst_iso()
    scraped_at = _now_utc_iso()
    interval = float(cfg.get("request_interval_seconds", 2))

    all_rows: list[dict] = []
    summary: dict[str, int] = {}

    # --- 女性全体ランキング ---
    if not args.skip_overall:
        ov_cfg = cfg["overall"]
        try:
            items = fetch_overall_ranking(
                top_n=int(ov_cfg.get("top_n", 200)),
                gender=ov_cfg.get("gender", "F"),
                request_interval_seconds=interval,
            )
            if args.dump_sample and items:
                logger.info("=== RAW overall[0] keys: %s", list(items[0].keys()))
                logger.info(
                    "=== RAW overall[0] json: %s",
                    json.dumps(items[0], ensure_ascii=False)[:3000],
                )
            rows = [
                normalize_goods(
                    g,
                    rank=i + 1,
                    ranking_type="overall",
                    brand_name="All",
                    brand_id=None,
                    date_key=date_key,
                    scraped_at_iso=scraped_at,
                )
                for i, g in enumerate(items)
            ]
            all_rows.extend(rows)
            summary["overall"] = len(rows)
            logger.info("Overall ranking: %d rows", len(rows))
        except Exception as e:
            logger.exception("Failed to fetch overall ranking")
            notify_failure(str(e), context="overall ranking")
            if args.fail_fast:
                return 2

    # --- ブランド独自ランキング ---
    if not args.skip_brand:
        brands = cfg.get("brands", [])
        periods = cfg.get("brand_periods", ["weekly", "monthly"])
        brand_top_n = int(cfg.get("brand_top_n", 200))

        for brand in brands:
            slug = brand["slug"]
            name = brand["name"]
            for period in periods:
                rtype = f"brand_{period}"
                try:
                    items = fetch_brand_ranking(
                        brand_slug=slug, period=period, top_n=brand_top_n
                    )
                    rows = [
                        normalize_goods(
                            g,
                            rank=i + 1,
                            ranking_type=rtype,
                            brand_name=name,
                            brand_id=slug,
                            date_key=date_key,
                            scraped_at_iso=scraped_at,
                        )
                        for i, g in enumerate(items)
                    ]
                    all_rows.extend(rows)
                    summary[f"{name}_{period}"] = len(rows)
                    logger.info("brand=%s period=%s: %d rows", name, period, len(rows))
                except Exception as e:
                    logger.exception("Failed to fetch brand=%s period=%s", slug, period)
                    notify_failure(str(e), context=f"brand {slug} {period}")
                    if args.fail_fast:
                        return 3
                time.sleep(interval)

    logger.info("Total rows collected: %d", len(all_rows))

    if args.dry_run:
        logger.info("--dry-run: skipping writes. Sample row: %s", all_rows[0] if all_rows else None)
        return 0

    # --- BigQuery ロード ---
    if not args.no_bq and all_rows:
        try:
            load_rows_to_bigquery(all_rows)
        except Exception as e:
            logger.exception("BigQuery load failed")
            notify_failure(str(e), context="BigQuery load")
            if args.fail_fast:
                return 4

    # --- スプレッドシート ロード ---
    if not args.no_sheets and all_rows:
        try:
            load_rows_to_sheets(all_rows)
        except Exception as e:
            logger.exception("Sheets load failed")
            notify_failure(str(e), context="Sheets load")
            if args.fail_fast:
                return 5

    # --- 成功通知(任意) ---
    if args.notify_on_success:
        notify_success(summary)

    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="MUSINSAランキング取得")
    p.add_argument("--config", default="config/targets.yaml")
    p.add_argument("--skip-overall", action="store_true", help="全体ランキングをスキップ")
    p.add_argument("--skip-brand", action="store_true", help="ブランドランキングをスキップ")
    p.add_argument("--dry-run", action="store_true", help="取得のみ。BQ/Sheetsに書き込まない")
    p.add_argument("--no-bq", action="store_true", help="BigQueryへの書き込みをスキップ")
    p.add_argument("--no-sheets", action="store_true", help="スプレッドシートへの書き込みをスキップ")
    p.add_argument("--notify-on-success", action="store_true", help="成功時もSlack通知")
    p.add_argument("--fail-fast", action="store_true", help="最初のエラーで即終了")
    p.add_argument(
        "--dump-sample",
        action="store_true",
        help="取得した生データの先頭1件をログ出力（カテゴリ有無などの確認用）",
    )
    args = p.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
