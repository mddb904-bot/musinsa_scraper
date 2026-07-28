# -*- coding: utf-8 -*-
"""初回セットアップ。

やること:
  - articles / sources タブをヘッダー付きで作る（既存があれば触らない）
  - sources に情報源の初期リストを入れる（空のときだけ）
  - 各フィードの疎通を確認する

既存のタブ・行は書き換えない。追加しかしない。
"""

import argparse
import sys

import feedparser

from . import config
from . import sheets_client as sc

# 初期の情報源リスト。
# feed_url は実在を確認しきれていないものが混ざるので、必ず --check を通すこと。
SEED_SOURCES = [
    ["ITmedia AI+", "https://rss.itmedia.co.jp/rss/2.0/aiplus.xml",
     "media", "global", "TRUE", ""],
    ["ITmedia NEWS", "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml",
     "media", "japan", "TRUE", ""],
    ["MONOist", "https://rss.itmedia.co.jp/rss/2.0/monoist.xml",
     "media", "japan", "TRUE", ""],
    ["Impress Watch", "https://www.watch.impress.co.jp/data/rss/1.0/ipw/feed.rdf",
     "media", "global", "TRUE", ""],
    ["PC Watch", "https://pc.watch.impress.co.jp/data/rss/1.0/pcw/feed.rdf",
     "media", "global", "TRUE", ""],
    ["ネットショップ担当者フォーラム", "https://netshop.impress.co.jp/rss/index.rdf",
     "media", "ec", "TRUE", "EC・アパレル向け"],
    ["AWS What's New", "https://aws.amazon.com/about-aws/whats-new/recent/feed/",
     "official", "tool", "TRUE", "一次発表"],
    ["ZOZO TECH BLOG", "https://techblog.zozo.com/rss",
     "official", "ec", "TRUE", "ZOZO本体の技術発信"],
    ["OpenAI Blog", "https://openai.com/blog/rss.xml",
     "official", "global", "TRUE", "一次発表"],
    ["PR TIMES 全体", "https://prtimes.jp/index.rdf",
     "official", "japan", "FALSE", "件数が多いので既定はオフ"],
]


def check_feed(url):
    """フィードが読めるかを確認する。(件数, エラー文) を返す。"""
    try:
        parsed = feedparser.parse(url)
    except Exception as exc:  # noqa: BLE001 - 疎通確認なので広く拾う
        return 0, str(exc)
    if getattr(parsed, "bozo", 0) and not parsed.entries:
        return 0, str(getattr(parsed, "bozo_exception", "解析に失敗"))
    return len(parsed.entries), ""


def run_check():
    print("--- フィード疎通確認 ---")
    ok = 0
    for row in SEED_SOURCES:
        name, url = row[0], row[1]
        count, err = check_feed(url)
        if count:
            print("  OK   %-28s %3d件" % (name, count))
            ok += 1
        else:
            print("  NG   %-28s %s" % (name, err or "0件"))
    print("疎通できたフィード: %d / %d" % (ok, len(SEED_SOURCES)))
    return ok


def run_setup(assume_yes=False):
    print("対象スプレッドシート: %s" % config.SPREADSHEET_ID)
    print("行うこと:")
    print("  - articles タブを作成（既存なら何もしない）")
    print("  - sources タブを作成（既存なら何もしない）")
    print("  - sources が空なら情報源の初期リストを追記")
    print("既存のタブ・行・セルは書き換えません。")

    if not assume_yes:
        answer = input("実行しますか? [y/N] ").strip().lower()
        if answer != "y":
            print("中止しました。")
            return 1

    ws, created = sc.get_or_create_tab(config.TAB_ARTICLES, config.ARTICLE_COLUMNS)
    print("articles タブ: %s" % ("作成しました" if created else "既存のものを使います"))

    ws, created = sc.get_or_create_tab(config.TAB_SOURCES, config.SOURCE_COLUMNS)
    print("sources タブ: %s" % ("作成しました" if created else "既存のものを使います"))

    _, rows = sc.read_all(config.TAB_SOURCES)
    if rows:
        print("sources には既に %d行あるので、初期リストは追加しません。" % len(rows))
    else:
        dicts = [dict(zip(config.SOURCE_COLUMNS, r)) for r in SEED_SOURCES]
        sc.append_dicts(config.TAB_SOURCES, dicts, config.SOURCE_COLUMNS)
        print("sources に %d件の情報源を追加しました。" % len(dicts))

    print("完了しました。")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="初回セットアップ")
    parser.add_argument("--check", action="store_true",
                        help="フィードの疎通確認だけを行う")
    parser.add_argument("--yes", action="store_true",
                        help="確認プロンプトを省略する")
    args = parser.parse_args(argv)

    if args.check:
        run_check()
        return 0
    return run_setup(assume_yes=args.yes)


if __name__ == "__main__":
    sys.exit(main())
