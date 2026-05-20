# セットアップ手順書(コマンドライン不要版)

このシステムは全部「ブラウザの画面操作」で組み立てられます。所要時間は**初回約60分**、一度設定すれば後は自動で動き続けます。

> 💡 **このシステムでやること**
> - GitHubに自動実行プログラムを置く
> - 毎週(または毎日)決まった時刻に勝手に動く
> - 取得したデータをBigQueryとスプレッドシートに自動で書き込む
> - エラーが出たらSlackで知らせる

---

## 全体の流れ

| ステップ | やること | 所要時間 |
|---|---|---|
| 1 | GitHubにアカウント作成・リポジトリ作成・ZIPアップロード | 10分 |
| 2 | Google Cloudでプロジェクト準備 | 10分 |
| 3 | BigQueryでテーブル作成 | 5分 |
| 4 | サービスアカウント作成・キーDL | 10分 |
| 5 | スプレッドシート作成・共有設定 | 5分 |
| 6 | Slack Webhook URL発行 | 5分 |
| 7 | GitHubに「秘密の値」4つを登録 | 5分 |
| 8 | 手動で動かしてみる | 5分 |

---

## ステップ1: GitHubにファイルを置く

### 1-1. GitHubアカウントを作る(初めての方のみ)

1. https://github.com/signup を開く
2. メールアドレス・パスワード・ユーザー名を入力して登録

### 1-2. リポジトリ(=プロジェクト置き場)を作る

1. https://github.com/new を開く
2. **Repository name** に `musinsa-scraper` と入力
3. **Private** を選択(他人に見えないようにする)
4. ページ下部の緑色の **「Create repository」** ボタンを押す

### 1-3. ZIPの中身をアップロード

1. お渡しした `musinsa-scraper.zip` をパソコン上で**解凍**(ダブルクリックでOK)
2. リポジトリ画面で、青いリンク **「uploading an existing file」** をクリック
   - もしリンクが見つからない場合: 上部にある **「Add file」** → **「Upload files」**
3. **解凍したフォルダの中身**(`musinsa-scraper` フォルダごとではなく、その中の `README.md` や `src` などのファイル群)をドラッグ&ドロップ
   - ⚠️ フォルダ階層をそのまま保ってください(`src`フォルダの中の`main.py`も一緒に)
4. 一番下の **「Commit changes」** ボタンを押す

→ これでGitHubに全ファイルが置かれました。

---

## ステップ2: Google Cloudプロジェクト準備

### 2-1. Google Cloudにログイン

1. https://console.cloud.google.com を開く
2. Googleアカウントでログイン

### 2-2. プロジェクトを作る

画面上部のプロジェクト選択メニュー(青いバーの中)をクリック → **「新しいプロジェクト」** → 名前を `musinsa-ranking` などで作成

### 2-3. 必要なAPIを有効化

以下のリンクを順番に開いて、それぞれの画面で **「有効にする」** ボタンを押すだけ:

1. [BigQuery API](https://console.cloud.google.com/apis/library/bigquery.googleapis.com) → 有効にする
2. [Google Sheets API](https://console.cloud.google.com/apis/library/sheets.googleapis.com) → 有効にする
3. [Google Drive API](https://console.cloud.google.com/apis/library/drive.googleapis.com) → 有効にする

⚠️ 開くときに画面上部で**先ほど作ったプロジェクトが選択されているか**確認してください。

---

## ステップ3: BigQueryでテーブル作成

### 3-1. データセットを作る

1. https://console.cloud.google.com/bigquery を開く
2. 画面左の「エクスプローラー」内のプロジェクト名(例: `musinsa-ranking`)の**右側の縦三点メニュー**をクリック
3. **「データセットを作成」** を選ぶ
4. 設定:
   - **データセットID**: `musinsa`
   - **ロケーションタイプ**: リージョン
   - **リージョン**: `asia-northeast1 (東京)`
5. **「データセットを作成」** ボタンを押す

### 3-2. テーブルを作る

1. 画面中央上部の **「+」(クエリを新規作成)** をクリック
2. お渡ししたZIPの中の `sql/create_table.sql` ファイルをテキストエディタで開く
3. ファイルの中身を全部コピーして、BigQueryのクエリエディタに貼り付ける
4. **2箇所**を書き換える:
   - `your-project` → 実際のプロジェクトID(画面上部に表示されているもの。例: `musinsa-ranking-12345`)
5. 右上の **「実行」** ボタン(青)を押す
6. 画面下部に「このクエリは0行に影響しました」のような完了メッセージが出ればOK

---

## ステップ4: サービスアカウント作成

サービスアカウントとは「プログラム用のGoogleアカウント」のようなものです。これがBigQueryとスプレッドシートにアクセスします。

### 4-1. アカウント作成

1. https://console.cloud.google.com/iam-admin/serviceaccounts を開く
2. 上部の **「+ サービス アカウントを作成」** を押す
3. **サービスアカウント名**: `musinsa-scraper` と入力
4. **「作成して続行」** を押す
5. **ロール(役割)を3つ追加**:
   - 1つ目: 「BigQueryデータ編集者」を選択
   - **「+ 別のロールを追加」** を押す
   - 2つ目: 「BigQueryジョブユーザー」を選択
6. **「続行」** → **「完了」**

### 4-2. キー(JSONファイル)をダウンロード

1. 一覧から、いま作った `musinsa-scraper@...` をクリック
2. 上部タブから **「キー」** を選択
3. **「鍵を追加」** → **「新しい鍵を作成」**
4. キーのタイプ: **JSON** を選択 → **「作成」**
5. **JSONファイルが自動でダウンロードされます**(後で使うので大切に保管)

### 4-3. ⚠️ メールアドレスをメモ

このサービスアカウントの **メールアドレス**(`musinsa-scraper@xxx.iam.gserviceaccount.com` のような形式)を**メモしておいてください**。次のステップで使います。

---

## ステップ5: スプレッドシート作成

### 5-1. 新しいスプレッドシートを作る

1. https://sheets.new を開く(自動で新規スプレッドシートが開きます)
2. 左上のタイトル「無題のスプレッドシート」をクリックして `MUSINSA Ranking` などに変更

### 5-2. スプレッドシートIDをメモ

URLバーを見ると、こうなっています:
```
https://docs.google.com/spreadsheets/d/【ここの長い文字列がID】/edit
```
**この長い文字列だけをコピー**してメモしておいてください。

### 5-3. サービスアカウントを編集者として招待

1. スプレッドシート右上の **「共有」** ボタンを押す
2. 「ユーザーやグループを追加」の欄に、**ステップ4-3でメモしたメールアドレス**を貼り付け
3. 権限が **「編集者」** になっていることを確認
4. **「通知」のチェックを外す**(サービスアカウントはメール受け取れないので)
5. **「共有」** ボタンを押す

---

## ステップ6: Slack Webhook URL発行

### 6-1. SlackのIncoming Webhookを作る

1. https://api.slack.com/apps を開く
2. **「Create New App」** → **「From scratch」**
3. App名: `MUSINSA Scraper`、ワークスペースを選択 → **「Create App」**
4. 左メニューから **「Incoming Webhooks」** を選択
5. 右上のトグルを **「On」** に切り替え
6. ページ下部の **「Add New Webhook to Workspace」** をクリック
7. 通知を送りたいSlackチャンネルを選択 → **「許可する」**
8. 表示された **Webhook URL**(`https://hooks.slack.com/services/...`)をコピーしてメモ

---

## ステップ7: GitHubに秘密の値を登録

GitHubで自動実行するときに、上で作った認証情報が必要です。これを「Secrets」として登録します。

### 7-1. Secretsの登録画面を開く

1. GitHubのリポジトリページに戻る(ステップ1で作ったやつ)
2. 上部タブの **「Settings」** をクリック
3. 左サイドバーの **「Secrets and variables」** → **「Actions」**
4. **「New repository secret」** ボタンを押す

### 7-2. 以下の4つを順番に登録

毎回「New repository secret」を押して入力 → 「Add secret」で保存、を繰り返します。

| Name(名前) | Secret(値) |
|---|---|
| `GCP_SERVICE_ACCOUNT_JSON` | ステップ4-2でダウンロードしたJSONファイルを**テキストエディタで開いて中身を全文コピペ** |
| `BQ_TABLE` | `あなたのプロジェクトID.musinsa.ranking` (例: `musinsa-ranking-12345.musinsa.ranking`) |
| `GSHEETS_SPREADSHEET_ID` | ステップ5-2でメモしたID |
| `SLACK_WEBHOOK_URL` | ステップ6-1でメモしたWebhook URL |

⚠️ **JSONファイルの中身全文** = `{` で始まり `}` で終わる全部です。

---

## ステップ8: 動作確認(手動実行)

### 8-1. 試しに動かしてみる

1. GitHubリポジトリの上部タブから **「Actions」** をクリック
2. 初回は「I understand my workflows, go ahead and enable them」と出るので押す
3. 左側のリストから **「Scrape MUSINSA Ranking」** をクリック
4. 右側に表示される **「Run workflow」** ボタンを押す
5. もう一度出てくる **「Run workflow」**(緑色)を押す

### 8-2. 実行を見守る

数秒待つとリストに新しい行が出現します。クリックすると進捗が見られます。

- 緑チェックマーク ✅ → 成功!
- 赤バツ ❌ → 失敗。クリックして詳細を確認 + Slackに通知が届いているはず

### 8-3. 結果を確認

- **BigQuery**: https://console.cloud.google.com/bigquery で `musinsa.ranking` テーブルを開き、「プレビュー」タブでデータが入っていることを確認
- **スプレッドシート**: 開くと `overall` `brand_weekly` `brand_monthly` の3シートが自動作成されてデータが入っています

---

## 🎉 ここまで完了したら自動運用開始

設定したCron(週1・月曜午前3時)に自動で動きます。何もしなくて大丈夫です。

### 頻度を変えたいとき(週1↔毎日 切り替え)

1. GitHubリポジトリの `.github/workflows/scrape.yml` をブラウザ上で開く
2. 右上の **鉛筆マーク(✏️)** で編集モード
3. `cron:` の行を書き換える:
   - 週1(月曜3時): `cron: '0 18 * * 0'`
   - 毎日(3時): `cron: '0 18 * * *'`
4. 下部の **「Commit changes」** で保存

---

## トラブル時

- 失敗するとSlackに**エラー内容**が届きます。その中身をそのまま私に送ってください
- Actions画面で赤バツの実行をクリックすると、ログが見られます
- ログの一番下の方にエラー原因が書いてあることが多いです

---

## よくある詰まりポイント

| 症状 | 原因 | 対処 |
|---|---|---|
| BigQueryで「permission denied」 | サービスアカウントのロール不足 | ステップ4-1で2つロール追加しているか確認 |
| Sheetsで「permission denied」 | サービスアカウントを編集者にしてない | ステップ5-3を再確認 |
| 「Spreadsheet not found」 | IDのコピペミス | ステップ5-2のIDを再取得 |
| Workflowが起動しない | Secretsの名前間違い | ステップ7-2のName欄が**完全一致**しているか確認(大文字小文字も) |
