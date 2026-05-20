# MUSINSA Ranking Scraper

MUSINSA(韓国ファッションEC)の女性ランキングをスクレイピングして BigQuery とGoogleスプレッドシートに蓄積するパイプライン。GitHub Actions で完全自動化。

## 取得対象

| 対象 | 種類 | 件数 |
|---|---|---|
| 女性全体ランキング | リアルタイム | 上位200位 |
| 9ブランド独自ランキング | weekly + monthly | 各上位200位 |

対象ブランド: MUCENT, ASYOUARE, COIRIS, CATSAVETHEWORLD, EYEER, SETUPEXE, HEISAN, PORTERNA, FANCYCLUB

## 取得項目

- 順位 (`rank`)
- 商品ID (`product_id`) / 商品名 (`product_name`)
- 商品画像URL (`image_url`)
- 価格 (`price`) / 定価 (`normal_price`) / セール率 (`sale_rate`)
- お気に入り数 (`favorite_count`)
- 掲載日 (`listing_date`, 画像URLパスから推定)
- 商品URL (`product_url`)
- 取得元ブランド情報

## アーキテクチャ

```
GitHub Actions (Cron)
   ↓
Python Scraper
   ├─ 女性全体  → requests + HTML埋め込みJSON抽出 (高速)
   └─ ブランド  → Playwright + ネットワーク傍受 (CSR対応)
   ↓
データ正規化
   ↓
   ├─→ BigQuery (履歴蓄積・SQL分析)
   └─→ Googleスプレッドシート (即時閲覧)
   ↓
失敗時 → Slack通知
```

---

## セットアップ

👉 **`SETUP_GUIDE.md` を見てください**(コマンドライン不要、画面操作だけで完了する手順書)

開発者向けの簡易手順:
1. このリポジトリをGitHubにpush
2. `sql/create_table.sql` のプロジェクトIDを置換して BigQuery で実行
3. GCPサービスアカウント作成 (`BigQuery Data Editor`, `BigQuery Job User` ロール) + キーDL
4. スプレッドシート作成 + サービスアカウントを編集者として共有 + Sheets API有効化
5. Slack Incoming Webhook作成
6. GitHub Secretsに `GCP_SERVICE_ACCOUNT_JSON` / `BQ_TABLE` / `GSHEETS_SPREADSHEET_ID` / `SLACK_WEBHOOK_URL` を登録
7. Actions タブから手動実行で動作確認

---

## ローカルで試す

```bash
# 依存インストール
pip install -r requirements.txt
python -m playwright install chromium

# 環境変数を設定
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/gcp-key.json
export BQ_TABLE=your-project.musinsa.ranking
export GSHEETS_SPREADSHEET_ID=xxxxxxxxxxxxxxxxxx
export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# まずは取得だけ試す (BQ/Sheetsに書き込まない)
python -m src.main --dry-run

# 全体ランキングだけ取得 (Playwright不要で軽量)
python -m src.main --skip-brand --dry-run

# 本番実行
python -m src.main
```

---

## 頻度・タイミングの変更

`.github/workflows/scrape.yml` の `schedule.cron` を編集します。

| 用途 | Cron式 |
|---|---|
| 週1 (月曜 03:00 JST) — 現状 | `'0 18 * * 0'` |
| 毎日 (03:00 JST) | `'0 18 * * *'` |
| 平日のみ (月〜金 03:00 JST) | `'0 18 * * 0-4'` |
| 朝 (08:00 JST) | `'0 23 * * *'` |

時刻は **UTC基準** なので、JSTにしたい時刻から **−9時間** で指定してください。

---

## 設定変更

`config/targets.yaml` で以下を変更できます:

- 取得上位件数 (`overall.top_n`, `brand_top_n`)
- 対象ブランドの追加・削除
- 取得期間 (`brand_periods`)
- リクエスト間隔 (`request_interval_seconds`)

---

## 出力スキーマ

`sql/create_table.sql` を参照。BigQueryもスプレッドシートも同じカラム構成です。

スプレッドシートは `ranking_type` ごとに別シートに振り分けられます:
- `overall`
- `brand_weekly`
- `brand_monthly`

---

## 注意事項

- MUSINSAの利用規約・robots.txtを必ず確認のうえ運用してください
- リクエスト間隔は `config/targets.yaml` の `request_interval_seconds` で調整できます (デフォルト2秒)
- ページ構造が変わった場合、`src/parser.py` および `src/scrapers/brand.py` の調整が必要になる可能性があります
