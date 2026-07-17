-- BigQuery ブランドランキング テーブル作成DDL
-- 実行前に `your-project` と `musinsa` を実際のプロジェクトID・データセット名に置換してください。
-- (既存の ranking テーブルと同じデータセットに置く想定)
--
-- このDDLをBigQueryコンソール、または bq query --use_legacy_sql=false で実行。

CREATE TABLE IF NOT EXISTS `your-project.musinsa.brand_ranking`
(
  date_key DATE NOT NULL OPTIONS(description="取得日 (Asia/Tokyo, YYYY-MM-DD)"),
  rank INT64 NOT NULL OPTIONS(description="ブランド順位"),
  brand_id STRING OPTIONS(description="ブランドID(slug)"),
  brand_name STRING OPTIONS(description="ブランド名"),
  brand_url STRING OPTIONS(description="ブランドページURL"),
  is_musinsa_exclusive BOOL OPTIONS(description="MUSINSA独占バッジの有無。判定不能時はNULL"),
  scraped_at TIMESTAMP NOT NULL OPTIONS(description="取得時刻 (UTC)")
)
PARTITION BY date_key
CLUSTER BY rank
OPTIONS(
  description="MUSINSAブランドランキング(ブランド単位・日次・上位100)",
  partition_expiration_days=NULL
);
