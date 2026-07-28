# -*- coding: utf-8 -*-
"""裏付け検証。

4段階:
  1. 一次発表への到達（collect 側で origin_url を解決済み）
  2. 数字の突合   … 要約に出てくる数値が取得元の本文にあるか
  3. 発表日の確定 … collect 側で一次発表の meta から取り直し済み
  4. 複数ソースの一致確認 … 同一事象を報じる記事どうしで数値が食い違わないか

「正しさ」を保証するものではなく、どこまで確かめられたかを記録するもの。
"""

import re
import unicodedata
from datetime import datetime, timedelta, timezone


from . import config

JST = timezone(timedelta(hours=9))

# 数値と単位の組を拾う。単位なしの数値は 2 桁以上だけを対象にする。
UNIT_PATTERN = r"(?:%|％|億円|兆円|億ドル|万ドル|億|兆|万|円|ドル|GW|MW|社|名|人|件|倍|時間|分|年|月|日|基|台)"
NUMBER_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(" + UNIT_PATTERN + r")?")


def normalize(text):
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_numbers(text):
    """(数値文字列, 単位) のリストを返す。照合対象になるものだけ。"""
    out = []
    for m in NUMBER_RE.finditer(normalize(text)):
        digits = m.group(1).replace(",", "")
        unit = m.group(2) or ""
        if not unit and len(digits.split(".")[0]) < 2:
            continue  # 単位なしの 1 桁は誤検出が多いので見ない
        out.append((digits, unit))
    return out


def number_check(summary, body):
    """要約中の数値が本文に存在するか照合する。

    戻り値: (欠落していた数値のリスト, 根拠として使える本文の抜粋)
    """
    body_norm = normalize(body)
    body_digits = {d.replace(",", "") for d, _ in extract_numbers(body_norm)}
    missing = []
    evidence = ""
    for digits, unit in extract_numbers(summary):
        if digits in body_digits:
            if not evidence:
                evidence = find_context(body_norm, digits)
        else:
            missing.append(digits + unit)
    return missing, evidence


def find_context(body, digits, width=60):
    idx = body.find(digits)
    if idx < 0:
        return ""
    start = max(0, idx - width)
    end = min(len(body), idx + len(digits) + width)
    return body[start:end]


def title_key(title):
    t = normalize(title)
    t = re.sub(r"[「」『』【】（）\(\)\[\]、。・,\.\-–—:：!！?？|｜]", "", t)
    return t.replace(" ", "")


def bigrams(text):
    if len(text) < 2:
        return {text} if text else set()
    return {text[i:i + 2] for i in range(len(text) - 1)}


def similarity(a, b):
    """文字バイグラムのDice係数。

    日本語の見出しでは difflib の比率より分離がはっきり出る。
    同一事象を報じた見出しどうしで 0.5 前後、無関係なら 0.0 付近になる。
    """
    ba, bb = bigrams(a), bigrams(b)
    if not ba or not bb:
        return 0.0
    return 2 * len(ba & bb) / (len(ba) + len(bb))


def group_similar(rows, threshold=0.35):
    """似たタイトルの記事をまとめる。同一事象の複数報道を見つけるため。"""
    groups = []
    for row in rows:
        key = title_key(row.get("title_ja") or row.get("title", ""))
        if not key:
            groups.append([row])
            continue
        placed = False
        for g in groups:
            ref = title_key(g[0].get("title_ja") or g[0].get("title", ""))
            if similarity(key, ref) >= threshold:
                g.append(row)
                placed = True
                break
        if not placed:
            groups.append([row])
    return groups


def row_numbers(row):
    text = (row.get("summary_ja") or "") + " " + (row.get("title_ja") or "")
    return {(unit, digits) for digits, unit in extract_numbers(text) if unit}


def detect_conflict(group):
    """同じ単位に違う値を報じている箇所を、多数決で切り分ける。

    1社の誤報でグループ全体を巻き添えにしないため、
    多数派と一致する行は通し、少数派の行だけを conflict にする。

    戻り値: (少数派だった行の _row の集合, 単位ごとの食い違いの説明)
    """
    votes = {}
    for row in group:
        for unit, digits in row_numbers(row):
            votes.setdefault(unit, {}).setdefault(digits, set()).add(row.get("_row"))

    minority_rows = set()
    notes = []
    for unit, by_value in votes.items():
        if len(by_value) < 2:
            continue
        ranked = sorted(by_value.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        top_value, top_rows = ranked[0]
        others = ranked[1:]

        # 最多が単独でなければ（同数で割れていれば）全員を保留にする。
        tied = [v for v, rows_ in others if len(rows_) == len(top_rows)]
        if tied:
            for _, rows_ in ranked:
                minority_rows |= rows_
        else:
            for _, rows_ in others:
                minority_rows |= rows_

        notes.append("%s: %s" % (
            unit,
            " / ".join("%s(%d件)" % (v, len(r)) for v, r in ranked),
        ))

    return minority_rows, notes


def is_primary(row):
    src_type = (row.get("source_type") or "").strip()
    return src_type == "official" or bool((row.get("origin_url") or "").strip())


def verify_rows(rows):
    """検証結果を各行に書き込む。rows は辞書のリスト（破壊的に更新する）。

    戻り値: [(row_number, {更新する列: 値}), ...]
    """
    verified_at = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
    updates = []

    for group in group_similar(rows):
        minority_rows, conflict_notes = detect_conflict(group)
        source_names = {r.get("source_name", "") for r in group if r.get("source_name")}
        source_count = len(source_names) or len(group)

        for row in group:
            summary = row.get("summary_ja", "")
            body = row.get("excerpt", "")
            missing, evidence = number_check(summary, body)
            in_minority = row.get("_row") in minority_rows

            if missing:
                status = config.ST_SUMMARY_MISMATCH
            elif in_minority:
                status = config.ST_CONFLICT
            elif is_primary(row):
                status = config.ST_VERIFIED_PRIMARY
            elif source_count >= 2:
                status = config.ST_CROSS_CONFIRMED
            else:
                status = config.ST_SINGLE_REPORT

            note = ""
            if missing:
                note = "本文に見当たらない数値: " + ", ".join(missing)
            elif in_minority:
                note = "他ソースと不一致: " + " / ".join(conflict_notes)
            elif conflict_notes:
                # 多数派側。食い違いがあった事実だけ残す。
                note = "少数派の異なる報道あり: " + " / ".join(conflict_notes)

            row["verification_status"] = status
            row["verified_at"] = verified_at
            row["source_count"] = str(source_count)
            row["evidence_excerpt"] = evidence[:300]
            row["conflict_note"] = note[:300]

            # 要約の数値が裏取りできなかった場合、要約は捨てて原文抜粋に戻す。
            if status == config.ST_SUMMARY_MISMATCH:
                row["summary_ja"] = ""

            updates.append((row["_row"], {
                "verification_status": row["verification_status"],
                "verified_at": row["verified_at"],
                "source_count": row["source_count"],
                "evidence_excerpt": row["evidence_excerpt"],
                "conflict_note": row["conflict_note"],
                "summary_ja": row["summary_ja"],
            }))

    return updates
