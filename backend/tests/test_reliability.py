from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

import pandas as pd
from sqlalchemy import select

from app.calc.lookthrough import is_equity_isin
from app.importer.run import import_workbook
from app.market.base import Quote
from app.market.service import store_quote
from app.market.yfinance_provider import quote_from_history
from app.models import Instrument, PortfolioSnapshot, SnapshotGap, SourceEvent
from app.news.sources import parse_rss
from app.resolve.sources import parse_amfi, parse_nse_index_list
from app.services.catchup import catch_up, missed_dates
from app.services.snapshots import series, take_snapshot
from app.services.source_health import record, summary

FIX = Path(__file__).parent / "fixtures"


# ---- parser regressions on recorded real responses (2026-10-17) ----
def test_recorded_yfinance_daily_bars():
    df = pd.read_csv(FIX / "yf_LT_daily.csv", index_col="Date", parse_dates=True)
    q = quote_from_history(df, "LT.NS")
    last = df.dropna().iloc[-1]
    assert q.price == D(repr(round(float(last["Close"]), 2))) and q.previous_close is not None
    assert q.price_date == df.index[-1].date()


def test_recorded_amfi_excerpt():
    s = parse_amfi((FIX / "amfi_navall_excerpt.txt").read_text())
    assert {"118989", "120620", "148745"} <= set(s)
    assert s["118989"].category == "Open Ended — Equity Scheme - Mid Cap Fund"
    assert s["120620"].option == "Cumulative" and s["120620"].nav and s["120620"].nav_date


def test_recorded_nse_index_list():
    rows = {r.symbol: r for r in parse_nse_index_list((FIX / "nse_totalmarket_excerpt.csv").read_text(), "Nifty Total Market")}
    assert rows["LT"].industry == "Construction" and rows["LT"].isin == "INE018A01030"
    assert all(is_equity_isin(r.isin) for r in rows.values())


def test_recorded_nse_announcements():
    items = parse_rss((FIX / "nse_announcements_excerpt.xml").read_text(), "NSE announcements", "EXCHANGE")
    assert len(items) == 5 and all(i.symbol_hint and i.published_at.tzinfo for i in items)
    assert items[-1].symbol_hint == "SAIIM"  # /corporate/xbrl/<SYMBOL>_... links (found via this recorded response)


# ---- source health ----
def test_source_health_records_and_summarises(session):
    record(session, "yfinance prices", True, "16 ok")
    record(session, "yfinance prices", False, "Source unavailable (timeout)")
    record(session, "AMFI NAVAll", False, "HTTP 503")
    out = {r["source"]: r for r in summary(session)}
    y = out["yfinance prices"]
    assert y["last_success"] and y["last_failure"] and y["last_error"] == "Source unavailable (timeout)"
    assert y["history"][-1]["status"] == "mixed" and len(y["history"]) == 30
    assert out["AMFI NAVAll"]["history"][-1]["status"] == "failed"
    assert out["LLM provider"]["history"][-1]["status"] == "none" and out["LLM provider"]["last_success"] is None


def test_refresh_records_source_events(session, workbook):
    from app.market.base import FetchError
    from app.market.service import refresh_prices

    import_workbook(session, workbook)

    class P:
        name = "Yahoo Finance (yfinance)"

        def supports(self, r):
            return r.asset_type != "MF"

        def fetch(self, refs):
            return {r.instrument_id: FetchError("down") for r in refs}
    refresh_prices(session, providers=[P()])
    ev = session.scalars(select(SourceEvent).where(SourceEvent.source == "yfinance prices")).all()
    assert len(ev) == 1 and not ev[0].ok


# ---- startup catch-up ----
def test_missed_dates():
    assert missed_dates(None, date(2026, 10, 17)) == []
    assert missed_dates(date(2026, 10, 16), date(2026, 10, 17)) == []
    assert missed_dates(date(2026, 10, 13), date(2026, 10, 17)) == [date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 16)]


def test_catch_up_records_gaps_and_never_backfills(session, workbook):
    import_workbook(session, workbook)
    lt = session.scalar(select(Instrument).where(Instrument.symbol == "LT"))
    store_quote(session, lt.id, Quote(D("3700"), date(2026, 10, 10), "t", "LT"))
    take_snapshot(session, on_date=date(2026, 10, 10))

    def fake_refresh(s):
        return {"ok_count": 1, "error_count": 0, "snapshot": take_snapshot(s, trigger="startup", on_date=date(2026, 10, 14))}
    res = catch_up(session, date(2026, 10, 14), refresh=fake_refresh)
    assert res["gaps_recorded"] == ["2026-10-11", "2026-10-12", "2026-10-13"]
    snaps = [p.snapshot_date for p in session.scalars(select(PortfolioSnapshot))]
    assert sorted(snaps) == [date(2026, 10, 10), date(2026, 10, 14)]  # no fake snapshots for the gap
    ser = series(session)
    gap_pts = [p for p in ser["points"] if p["gap"]]
    assert [p["date"] for p in gap_pts] == ["2026-10-11", "2026-10-12", "2026-10-13"]
    assert all(p["value_paise"] is None for p in gap_pts)
    assert catch_up(session, date(2026, 10, 14), refresh=fake_refresh)["ran"] is False  # today's snapshot exists
    assert len(session.scalars(select(SnapshotGap)).all()) == 3
