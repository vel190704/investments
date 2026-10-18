"""News / announcement sources. Each returns RawItems or raises SourceUnavailable."""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

from app.net.polite import PoliteClient
from app.timeutil import IST

NSE_FEEDS = {
    "NSE announcements": "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml",
    "NSE board meetings": "https://nsearchives.nseindia.com/content/RSS/Board_Meetings.xml",
    "NSE financial results": "https://nsearchives.nseindia.com/content/RSS/Financial_Results.xml",
    "NSE corporate actions": "https://nsearchives.nseindia.com/content/RSS/Corporate_action.xml",
}
DEFAULT_PUBLISHER_FEEDS = [
    {"name": "ET Markets", "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"},
    {"name": "Mint Markets", "url": "https://www.livemint.com/rss/markets"},
]


@dataclass(frozen=True)
class RawItem:
    title: str
    url: str
    published_at: datetime
    summary: str | None
    source: str
    source_kind: str  # EXCHANGE | NEWS
    symbol_hint: str | None = None  # NSE symbol taken from an exchange link


def _clean(text: str | None, limit: int = 600) -> str | None:
    if not text:
        return None
    t = html.unescape(re.sub(r"<[^>]+>", " ", text))
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit] or None


def _date(text: str | None) -> datetime | None:
    if not text:
        return None
    text = text.strip()
    try:
        d = parsedate_to_datetime(text)  # RFC 822 (publisher feeds)
        return d if d.tzinfo else d.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        pass
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y"):  # NSE: 17-Oct-2026 13:06:20 (IST)
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=IST)
        except ValueError:
            continue
    return None


def parse_rss(xml_text: str, source: str, kind: str) -> list[RawItem]:
    try:
        root = ET.fromstring(xml_text.encode() if isinstance(xml_text, str) else xml_text)
    except ET.ParseError as e:
        raise ValueError(f"{source}: not valid RSS ({e})") from None
    out = []
    for it in root.iter("item"):
        title = _clean(it.findtext("title"), 400)
        link = (it.findtext("link") or "").strip()
        when = _date(it.findtext("pubDate"))
        if not title or not link or not when:
            continue
        hint = None
        if kind == "EXCHANGE":
            m = re.search(r"/corporate/(?:xbrl/)?([A-Z0-9&\-]+?)_", link)
            hint = m.group(1) if m else None
        desc = _clean(it.findtext("description"))
        if kind == "EXCHANGE" and desc and "|SUBJECT:" in desc.replace(" |SUBJECT:", "|SUBJECT:"):
            desc = desc.replace(" |SUBJECT:", " | Subject:")
        out.append(RawItem(title, link, when, desc, source, kind, hint))
    return out


def fetch_nse(client: PoliteClient) -> tuple[list[RawItem], dict[str, str]]:
    """All NSE feeds. Returns (items, {feed: error}) — a failing feed doesn't stop the others."""
    items, errors = [], {}
    for name, url in NSE_FEEDS.items():
        try:
            items += parse_rss(client.get_text(url, name), name, "EXCHANGE")
        except Exception as e:
            errors[name] = str(e)
    return items, errors


def fetch_publisher(client: PoliteClient, name: str, url: str) -> list[RawItem]:
    return parse_rss(client.get_text(url, f"News feed: {name}"), name, "NEWS")


def google_news_url(company: str, symbol: str | None) -> str:
    q = f'"{company}"' + (f" {symbol}" if symbol else "")
    return f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=en-IN&gl=IN&ceid=IN:en"


def fetch_google_news(client: PoliteClient, company: str, symbol: str | None) -> list[RawItem]:
    """Requested source. Its robots.txt disallows /rss, so the polite client refuses it (SourceUnavailable)."""
    return parse_rss(client.get_text(google_news_url(company, symbol), "Google News"), "Google News", "NEWS")
