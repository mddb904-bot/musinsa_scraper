# AIニュース日次ダイジェスト

平日朝にAI関連ニュースを収集し、裏付けを取ったうえで日本語のダイジェストHTMLを作る。
収集した記事はすべてGoogleスプレッドシートに蓄積し、後から検索・分析できる状態にする。

```
収集 → 要約・分類（Claude API）→ 裏付け検証 → HTML生成 → 掲載フラグ更新
                                    ↓
                      すべての行はスプレッドシートに残る
```

GitHub Actions で動く。Macが起きている必要はない。

- 格納先シート: `AIニュース蓄積シート`
  `1qJD9GwKxOw9zW9fubWyAeZQBw0iSdL88a4RCXhwQppo`
- サービスアカウント: 既存の `zozo-auto-download@ada-bigquery.iam.gserviceaccount.com` を流用する想定

## セットアップ

ローカルにPython環境を作らなくても、ブラウザだけで一通り完了する。

### 1. リポジトリを作る

GitHub Desktop で新規リポジトリを作り、このフォルダの中身をコピーしてコミット・プッシュする。

**リポジトリは必ず Private にすること。** `implication` 列には社内向けの示唆が入るため、
公開リポジトリだと業務上の判断材料が外から見える状態になる。

### 2. シートをサービスアカウントに共有する（必須）

現時点でシートの権限はオーナーの `richimaru@crooz.co.jp` のみ。このままでは書き込めない。

シートの共有設定から `zozo-auto-download@ada-bigquery.iam.gserviceaccount.com` を
**編集者**として追加する。

### 3. Secrets を登録する

リポジトリの Settings → Secrets and variables → Actions → New repository secret。

| 名前 | 中身 |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API のキー |
| `AINEWS_SA_JSON` | サービスアカウント鍵JSONの**中身そのもの**を貼る（ファイルパスではない） |

`AINEWS_SA_JSON` は `service_account.json` をテキストエディタで開いて、
`{` から `}` まで全部をそのまま貼り付ける。改行が入っていて構わない。

### 4. フィードの疎通を確認する

Actions タブ → `setup` → Run workflow → `check-sources` を選んで実行。

初期の情報源リストは実在を確認しきれていないURLを含む。ここで `NG` が出たものは、
`src/setup_sheet.py` の `SEED_SOURCES` を直すか、後で `sources` タブで
`is_active` を `FALSE` にする。

### 5. タブを作る

Actions タブ → `setup` → Run workflow → `create-tabs` を選んで実行。

`articles` と `sources` の2タブをヘッダー付きで作り、`sources` が空なら初期リストを入れる。
既存のタブ・行・セルは書き換えない。

### 6. 手動で一度動かす

Actions タブ → `daily-digest` → Run workflow。

まず `dry_run` にチェックを入れて実行し、生成されたHTMLを確認するとよい。
シートには書き込まれない。問題なければチェックを外して本番実行する。

### 7. あとは自動

`0 22 * * 0-4`（UTC）= 平日 07:00 JST に動く。

GitHub のスケジュール実行は混雑時に数分から十数分遅れることがある。
分単位の正確さが要るものではないので、そのまま運用してよい。

## 生成物の見かた

実行後、Actions の該当 run のページ下部 `Artifacts` から `digest-<番号>` を
ダウンロードする。中の `latest.html` をブラウザで開く。保存期間は30日。

**スマホで手軽に見たい場合**、現状は少し手間がかかる。GitHub Pages に載せれば
URLで開けるが、無料枠では公開リポジトリが必要になり、`implication` の内容が
外から見えてしまう。当面はシート（`articles` タブ）をスマホのスプレッドシートアプリで
見るのが現実的。HTMLは腰を据えて読むとき用と割り切る。

## 実行オプション

`daily-digest` の Run workflow で2つ選べる。

| 入力 | 効果 |
|---|---|
| `dry_run` | シートに書き込まず HTML だけ作る |
| `skip_collect` | 収集をスキップして既存行だけ処理する |

要約プロンプトを直したあと過去分を作り直したいときは、`articles` の `title_ja` 列を
空にしてから `skip_collect` で回す。生の収集列（`excerpt` など）は残っているので、
何度でもやり直せる。あわせて `config.PROMPT_VERSION` を上げること。

## ローカルで動かす場合

```bash
pip3 install -r requirements.txt
export ANTHROPIC_API_KEY="..."
export AINEWS_SA_KEY="$HOME/ZOZO_data_download/service_account.json"
python3 -m src.run_daily --dry-run
```

launchd で回したい場合は `local/com.ada.ainews.digest.plist` を使う。
ただしMacが起きている必要があるので、Actions と併用しないこと。二重に走る。

## シートの構成

### `articles` タブ

| 列 | 内容 | 書かれるタイミング |
|---|---|---|
| `article_id` | URLのSHA256先頭16桁。重複判定のキー | 収集 |
| `collected_at` | 収集日時 | 収集 |
| `source_name` | 情報源名 | 収集 |
| `source_type` | official / media / blog | 収集 |
| `url` | 記事URL | 収集 |
| `origin_url` | まとめ記事から辿った一次発表 | 収集 |
| `title` | 元タイトル | 収集 |
| `published_date` | 発表日。一次発表があればそちらから取る | 収集 |
| `excerpt` | 本文冒頭800字。全文は保存しない | 収集 |
| `title_ja` | 整えた見出し | 加工 |
| `summary_ja` | 要約 | 加工 |
| `category` | global / japan / tool / ec | 加工 |
| `importance` | A / B / C | 加工 |
| `relevance_score` | 業務関連度 0-100 | 加工 |
| `implication` | MDへの示唆 | 加工 |
| `theme_id` | 継続追跡用のテーマID | 加工 |
| `is_delivered` | ダイジェストに載せたか | 配信 |
| `model_version` | 使ったモデルとプロンプト版 | 加工 |
| `verification_status` | 検証結果 | 検証 |
| `verified_at` | 検証日時 | 検証 |
| `source_count` | 同一事象を報じた情報源の数 | 検証 |
| `evidence_excerpt` | 数値の根拠になった本文の抜粋 | 検証 |
| `conflict_note` | 食い違いや欠落の内容 | 検証 |

**列を足すときは必ず末尾に足すこと。** 途中に挿入すると既存行との対応がずれる。

### `sources` タブ

`feed_name` / `feed_url` / `source_type` / `category_hint` / `is_active` / `note`

情報源の追加・停止はこのタブを手で編集する。スクリプトは読むだけで書き換えない。
`is_active` が `TRUE` の行だけを見にいく。

## 検証ステータス

| status | 意味 | ダイジェスト |
|---|---|---|
| `verified_primary` | 一次発表に到達し、要約の数値も本文と一致 | 載せる（一次発表で確認） |
| `cross_confirmed` | 一次発表なし。複数の情報源が同じ数値を報じている | 載せる（複数報道で一致） |
| `single_report` | 1社のみ。裏付けなし | 載せる（未確認） |
| `conflict` | 他ソースと数値が食い違い、少数派だった | 載せない |
| `summary_mismatch` | 要約の数値が本文にない。要約は破棄 | 載せない |

食い違いは多数決で切り分ける。1社の誤報でグループ全体を落とさないため、
多数派と一致する記事は通し、少数派だけを `conflict` にする。
ただし1対1で割れた場合は多数派が決まらないので、両方を保留にする。

**載せなかった記事も行としては残る。** 消すと「検証していない」という事実まで
消えてしまい、後から「そのニュースがなかった」のか「拾えなかった」のかが
判別できなくなるため。

## この仕組みでできないこと

- **発表内容そのものの正しさは検証できない。** 全社が同じプレスリリースを引き写して
  いる場合、何社が報じていようと裏付けにはならない。`verified_primary` は
  「一次発表と一致している」であって「事実である」ではない。
- 数値の照合は文字列一致で行っている。「5,000」と「5000」は吸収するが、
  「50億」と「5,000,000,000」は別物と判定する。
- 記事本文は冒頭800字しか保存していない。本文後半にしか出てこない数値は
  `summary_mismatch` として弾かれることがある。誤検出側に倒してある。

## 後からBigQueryで分析したくなったら

シートを移し替える必要はない。`ada-bigquery` から外部テーブルとして
このスプレッドシートを参照すれば、そのままSQLで集計できる。

## Claude Code で作業するとき

`CLAUDE.md` に、作業の進め方・触ってはいけないもの・設計意図をまとめてある。
検証ロジックには意図があって選んだ実装が含まれるので、変更前に読むこと。
