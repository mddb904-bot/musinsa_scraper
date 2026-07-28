# -*- coding: utf-8 -*-
"""AIニュースダイジェスト 共通設定."""

import os

# ---- Google Sheets ----------------------------------------------------------
SPREADSHEET_ID = "1qJD9GwKxOw9zW9fubWyAeZQBw0iSdL88a4RCXhwQppo"
TAB_ARTICLES = "articles"
TAB_SOURCES = "sources"

# 認証は2通り。GitHub Actions では SA_JSON（鍵の中身そのもの）を使う。
# ローカル実行では SA_KEY（鍵ファイルのパス）を使う。両方あれば SA_JSON を優先。
SERVICE_ACCOUNT_JSON = os.environ.get("AINEWS_SA_JSON", "")
SERVICE_ACCOUNT_FILE = os.environ.get(
    "AINEWS_SA_KEY",
    os.path.expanduser("~/ZOZO_data_download/service_account.json"),
)

# ---- Claude API -------------------------------------------------------------
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = os.environ.get("AINEWS_MODEL", "claude-sonnet-5")
# 要約プロンプトを変えたらここを上げる。過去分と混ざらないようにするための版番号。
PROMPT_VERSION = "v1"

# ---- 収集条件 ---------------------------------------------------------------
LOOKBACK_DAYS = 7          # ダイジェストに載せる対象期間
MAX_ITEMS_PER_FEED = 30    # 1フィードあたりの取得上限
DIGEST_MAX_ITEMS = 8       # ダイジェストに載せる最大件数
REQUEST_TIMEOUT = 20
USER_AGENT = "ai-news-digest/1.0 (internal research tool)"

# ---- 出力 -------------------------------------------------------------------
# GitHub Actions では dist/ に出してアーティファクトに上げる。
_default_out = "dist" if os.environ.get("GITHUB_ACTIONS") else os.path.expanduser(
    "~/ai_news_digest_out")
OUTPUT_DIR = os.environ.get("AINEWS_OUTPUT_DIR", _default_out)

# ---- articles タブの列定義 --------------------------------------------------
# 並び順がそのままシートの列順になる。列を足すときは必ず末尾に足すこと。
# 途中に挿入すると、既存行との対応がずれる。
ARTICLE_COLUMNS = [
    "article_id",           # url の SHA256 先頭16桁
    "collected_at",
    "source_name",
    "source_type",          # official / media / blog
    "url",
    "origin_url",           # まとめ記事から辿った一次発表
    "title",
    "published_date",
    "excerpt",
    "title_ja",
    "summary_ja",
    "category",             # global / japan / tool / ec
    "importance",           # A / B / C
    "relevance_score",      # 0-100
    "implication",
    "theme_id",
    "is_delivered",
    "model_version",
    "verification_status",
    "verified_at",
    "source_count",
    "evidence_excerpt",
    "conflict_note",
]

SOURCE_COLUMNS = [
    "feed_name",
    "feed_url",
    "source_type",
    "category_hint",
    "is_active",
    "note",
]

# ---- 検証ステータス ---------------------------------------------------------
ST_VERIFIED_PRIMARY = "verified_primary"    # 一次発表に到達し数値も一致
ST_CROSS_CONFIRMED = "cross_confirmed"      # 一次発表なし。複数報道が一致
ST_SINGLE_REPORT = "single_report"          # 1社のみ。裏付けなし
ST_CONFLICT = "conflict"                    # ソース間で数値が食い違う
ST_SUMMARY_MISMATCH = "summary_mismatch"    # 要約の数値が本文にない

# ダイジェストに載せてよいステータス。
# single_report は載せるが「未確認」ラベルを付ける。
DELIVERABLE_STATUSES = {
    ST_VERIFIED_PRIMARY,
    ST_CROSS_CONFIRMED,
    ST_SINGLE_REPORT,
}

# ---- 一次発表とみなすドメイン ------------------------------------------------
# ここに載っているドメインに着地したら official 扱いにする。
OFFICIAL_DOMAIN_PATTERNS = [
    "prtimes.jp",
    "corp.zozo.com",
    "aws.amazon.com",
    "cloud.google.com",
    "blog.google",
    "openai.com",
    "anthropic.com",
    "about.fb.com",
    "news.microsoft.com",
    "nvidia.com",
    "meti.go.jp",
    "nedo.go.jp",
    "soumu.go.jp",
    "mufg.jp",
    "digitalpr.jp",
    "news.panasonic.com",
    "group.softbank",
    "sony.com",
    "jpx.co.jp",
]

# まとめ・二次情報として扱うドメイン。ここ経由なら一次発表を辿りにいく。
AGGREGATOR_DOMAIN_PATTERNS = [
    "note.com",
    "buttondown.com",
    "hatenablog.com",
    "qiita.com",
    "zenn.dev",
    "news.yahoo.co.jp",
    "news.livedoor.com",
    "finance.biggo.jp",
]
