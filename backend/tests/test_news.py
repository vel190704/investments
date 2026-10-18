from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app.calc import news as nc
from app.importer.run import import_workbook
from app.models import Instrument, NewsItem, NewsSourceStatus
from app.net.polite import PoliteClient, SourceUnavailable
from app.news import sources as src
from app.services import news as ns

NOW = datetime(2026, 10, 17, 8, 0, tzinfo=UTC)


@pytest.mark.parametrize("title,cat", [
    ("Larsen & Toubro bags order worth Rs 2,000 crore from NHAI", "order win / contract"),
    ("SBI Q2 results: net profit rises 12%", "results"),
    ("ITC announces interim dividend; record date for payout", "dividend"),
    ("Outcome of Board Meeting to consider financial results", "board meeting"),
    ("Tata Power to acquire 49% stake in renewable unit", "acquisition / merger"),
    ("SEBI imposes penalty on company for disclosure lapse", "regulatory / legal"),
    ("Biocon appoints new Chief Financial Officer", "management change"),
    ("CRISIL reaffirms AAA credit rating", "rating action"),
    ("Markets end flat ahead of holiday", "other"),
])
def test_rule_categories(title, cat):
    assert nc.categorize(title) == cat


def test_near_duplicate_headlines():
    t0 = NOW
    existing = [("L&T bags Rs 2,000 crore order from NHAI", t0)]
    assert nc.is_near_duplicate("L&T bags Rs 2,000-crore order from NHAI", t0 + timedelta(hours=3), existing)
    assert not nc.is_near_duplicate("L&T bags Rs 2,000 crore order from NHAI", t0 + timedelta(days=5), existing)
    assert not nc.is_near_duplicate("L&T Q2 results beat estimates", t0, existing)


def test_company_matching_is_conservative():
    pats = nc.company_patterns("Bharat Electronics Ltd", "BEL")
    assert nc.mentions("Bharat Electronics wins defence order", pats)
    assert nc.mentions("BEL shares climb after order", pats)
    assert not nc.mentions("Bell rings at the exchange", pats) and not nc.mentions("bel air hotel", pats)
    itc = nc.company_patterns("ITC", "ITC")
    assert nc.mentions("ITC hotels demerger update", itc) and not nc.mentions("Witcher", itc)


def test_feed_ranked_by_lookthrough_exposure():
    items = [{"isin": "A", "published_ts": 3}, {"isin": "B", "published_ts": 2}, {"isin": "B", "published_ts": 5},
             {"isin": "C", "published_ts": 9}]
    out = nc.rank_feed(items, {"A": 0.05, "B": 0.20})
    assert [(i["isin"], i["published_ts"]) for i in out] == [("B", 5), ("B", 2), ("A", 3), ("C", 9)]


NSE_XML = """<rss version="2.0"><channel>
<item><title>Larsen &amp; Toubro Limited</title><link>https://nsearchives.nseindia.com/corporate/LT_17102026120000_Order.pdf</link>
<description>Larsen &amp; Toubro Limited has informed the Exchange about order win |SUBJECT: Bagging/Receiving of orders/contracts</description>
<pubDate>17-Oct-2026 12:00:00</pubDate></item>
<item><title>Other Co Limited</title><link>https://nsearchives.nseindia.com/corporate/OTHERCO_17102026120000_x.pdf</link>
<description>x</description><pubDate>17-Oct-2026 11:00:00</pubDate></item>
<item><title>Larsen &amp; Toubro Limited</title><link>https://nsearchives.nseindia.com/corporate/LT_01062026120000_old.pdf</link>
<description>Old filing</description><pubDate>01-Jun-2026 10:00:00</pubDate></item>
</channel></rss>"""
PUB_XML = """<rss version="2.0"><channel>
<item><title>Larsen &amp; Toubro shares rise after big order</title><link>https://pub.example/lt-1</link>
<pubDate>Fri, 17 Oct 2026 06:00:00 GMT</pubDate><description>&lt;p&gt;Source text&lt;/p&gt;</description></item>
<item><title>Larsen and Toubro? No: Bellwether index ends higher</title><link>https://pub.example/x</link>
<pubDate>Fri, 17 Oct 2026 06:00:00 GMT</pubDate></item>
</channel></rss>"""


def make_client(log):
    def handler(req: httpx.Request):
        log.append(str(req.url))
        host, path = req.url.host, req.url.path
        if path == "/robots.txt":
            if host == "news.google.com":
                return httpx.Response(200, text="User-agent: *\nDisallow: /\nAllow: /$\n")
            if host == "blocked.example":
                return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
            return httpx.Response(404)
        if host == "nsearchives.nseindia.com":
            return httpx.Response(200, text=NSE_XML if "Online" in path else "<rss><channel></channel></rss>")
        if host == "pub.example":
            return httpx.Response(200, text=PUB_XML)
        if host == "down.example":
            return httpx.Response(403)
        return httpx.Response(404)
    return PoliteClient(transport=httpx.MockTransport(handler), min_interval=0)


def test_robots_guard_refuses_google_news():
    log = []
    c = make_client(log)
    with pytest.raises(SourceUnavailable, match="robots.txt of news.google.com disallows"):
        c.get_text(src.google_news_url("Larsen & Toubro", "LT"))
    assert all("/rss/search" not in u for u in log)  # never fetched


def test_blocked_source_is_not_retried():
    c = make_client([])
    with pytest.raises(SourceUnavailable, match="HTTP 403; not retried"):
        c.get_text("https://down.example/feed.xml")


def test_refresh_stores_by_isin_dedupes_and_reports_unavailable(session, workbook, monkeypatch):
    import_workbook(session, workbook)
    lt = session.scalar(select(Instrument).where(Instrument.symbol == "LT"))
    lt.isin = "INE018A01030"
    from app.services import settings as st
    st.put(session, "news", {"feeds": [{"name": "Example Pub", "url": "https://pub.example/rss"}]})
    rep = ns.refresh_news(session, make_client([]), now=NOW)
    items = session.scalars(select(NewsItem)).all()
    assert {(i.source_kind, i.category) for i in items} == {("EXCHANGE", "order win / contract"), ("NEWS", "other")}
    assert all(i.isin == "INE018A01030" and i.category_origin == "RULE" for i in items)
    assert rep["added"] == 2 and len(rep["untracked"]) == 13  # other stocks: ISIN not confirmed
    g = session.scalar(select(NewsSourceStatus).where(NewsSourceStatus.source == "Google News"))
    assert not g.ok and "robots.txt" in g.message
    # idempotent: a second refresh adds nothing
    assert ns.refresh_news(session, make_client([]), now=NOW)["added"] == 0
    feed = ns.feed(session, now=NOW)
    assert feed["items"][0]["company"] == "Larsen & Toubro"
    assert next(c for c in feed["companies"] if c["isin"] == "INE018A01030")["unavailable"][0]["source"] == "Google News"
    assert any("No holdings disclosure" in f["note"] for f in feed["funds"])


def test_retention_prunes_old_items(session, workbook):
    import_workbook(session, workbook)
    lt = session.scalar(select(Instrument).where(Instrument.symbol == "LT"))
    session.add(NewsItem(isin="INE018A01030", company="LT", title="old", source="x",
                         source_kind="NEWS", url="https://x/old", published_at=NOW - timedelta(days=91),
                         category="other", category_origin="RULE", dedupe_key="k"))
    session.flush()
    rep = ns.refresh_news(session, make_client([]), now=NOW)
    assert rep["pruned"] == 1 and session.scalar(select(func.count()).select_from(NewsItem)) == 0


def test_network_failure_degrades_to_source_unavailable(session, workbook):
    import_workbook(session, workbook)
    def boom(req):
        raise httpx.ConnectError("offline")
    c = PoliteClient(transport=httpx.MockTransport(boom), min_interval=0, sleep=lambda _s: None)
    session.scalar(select(Instrument).where(Instrument.symbol == "LT")).isin = "INE018A01030"
    rep = ns.refresh_news(session, c, now=NOW)  # must not raise
    assert rep["added"] == 0 and rep["sources"]["NSE"]["errors"]
    assert all(not r.ok for r in session.scalars(select(NewsSourceStatus)))


def test_failed_host_is_skipped_for_a_while():
    calls = []
    def slow(req):
        calls.append(str(req.url))
        raise httpx.ReadTimeout("slow")
    t = [0.0]
    c = PoliteClient(transport=httpx.MockTransport(slow), min_interval=0, clock=lambda: t[0], sleep=lambda _s: None)
    for path in ("a.xml", "b.xml", "c.xml"):
        with pytest.raises(SourceUnavailable):
            c.get_text(f"https://slow.example/{path}")
    assert len(calls) == 2  # robots.txt timed out twice (one retry); the other feeds on that host were skipped
    t[0] = 11 * 60
    with pytest.raises(SourceUnavailable):
        c.get_text("https://slow.example/d.xml")
    assert len(calls) == 4  # tried again (with its one retry) after the cool-down


def test_robots_403_means_not_permitted():
    def h(req):
        return httpx.Response(403) if req.url.path == "/robots.txt" else httpx.Response(200, text="<rss/>")
    c = PoliteClient(transport=httpx.MockTransport(h), min_interval=0)
    with pytest.raises(SourceUnavailable, match="robots.txt"):
        c.get_text("https://bot-wall.example/rss")
