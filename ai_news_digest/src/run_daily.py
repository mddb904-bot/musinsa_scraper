# -*- coding: utf-8 -*-
"""日次実行のエントリポイント。

  収集 → 要約・分類 → 裏付け検証 → HTML生成 → 掲載フラグ更新

途中で失敗しても、シートに書き込んだところまでは残る。
翌日の実行が続きから拾い直す。
"""

import argparse
import sys
from datetime import datetime, timedelta, timezone

from . import config
from . import collect as collect_mod
from . import enrich as enrich_mod
from . import render as render_mod
from . import sheets_client as sc
from . import verify as verify_mod

JST = timezone(timedelta(hours=9))


def needs_enrichment(row):
    return not (row.get("title_ja") or "").strip()


def needs_verification(row):
    return not (row.get("verification_status") or "").strip()


def in_window(row, cutoff):
    published = (row.get("published_date") or "").strip()
    if not published:
        return True  # 日付不明は落とさず残す
    return published >= cutoff


def main(argv=None):
    parser = argparse.ArgumentParser(description="AIニュース日次ダイジェスト")
    parser.add_argument("--skip-collect", action="store_true",
                        help="収集をスキップして既存行だけ処理する")
    parser.add_argument("--dry-run", action="store_true",
                        help="シートに書き込まずHTMLだけ作る")
    args = parser.parse_args(argv)

    print("=== AIニュースダイジェスト %s ===" %
          datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S"))

    if not args.skip_collect:
        added = collect_mod.collect()
        print("収集: %d件を追加" % added)
    else:
        print("収集: スキップ")

    _, rows = sc.read_all(config.TAB_ARTICLES)
    print("シート内: %d行" % len(rows))

    cutoff = (datetime.now(JST) - timedelta(days=config.LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    window = [r for r in rows if in_window(r, cutoff)]
    print("対象期間内: %d行" % len(window))

    # --- 要約・分類 ---
    targets = [r for r in window if needs_enrichment(r)]
    if targets:
        print("要約対象: %d件" % len(targets))
        updates = enrich_mod.enrich_rows(targets)
        if not args.dry_run:
            sc.update_fields(config.TAB_ARTICLES, updates, config.ARTICLE_COLUMNS)
        print("要約完了: %d件" % len(updates))
    else:
        print("要約対象: なし")

    # --- 裏付け検証 ---
    targets = [r for r in window if needs_verification(r) and r.get("title_ja")]
    if targets:
        print("検証対象: %d件" % len(targets))
        updates = verify_mod.verify_rows(targets)
        if not args.dry_run:
            sc.update_fields(config.TAB_ARTICLES, updates, config.ARTICLE_COLUMNS)
        summary = {}
        for r in targets:
            key = r.get("verification_status", "")
            summary[key] = summary.get(key, 0) + 1
        for key in sorted(summary):
            print("  %s: %d件" % (key, summary[key]))
    else:
        print("検証対象: なし")

    # --- HTML生成 ---
    path, delivered_ids = render_mod.render(window, len(window))
    print("出力: %s" % path)
    print("掲載: %d件" % len(delivered_ids))

    # --- 掲載フラグ ---
    if delivered_ids and not args.dry_run:
        by_id = {r["article_id"]: r for r in window if r.get("article_id")}
        flag_updates = [
            (by_id[aid]["_row"], {"is_delivered": "TRUE"})
            for aid in delivered_ids if aid in by_id
        ]
        sc.update_fields(config.TAB_ARTICLES, flag_updates, config.ARTICLE_COLUMNS)

    return 0


if __name__ == "__main__":
    sys.exit(main())
