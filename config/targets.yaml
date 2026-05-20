# MUSINSAランキング取得対象
# 頻度・実行タイミングは .github/workflows/scrape.yml の Cron で制御

# 女性全体ランキング (集計期間の区別なし)
overall:
  url: "https://global.musinsa.com/jp/trending/items"
  gender: "F"
  top_n: 200  # 上位N位まで取得

# ブランド独自ランキング
# URL形式: https://global.musinsa.com/jp/brands/{slug}/trending?period={weekly|monthly}
brands:
  - slug: mucent
    name: MUCENT
  - slug: asyouare
    name: ASYOUARE
  - slug: coiris
    name: COIRIS
  - slug: catsavetheworld
    name: CATSAVETHEWORLD
  - slug: eyeer
    name: EYEER
  - slug: setupexe
    name: SETUPEXE
  - slug: heisan
    name: HEISAN
  - slug: porterna
    name: PORTERNA
  - slug: nastyfancyclub  # 表示名は FANCYCLUB
    name: FANCYCLUB

# ブランドランキングの期間
brand_periods:
  - weekly
  - monthly

brand_top_n: 200  # 各ブランドで上位何件まで取得するか

# リクエスト間隔(サーバー負荷配慮 / 秒)
request_interval_seconds: 2
