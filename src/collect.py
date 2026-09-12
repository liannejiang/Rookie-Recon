"""抓取 RSS/Atom 來源，正規化、去重、篩出時間範圍內的項目。"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
feedparser.PREFERRED_XML_PARSERS = []

import socket
socket.setdefaulttimeout(20)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

log = logging.getLogger(__name__)

# 常見的追蹤參數，去重前先移除，否則同一篇文章會被當成兩篇
TRACKING_PARAMS = re.compile(
    r"^(utm_|ito_|mc_|_hs|ref$|ref_|fbclid$|gclid$|igshid$|source$|amp$)"
)
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class Item:
    """一則候選新聞。"""

    title: str
    url: str
    source: str
    lang: str
    published: datetime
    summary: str = ""
    trust: float = 1.0
    region: str | None = None
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        """標題 + 摘要，供關鍵字比對與抄襲檢查使用。"""
        return f"{self.title}\n{self.summary}"


def strip_html(raw: str) -> str:
    """把 RSS 摘要裡的 HTML 標籤清掉，還原 HTML entity。"""
    if not raw:
        return ""
    text = TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    return WHITESPACE_RE.sub(" ", text).strip()


def canonical_url(url: str) -> str:
    """去掉追蹤參數與 fragment，統一小寫網域，用來當去重的 key。"""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url

    query = [(k, v) for k, v in parse_qsl(parts.query) if not TRACKING_PARAMS.match(k)]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), "")
    )


def entry_time(entry) -> datetime | None:
    """
    取出發布時間並轉成 UTC aware datetime。

    feedparser 會把各種日期格式統一成 time.struct_time（UTC），
    但不是每個來源都有 published，所以 updated 當備援。
    """
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def fetch_source(source: dict, since: datetime) -> list[Item]:
    """抓單一來源。任何失敗都只記 log，不讓整批中斷。"""
    try:
        feed = feedparser.parse(source["url"])    
    except Exception as exc:  # feedparser 很少 raise，但網路層可能會
        log.warning("抓取失敗 %s：%s", source["name"], exc)
        return []

    if feed.get("bozo") and not feed.entries:
        log.warning(
            "來源解析失敗且無項目 %s：%s",
            source["name"],
            feed.get("bozo_exception"),
        )
        return []

    items: list[Item] = []
    skipped_no_date = 0

    for entry in feed.entries:
        published = entry_time(entry)
        if published is None:
            skipped_no_date += 1
            continue
        if published < since:
            continue

        title = strip_html(entry.get("title", "")).strip()
        url = entry.get("link", "").strip()
        if not title or not url:
            continue

        summary = strip_html(
            entry.get("summary") or entry.get("description") or ""
        )[:1500]

        items.append(
            Item(
                title=title,
                url=url,
                source=source["name"],
                lang=source.get("lang", "en"),
                published=published,
                summary=summary,
                trust=source.get("trust", 1.0),
                region=source.get("region"),
            )
        )

    if skipped_no_date:
        log.info("%s：%d 則沒有日期欄位，已跳過", source["name"], skipped_no_date)
    log.info("%s：取得 %d 則", source["name"], len(items))
    return items


def dedupe(items: list[Item]) -> list[Item]:
    """
    兩層去重：
    1. 正規化後的 URL 完全相同
    2. 標題正規化後相同（不同媒體轉載同一則）
    保留發布時間較早、來源可信度較高的那一則。
    """
    by_url: dict[str, Item] = {}
    for item in sorted(items, key=lambda i: (-i.trust, i.published)):
        key = canonical_url(item.url)
        if key not in by_url:
            by_url[key] = item

    by_title: dict[str, Item] = {}
    for item in by_url.values():
        key = WHITESPACE_RE.sub("", item.title.lower())[:60]
        if key not in by_title:
            by_title[key] = item

    removed = len(items) - len(by_title)
    if removed:
        log.info("去重移除 %d 則", removed)
    return list(by_title.values())


def collect(sources: list[dict], days: int) -> list[Item]:
    """抓完所有來源，去重後回傳。"""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    items: list[Item] = []
    for source in sources:
        items.extend(fetch_source(source, since))
    log.info("原始總計 %d 則", len(items))
    return dedupe(items)

import requests

def probe(url: str) -> str:
    """直接看對方回了什麼，判斷是被擋還是 feed 真的壞掉。"""
    try:
        r = requests.get(url, timeout=20)
        head = r.text[:120].replace("\n", " ")
        return f"HTTP {r.status_code} · {r.headers.get('content-type','?')} · {head}"
    except Exception as exc:
        return f"連線失敗：{exc}"

def check_feeds(sources: list[dict]) -> int:
    """
    逐一測試每個來源，印出狀態。RSS 網址會變，第一次設定或
    連續幾週沒新聞時先跑這個，比猜快得多。回傳失效的來源數。
    """
    broken = 0
    print(f"\n檢查 {len(sources)} 個來源\n" + "─" * 72)

    for source in sources:
        try:
            feed = feedparser.parse(source["url"])
        except Exception as exc:
            print(f"✗  {source['name']:<28} 連線失敗：{exc}")
            print(f"   └─ {probe(source['url'])}")
            broken += 1
            continue

        count = len(feed.entries)
        dated = sum(1 for e in feed.entries if entry_time(e) is not None)

        if count == 0:
            note = feed.get("bozo_exception") or "無法解析或網址已失效"
            print(f"✗  {source['name']:<28} 0 則（{note}）")
            print(f"   └─ {probe(source['url'])}")
            broken += 1
        elif dated == 0:
            print(f"!  {source['name']:<28} {count} 則，但都沒有日期欄位（無法篩時間）")
            print(f"   └─ {probe(source['url'])}")
            broken += 1
        else:
            newest = max(
                (entry_time(e) for e in feed.entries if entry_time(e)),
                default=None,
            )
            age = (datetime.now(timezone.utc) - newest).days if newest else "?"
            flag = "!" if isinstance(age, int) and age > 14 else "✓"
            print(f"{flag}  {source['name']:<28} {count} 則，最新 {age} 天前")

    print("─" * 72)
    print(f"{len(sources) - broken} 個正常，{broken} 個有問題\n")
    return broken
