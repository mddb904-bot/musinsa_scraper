# -*- coding: utf-8 -*-
"""ダイジェストHTMLの生成。"""

import html
import os
from datetime import datetime, timedelta, timezone

from . import config
from . import verify

JST = timezone(timedelta(hours=9))

CATEGORY_LABEL = {
    "global": ("AI全般・新モデル", "#EEEDFE", "#3C3489"),
    "japan": ("国内動向", "#E1F5EE", "#0F6E56"),
    "tool": ("業務・自動化", "#FAECE7", "#993C1D"),
    "ec": ("EC・アパレル", "#FBEAF0", "#72243E"),
}

STATUS_LABEL = {
    config.ST_VERIFIED_PRIMARY: ("一次発表で確認", "#E1F5EE", "#0F6E56"),
    config.ST_CROSS_CONFIRMED: ("複数報道で一致", "#E6F1FB", "#0C447C"),
    config.ST_SINGLE_REPORT: ("未確認", "#FAEEDA", "#854F0B"),
    config.ST_CONFLICT: ("数値に食い違い", "#FCEBEB", "#A32D2D"),
    config.ST_SUMMARY_MISMATCH: ("要約を破棄", "#FCEBEB", "#A32D2D"),
}

IMPORTANCE_COLOR = {
    "A": ("#FAEEDA", "#854F0B"),
    "B": ("#F1EFE8", "#5F5E5A"),
    "C": ("#F1EFE8", "#5F5E5A"),
}

PAGE = """<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AIニュース日次ダイジェスト {date}</title>
<style>
:root {{ color-scheme: light; }}
body {{ margin:0; padding:32px 20px; background:#FAFAF8; color:#2C2C2A;
  font-family:-apple-system,BlinkMacSystemFont,"Hiragino Sans","Noto Sans JP",sans-serif;
  line-height:1.7; }}
.wrap {{ max-width:760px; margin:0 auto; }}
h1 {{ font-size:20px; font-weight:500; margin:0 0 4px; }}
.sub {{ font-size:13px; color:#888780; margin-bottom:24px; }}
.metrics {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr));
  gap:12px; margin-bottom:28px; }}
.metric {{ background:#F1EFE8; border-radius:8px; padding:14px 16px; }}
.metric .k {{ font-size:12px; color:#5F5E5A; }}
.metric .v {{ font-size:24px; font-weight:500; }}
.card {{ background:#fff; border:0.5px solid #D3D1C7; border-radius:12px;
  padding:18px 22px; margin-bottom:14px; }}
.badges {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:10px; }}
.badge {{ font-size:12px; padding:3px 10px; border-radius:8px; }}
.date {{ font-size:12px; color:#888780; margin-left:auto; }}
.title {{ font-size:16px; font-weight:500; margin-bottom:6px; }}
.summary {{ font-size:14px; color:#5F5E5A; }}
.impl {{ margin-top:12px; background:#E6F1FB; color:#0C447C; border-radius:8px;
  padding:9px 13px; font-size:13px; }}
.note {{ margin-top:12px; background:#FCEBEB; color:#A32D2D; border-radius:8px;
  padding:9px 13px; font-size:13px; }}
.links {{ margin-top:12px; padding-top:12px; border-top:0.5px solid #D3D1C7;
  font-size:12px; display:flex; gap:14px; flex-wrap:wrap; align-items:center; }}
.links a {{ color:#185FA5; text-decoration:none; }}
.links a:hover {{ text-decoration:underline; }}
.foot {{ margin-top:28px; font-size:12px; color:#888780; }}
</style></head><body><div class="wrap">
<h1>AIニュース日次ダイジェスト</h1>
<div class="sub">{date} {time} 更新 ／ 直近{days}日から抽出</div>
<div class="metrics">{metrics}</div>
{cards}
<div class="foot">{footer}</div>
</div></body></html>"""


def esc(text):
    return html.escape(str(text or ""))


def badge(text, bg, fg):
    return '<span class="badge" style="background:%s;color:%s">%s</span>' % (bg, fg, esc(text))


def metric(key, value):
    return '<div class="metric"><div class="k">%s</div><div class="v">%s</div></div>' % (
        esc(key), esc(value))


def render_card(row):
    cat = row.get("category", "global")
    cat_label, cat_bg, cat_fg = CATEGORY_LABEL.get(cat, CATEGORY_LABEL["global"])
    imp = row.get("importance", "C")
    imp_bg, imp_fg = IMPORTANCE_COLOR.get(imp, IMPORTANCE_COLOR["C"])
    status = row.get("verification_status", "")
    st_label, st_bg, st_fg = STATUS_LABEL.get(status, ("", "#F1EFE8", "#5F5E5A"))

    parts = ['<div class="card">', '<div class="badges">']
    parts.append(badge(cat_label, cat_bg, cat_fg))
    parts.append(badge("重要度 " + imp, imp_bg, imp_fg))
    if st_label:
        parts.append(badge(st_label, st_bg, st_fg))
    parts.append('<span class="date">%s</span>' % esc(row.get("published_date", "")))
    parts.append("</div>")

    parts.append('<div class="title">%s</div>' % esc(
        row.get("title_ja") or row.get("title", "")))

    summary = row.get("summary_ja") or ""
    if not summary:
        summary = (row.get("excerpt") or "")[:180] + "…"
        parts.append('<div class="summary">%s</div>' % esc(summary))
    else:
        parts.append('<div class="summary">%s</div>' % esc(summary))

    if row.get("implication"):
        parts.append('<div class="impl">%s</div>' % esc(row["implication"]))
    if row.get("conflict_note"):
        parts.append('<div class="note">%s</div>' % esc(row["conflict_note"]))

    links = []
    if row.get("origin_url"):
        links.append('<a href="%s">一次発表</a>' % esc(row["origin_url"]))
    if row.get("url"):
        links.append('<a href="%s">%s</a>' % (
            esc(row["url"]), esc(row.get("source_name", "記事"))))
    if row.get("source_count"):
        links.append('<span style="color:#888780">ソース %s件</span>' % esc(row["source_count"]))
    parts.append('<div class="links">%s</div>' % "".join(links))

    parts.append("</div>")
    return "".join(parts)


STATUS_RANK = {
    config.ST_VERIFIED_PRIMARY: 0,
    config.ST_CROSS_CONFIRMED: 1,
    config.ST_SINGLE_REPORT: 2,
}


def safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def pick_for_digest(rows):
    """ダイジェストに載せる行を選ぶ。

    同じ出来事を複数社が報じている場合は、いちばん裏付けの強い1件だけを載せる。
    残りは source_count に件数として反映されるので、シート側には残る。
    """
    order = {"A": 0, "B": 1, "C": 2}
    candidates = [
        r for r in rows
        if r.get("verification_status") in config.DELIVERABLE_STATUSES
        and (r.get("title_ja") or r.get("title"))
    ]

    # 同一事象を1件に畳む。一次発表 > 複数報道一致 > 単独、の順で代表を選ぶ。
    representatives = []
    for group in verify.group_similar(candidates):
        group.sort(key=lambda r: (
            STATUS_RANK.get(r.get("verification_status"), 9),
            -safe_int(r.get("relevance_score")),
        ))
        representatives.append(group[0])

    representatives.sort(key=lambda r: (
        order.get(r.get("importance", "C"), 3),
        -safe_int(r.get("relevance_score")),
    ))
    return representatives[: config.DIGEST_MAX_ITEMS]


def render(rows, all_count):
    now = datetime.now(JST)
    picked = pick_for_digest(rows)

    primary = sum(1 for r in picked
                  if r.get("verification_status") == config.ST_VERIFIED_PRIMARY)
    high = sum(1 for r in picked if int(r.get("relevance_score") or 0) >= 60)
    dropped = sum(1 for r in rows
                  if r.get("verification_status") not in config.DELIVERABLE_STATUSES)

    metrics = "".join([
        metric("収集件数", all_count),
        metric("掲載", len(picked)),
        metric("一次発表で確認", primary),
        metric("検証で除外", dropped),
    ])

    cards = "".join(render_card(r) for r in picked) or \
        '<div class="card">該当する記事がありませんでした。</div>'

    footer = ("検証ステータスは「どこまで裏付けが取れたか」を示すものです。"
              "一次発表で確認済みでも、発表内容そのものの正しさは保証しません。")

    page = PAGE.format(
        date=now.strftime("%Y-%m-%d"),
        time=now.strftime("%H:%M"),
        days=config.LOOKBACK_DAYS,
        metrics=metrics,
        cards=cards,
        footer=footer,
    )

    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    path = os.path.join(config.OUTPUT_DIR, "digest_%s.html" % now.strftime("%Y%m%d"))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)

    latest = os.path.join(config.OUTPUT_DIR, "latest.html")
    with open(latest, "w", encoding="utf-8") as fh:
        fh.write(page)

    return path, [r["article_id"] for r in picked]
