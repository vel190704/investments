"""News & announcements: tracked companies, refresh, feed, dashboard widget."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.calc import news as nc
from app.models import NewsItem, NewsSourceStatus
from app.net.polite import PoliteClient, SourceUnavailable, default_client
from app.news import sources as src
from app.services import settings as st
from app.timeutil import as_utc, utcnow

RETENTION_DAYS = 90
FUND_TOP_N = 5
NOT_CONFIRMED = "ISIN not confirmed — confirm it on Mappings to track news for this holding"


@dataclass
class Tracked:
    isin: str
    name: str
    symbol: str | None
    instrument_id: int | None  # direct holding, if any
    exposure: float  # total % of portfolio (direct + via funds), 0..1
    via_funds: list[str] = field(default_factory=list)


def _nse_symbols_by_isin() -> dict[str, tuple[str, str]]:
    """ISIN -> (symbol, company) from the cached NSE equity list (official)."""
    from app.config import get_settings
    from app.resolve.sources import parse_nse_equity

    path = get_settings().cache_dir / "EQUITY_L.csv"
    if not path.exists():
        return {}
    return {sec.isin: (sec.symbol, sec.name) for sec in parse_nse_equity(path.read_text(encoding="utf-8")).values()}


def tracked_companies(s: Session) -> tuple[list[Tracked], list[dict], list[dict]]:
    """(tracked companies, direct holdings that can't be tracked, fund coverage notes)."""
    from app.calc.lookthrough import company_exposure, is_equity_isin
    from app.services.lookthrough import inputs

    rows, priced, total, direct, funds = inputs(s)
    exposure = {c["isin"]: c for c in company_exposure(direct, funds, total)["companies"]}
    nse = _nse_symbols_by_isin()
    out: dict[str, Tracked] = {}
    untracked = []
    for r in rows:
        if r.inst.asset_type != "STOCK":
            continue
        if not is_equity_isin(r.inst.isin):
            untracked.append({"instrument_id": r.inst.id, "name": r.inst.symbol or r.inst.name, "reason": NOT_CONFIRMED})
            continue
        e = exposure.get(r.inst.isin)
        out[r.inst.isin] = Tracked(r.inst.isin, r.inst.name, r.inst.symbol, r.inst.id,
                                   float(e["total_pct"]) if e and e["total_pct"] else 0.0)
    fund_notes = []
    for f in funds:
        if not f.rows:
            fund_notes.append({"fund": f.name, "companies": [], "note": "No holdings disclosure uploaded — fund news is "
                                                                         "not shown (only news for its holdings would be)."})
            continue
        top = sorted([c for c in exposure.values() if any(v["instrument_id"] == f.instrument_id for v in c["via"])],
                     key=lambda c: -c["total_paise"])[:FUND_TOP_N]
        names = []
        for c in top:
            sym, nse_name = nse.get(c["isin"], (None, c["name"]))
            t = out.get(c["isin"]) or Tracked(c["isin"], nse_name or c["name"], sym, None,
                                             float(c["total_pct"]) if c["total_pct"] else 0.0)
            t.via_funds.append(f.name)
            out[c["isin"]] = t
            names.append(t.name)
        fund_notes.append({"fund": f.name, "companies": names, "note": f"News for its top {len(names)} holdings by "
                                                                      "your look-through exposure."})
    return sorted(out.values(), key=lambda t: -t.exposure), untracked, fund_notes


def _status(s: Session, source: str, isin: str | None, ok: bool, message: str) -> None:
    row = s.scalar(select(NewsSourceStatus).where(NewsSourceStatus.source == source, NewsSourceStatus.isin == isin))
    if row is None:
        row = NewsSourceStatus(source=source, isin=isin)
        s.add(row)
    row.ok, row.message, row.checked_at = ok, message, utcnow()


def _store(s: Session, t: Tracked, item: src.RawItem, report: dict) -> None:
    if s.scalar(select(NewsItem.id).where(NewsItem.url == item.url)):
        report["already_stored"] += 1
        return
    recent = [(n.title, as_utc(n.published_at)) for n in s.scalars(
        select(NewsItem).where(NewsItem.isin == t.isin,
                               NewsItem.published_at >= item.published_at - timedelta(days=3)))]
    if nc.is_near_duplicate(item.title, item.published_at, recent):
        report["duplicates"] += 1
        return
    s.add(NewsItem(isin=t.isin, instrument_id=t.instrument_id, company=t.name, title=item.title, source=item.source,
                   source_kind=item.source_kind, url=item.url, published_at=item.published_at,
                   category=nc.categorize(item.title, item.summary), category_origin="RULE", summary=item.summary,
                   dedupe_key=nc.dedupe_key(item.title)))
    s.flush()
    report["added"] += 1


def refresh_news(s: Session, client: PoliteClient | None = None, now: datetime | None = None) -> dict:
    client = client or default_client()
    now = now or utcnow()
    tracked, untracked, _ = tracked_companies(s)
    report = {"tracked": len(tracked), "added": 0, "duplicates": 0, "already_stored": 0, "pruned": 0,
              "sources": {}, "untracked": untracked}
    cutoff = now - timedelta(days=RETENTION_DAYS)

    # 1) NSE official announcement feeds — matched by NSE symbol from the filing link
    by_symbol = {t.symbol.upper(): t for t in tracked if t.symbol}
    items, errors = src.fetch_nse(client)
    for name in src.NSE_FEEDS:
        _status(s, name, None, name not in errors, errors.get(name, "ok"))
    for it in items:
        t = by_symbol.get((it.symbol_hint or "").upper())
        if t and it.published_at >= cutoff:
            _store(s, t, it, report)
    report["sources"]["NSE"] = {"items": len(items), "errors": errors}

    # 2) Publisher market feeds — matched by company name / NSE symbol in the headline
    patterns = {t.isin: nc.company_patterns(t.name, t.symbol) for t in tracked}
    for feed in (st.get(s, "news") or {}).get("feeds", src.DEFAULT_PUBLISHER_FEEDS):
        try:
            feed_items = src.fetch_publisher(client, feed["name"], feed["url"])
            _status(s, feed["name"], None, True, f"ok ({len(feed_items)} items)")
        except (SourceUnavailable, ValueError) as e:
            _status(s, feed["name"], None, False, str(e))
            report["sources"][feed["name"]] = {"error": str(e)}
            continue
        matched = 0
        for it in feed_items:
            hits = [t for t in tracked if nc.mentions(it.title, patterns[t.isin])]
            if hits and it.published_at >= cutoff:
                _store(s, max(hits, key=lambda t: t.exposure), it, report)  # one row per URL: most-exposed company
                matched += 1
        report["sources"][feed["name"]] = {"items": len(feed_items), "matched": matched}

    # 3) Google News RSS (requested) — refused by robots.txt; recorded per holding as unavailable
    for t in tracked:
        try:
            for it in src.fetch_google_news(client, t.name, t.symbol):
                if it.published_at >= cutoff:
                    _store(s, t, it, report)
            _status(s, "Google News", t.isin, True, "ok")
        except (SourceUnavailable, ValueError) as e:
            _status(s, "Google News", t.isin, False, str(e))
            report["sources"]["Google News"] = {"error": str(e)}
            if "robots.txt" in str(e):  # same answer for every query; don't ask again this run
                for rest in tracked:
                    _status(s, "Google News", rest.isin, False, str(e))
                break

    report["pruned"] = s.execute(delete(NewsItem).where(NewsItem.published_at < cutoff)
                                 .execution_options(synchronize_session="fetch")).rowcount or 0
    s.flush()
    return report


def _item_dict(n: NewsItem, t: Tracked | None) -> dict:
    p = as_utc(n.published_at)
    return {"id": n.id, "isin": n.isin, "company": n.company, "instrument_id": n.instrument_id, "title": n.title,
            "source": n.source, "source_kind": n.source_kind, "url": n.url, "published_at": p.isoformat(),
            "published_ts": p.timestamp(), "fetched_at": as_utc(n.fetched_at).isoformat(), "category": n.category,
            "category_origin": n.category_origin, "summary": n.summary,
            "exposure": t.exposure if t else 0.0, "via_funds": t.via_funds if t else []}


def feed(s: Session, isin: str | None = None, category: str | None = None, days: int = 30,
         now: datetime | None = None) -> dict:
    now = now or utcnow()
    tracked, untracked, fund_notes = tracked_companies(s)
    by_isin = {t.isin: t for t in tracked}
    q = select(NewsItem).where(NewsItem.published_at >= now - timedelta(days=days))
    if isin:
        q = q.where(NewsItem.isin == isin)
    if category:
        q = q.where(NewsItem.category == category)
    items = [_item_dict(n, by_isin.get(n.isin)) for n in s.scalars(q)]
    items = nc.rank_feed(items, {k: t.exposure for k, t in by_isin.items()})
    statuses = {}
    for row in s.scalars(select(NewsSourceStatus)):
        if row.isin is None:
            statuses.setdefault("_sources", []).append({"source": row.source, "ok": row.ok, "message": row.message,
                                                        "checked_at": as_utc(row.checked_at).isoformat()})
        elif not row.ok:
            statuses.setdefault(row.isin, []).append({"source": row.source, "message": row.message})
    return {
        "items": items,
        "companies": [{"isin": t.isin, "name": t.name, "symbol": t.symbol, "exposure": t.exposure,
                       "direct": t.instrument_id is not None, "via_funds": t.via_funds,
                       "unavailable": statuses.get(t.isin, [])} for t in tracked],
        "untracked": untracked, "funds": fund_notes, "sources": statuses.get("_sources", []),
        "categories": nc.CATEGORIES,
        "basis": "Sorted by your total exposure to the company (direct + through funds), then newest first. "
                 "Titles and summaries are the source's own text.",
    }


def recent(s: Session, days: int = 7, limit: int = 8) -> list[dict]:
    return feed(s, days=days)["items"][:limit]
