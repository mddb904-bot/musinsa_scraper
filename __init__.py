-- BigQuery テーブル作成DDL
-- 実行前に `your-project` と `musinsa` を実際のプロジェクトIDとデータセット名に置換してください
--
-- データセットを先に作成:
--   bq --location=asia-northeast1 mk -d --description "MUSINSA ranking data" musinsa
--
-- このDDLをBigQueryコンソールまたは bq query --use_legacy_sql=false で実行

CREATE TABLE IF NOT EXISTS `your-project.musinsa.ranking`
(
  date_key DATE NOT NULL OPTIONS(description="取得日 (Asia/Tokyo, YYYY-MM-DD)"),
  ranking_type STRING NOT NULL OPTIONS(description="overall / brand_weekly / brand_monthly"),
  brand_name STRING NOT NULL OPTIONS(description="ブランド名。全体ランキングは 'All'"),
  brand_id STRING OPTIONS(description="ブランドID(slug)。全体ランキングはNULL"),
  rank INT64 NOT NULL OPTIONS(description="ランキング順位"),
  product_id STRING NOT NULL OPTIONS(description="MUSINSA商品ID (goodsNo)"),
  product_name STRING OPTIONS(description="商品名"),
  category STRING OPTIONS(description="カテゴリ(取得可能な場合)"),
  image_url STRING OPTIONS(description="商品画像URL"),
  price INT64 OPTIONS(description="価格(円, セール後)"),
  normal_price INT64 OPTIONS(description="定価(円)"),
  sale_rate INT64 OPTIONS(description="セール率(%)"),
  favorite_count INT64 OPTIONS(description="お気に入り数"),
  listing_date DATE OPTIONS(description="掲載日(画像URLパスから推定)"),
  product_url STRING OPTIONS(description="商品詳細URL"),
  product_brand_name STRING OPTIONS(description="商品が属するブランド名(全体ランキング時に有用)"),
  product_brand_id STRING OPTIONS(description="商品が属するブランドID"),
  scraped_at TIMESTAMP NOT NULL OPTIONS(description="取得時刻 (UTC)")
)
PARTITION BY date_key
CLUSTER BY ranking_type, brand_name
OPTIONS(
  description="MUSINSA女性ランキング(全体TOP200 + ブランド独自weekly/monthly)",
  partition_expiration_days=NULL
);
