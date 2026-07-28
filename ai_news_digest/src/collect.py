# -*- coding: utf-8 -*-
"""記事の収集。

やること:
  1. sources タブのフィードを読む
  2. RSS を取得して記事の候補を作る
  3. article_id で重複を落とす
  4. まとめ記事なら本文中のリンクを辿って一次発表 URL を拾う
  5. articles タブに追記する（AI 加工列は空のまま）
"""

import hashlib
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import feedparser
import requests
from bs4 import BeautifulSoup

from . import config
from . import sheets_client as sc

JST = timezone(timedelta(hours=9))

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ref", "ref_src", "spm",
}


def now_jst():
    return datetime.now(JST)


def normalize_url(url):
    """トラッキングパラメータを落として URL を正規化する。"""
    try:
        p = urlparse(url.strip())
    except ValueError:
        return url.strip()
    query = [(k, v) for k, v in parse_qsl(p.query) if k not in TRACKING_PARAMS]
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme, p.netloc.lower(), path, "", urlencode(query), ""))


def article_id(url):
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()[:16]


def domain_of(url):
    try:
        return urlparse(url).netloc.lower()
    except ValueError:
        return ""


def matches_any(url, patterns):
    host = domain_of(url)
    return any(p in host for p in patterns)


def classify_source_type(url, hint=""):
    if matches_any(url, config.OFFICIAL_DOMAIN_PATTERNS):
        return "official"
    if matches_any(url, config.AGGREGATOR_DOMAIN_PATTERNS):
        return "blog"
    return hint or "media"


def fetch(url):
    """HTML を取得する。失敗したら空文字を返す（例外で全体を止めない）。"""
    try:
        res = requests.get(
            url,
            timeout=config.REQUEST_TIMEOUT,
            headers={"User-Agent": config.USER_AGENT},
        )
        if res.status_code != 200:
            return ""
        res.encoding = res.apparent_encoding or res.encoding
        return res.text
    except requests.RequestException:
        return ""


def page_text(html):
    """本文っぽいテキストを抜く。数値照合に使うだけなので厳密でなくてよい。"""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text)


def meta_published_date(html):
    """meta タグから発表日を拾う。取れなければ空文字。"""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    keys = [
        ("property", "article:published_time"),
        ("name", "pubdate"),
        ("name", "date"),
        ("itemprop", "datePublished"),
    ]
    for attr, val in keys:
        tag = soup.find("meta", attrs={attr: val})
        if tag and tag.get("content"):
            m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", tag["content"])
            if m:
                return "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
    time_tag = soup.find("time")
    if time_tag and time_tag.get("datetime"):
        m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", time_tag["datetime"])
        if m:
            return "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
    return ""


def resolve_origin(url, html):
    """まとめ記事の本文から一次発表へのリンクを探す。

    見つからなければ空文字を返す。無理に埋めない。
    """
    if not html:
        return ""
    if matches_any(url, config.OFFICIAL_DOMAIN_PATTERNS):
        return ""  # 自分が一次発表なので辿る必要がない
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("http"):
            continue
        if domain_of(href) == domain_of(url):
            continue
        if matches_any(href, config.OFFICIAL_DOMAIN_PATTERNS):
            return normalize_url(href)
    return ""


def entry_published_date(entry):
    for key in ("published_parsed", "updated_parsed"):
        val = getattr(entry, key, None)
        if val:
            return "%04d-%02d-%02d" % (val.tm_year, val.tm_mon, val.tm_mday)
    return ""


def load_sources():
    """sources タブから有効なフィードを読む。"""
    _, rows = sc.read_all(config.TAB_SOURCES)
    active = []
    for r in rows:
        if str(r.get("is_active", "")).strip().upper() not in ("TRUE", "1", "YES"):
            continue
        if not r.get("feed_url"):
            continue
        active.append(r)
    return active


def collect():
    """収集して articles タブに追記する。追記した件数を返す。"""
    known = sc.existing_article_ids(config.TAB_ARTICLES)
    cutoff = (now_jst() - timedelta(days=config.LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    collected_at = now_jst().strftime("%Y-%m-%d %H:%M:%S")

    new_rows = []
    seen_this_run = set()

    for src in load_sources():
        feed = feedparser.parse(src["feed_url"])
        for entry in feed.entries[: config.MAX_ITEMS_PER_FEED]:
            url = getattr(entry, "link", "")
            if not url:
                continue
            aid = article_id(url)
            if aid in known or aid in seen_this_run:
                continue

            published = entry_published_date(entry)
            if published and published < cutoff:
                continue

            html = fetch(url)
            body = page_text(html)
            if not published:
                published = meta_published_date(html)

            origin = resolve_origin(url, html)
            source_type = classify_source_type(origin or url, src.get("source_type", ""))

            # 一次発表に辿り着いたら、発表日はそちらから取り直す。
            if origin:
                origin_html = fetch(origin)
                origin_date = meta_published_date(origin_html)
                if origin_date:
                    published = origin_date

            seen_this_run.add(aid)
            new_rows.append({
                "article_id": aid,
                "collected_at": collected_at,
                "source_name": src.get("feed_name", domain_of(url)),
                "source_type": source_type,
                "url": normalize_url(url),
                "origin_url": origin,
                "title": getattr(entry, "title", "").strip(),
                "published_date": published,
                "excerpt": body[:800],
                "is_delivered": "FALSE",
            })

    sc.append_dicts(config.TAB_ARTICLES, new_rows, config.ARTICLE_COLUMNS)
    return len(new_rows)


if __name__ == "__main__":
    print("collected: %d" % collect())
