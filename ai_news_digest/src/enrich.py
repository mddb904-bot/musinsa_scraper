# -*- coding: utf-8 -*-
"""Claude API で要約・分類・示唆を作る。

数値は本文に書かれているものだけを使うよう明示的に縛っている。
それでも外すことがあるので、後段の verify で必ず照合する。
"""

import json
import re

import anthropic

from . import config

SYSTEM_PROMPT = """あなたはアパレルEC事業者のMD（マーチャンダイザー）に向けて、AI関連ニュースを要約するアシスタントです。
読み手はZOZOに出店するブランドの運営を担当し、BigQueryでの分析やPythonでの業務自動化を自分で行う非エンジニアです。

厳守すること:
- 数値は、与えられた本文に明記されているものだけを書く。本文にない数値を補わない。
- 本文から読み取れないことは書かない。推測で埋めない。
- 誇張しない。「画期的」「衝撃」のような煽り表現を使わない。
- 出力はJSONのみ。前置きもマークダウンのコードフェンスも付けない。

出力するJSONの形式:
{
  "title_ja": "40字以内の見出し",
  "summary_ja": "2〜3文の要約。本文にある事実のみ",
  "category": "global | japan | tool | ec のいずれか",
  "importance": "A | B | C のいずれか",
  "relevance_score": 0から100の整数,
  "implication": "この読み手の業務にどう関係するかを1文。関係が薄ければ空文字",
  "theme_id": "継続追跡用のテーマID。英小文字とハイフンのみ。例: zozo-ai-agent"
}

categoryの定義:
  global … AI全般、新モデル、海外大手の動向
  japan  … 国内企業・政府のAI導入動向
  tool   … 業務効率化・自動化に使えるツールやAPIの話
  ec     … EC、アパレル、小売でのAI活用

importanceの定義:
  A … 業界の前提が変わる、または読み手の業務に直接影響する
  B … 知っておくと判断材料になる
  C … 流し読みで十分

relevance_scoreは、読み手自身の業務（ZOZO運用、データ分析、業務自動化）との距離。
遠い話に高い点を付けない。"""

USER_TEMPLATE = """タイトル: {title}
情報源: {source_name}（{source_type}）
発表日: {published_date}

本文:
{excerpt}"""


def get_client():
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY が設定されていません")
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def strip_fences(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def enrich_one(client, row):
    """1件を加工して、更新すべき列の辞書を返す。失敗したら None。"""
    excerpt = (row.get("excerpt") or "").strip()
    if not excerpt:
        return None

    message = client.messages.create(
        model=config.MODEL,
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": USER_TEMPLATE.format(
                title=row.get("title", ""),
                source_name=row.get("source_name", ""),
                source_type=row.get("source_type", ""),
                published_date=row.get("published_date", ""),
                excerpt=excerpt[:6000],
            ),
        }],
    )

    text = "".join(b.text for b in message.content if getattr(b, "type", "") == "text")
    try:
        data = json.loads(strip_fences(text))
    except json.JSONDecodeError:
        return None

    score = data.get("relevance_score", 0)
    try:
        score = max(0, min(100, int(score)))
    except (TypeError, ValueError):
        score = 0

    category = data.get("category", "")
    if category not in ("global", "japan", "tool", "ec"):
        category = "global"

    importance = data.get("importance", "")
    if importance not in ("A", "B", "C"):
        importance = "C"

    return {
        "title_ja": str(data.get("title_ja", ""))[:120],
        "summary_ja": str(data.get("summary_ja", ""))[:600],
        "category": category,
        "importance": importance,
        "relevance_score": str(score),
        "implication": str(data.get("implication", ""))[:300],
        "theme_id": re.sub(r"[^a-z0-9\-]", "", str(data.get("theme_id", "")).lower())[:60],
        "model_version": "%s/%s" % (config.MODEL, config.PROMPT_VERSION),
    }


def enrich_rows(rows):
    """未加工の行をまとめて処理する。

    戻り値: [(row_number, {更新する列: 値}), ...]
    rows 自体にも結果を書き戻す（後段の verify がそのまま使えるように）。
    """
    client = get_client()
    updates = []
    for row in rows:
        try:
            fields = enrich_one(client, row)
        except anthropic.APIError as exc:
            print("  加工に失敗 (%s): %s" % (row.get("article_id", ""), exc))
            continue
        if not fields:
            continue
        row.update(fields)
        updates.append((row["_row"], fields))
    return updates
