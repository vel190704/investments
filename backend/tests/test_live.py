"""Live intraday prices: polling with mocked quotes, market hours, stale badge, retention, partial failures."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import func, select

from app.importer.run import import_workbook
from app.market.base import Quote
from app.market.service import store_quote
from app.models import Instrument, IntradayTick, PriceQuote
from app.services import live
from app.services import settings as st
from app.services.snapshots import take_snapshot
from app.timeutil import IST

OPEN_NOW = datetime(2026, 10, 19, 11, 0, tzinfo=IST)     # Monday 11:00 IST
CLOSED_NOW = datetime(2026, 10, 19, 16, 0, tzinfo=IST)   # Monday after close
SAT = datetime(2026, 10, 17, 11, 0, tzinfo=IST)


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    monkeypatch.setattr(live, "STATE", live.PollerState())


def book(session, workbook):
    import_workbook(session, workbook)
    for i in session.scalars(select(Instrument)):
        if i.symbol:  # previous session's end-of-day close (Friday)
            store_quote(session, i.id, Quote(D("100"), date(2026, 10, 16), "t", i.symbol))
        else:
            i.scheme_code = "1"
            store_quote(session, i.id, Quote(D("50"), date(2026, 10, 16), "t", "1"))
    session.flush()


def fake_fetch(prices=None, fail=(), calls=None):
    """bars at 10:58 and 10:59 IST for every symbol; `fail` symbols return an error."""
    def fetch(symbols):
        if calls is not None:
            calls.append(list(symbols))
        out = {}
        for sym in symbols:
            if sym in fail:
                out[sym] = "no intraday data returned"
            else:
                p = D((prices or {}).get(sym, "110"))
                out[sym] = [(datetime(2026, 10, 19, 5, 28, tzinfo=UTC), p - 1), (datetime(2026, 10, 19, 5, 29, tzinfo=UTC), p)]
        return out
    return fetch


def ticks(session):
    return session.scalar(select(func.count()).select_from(IntradayTick))


def test_poll_in_market_hours_stores_real_bars_for_stocks_and_etfs_only(session, workbook):
    book(session, workbook)
    calls = []
    cycle = live.poll_cycle(session, OPEN_NOW, fetch=fake_fetch(calls=calls))
    assert cycle["ran"] and cycle["requested"] == 16 and cycle["succeeded"] == 16 and cycle["failed"] == 0
    assert len(calls) == 1 and len(calls[0]) == 16  # one batched request; the 3 mutual funds are not polled
    assert ticks(session) == 32
    again = live.poll_cycle(session, OPEN_NOW + timedelta(seconds=60), fetch=fake_fetch())
    assert again["ticks_added"] == 0 and ticks(session) == 32  # same bars are not duplicated


def test_ticks_never_feed_eod_quotes_or_snapshots(session, workbook):
    book(session, workbook)
    before_quotes = session.scalar(select(func.count()).select_from(PriceQuote))
    snap_before = take_snapshot(session, on_date=date(2026, 10, 19))["total_value_paise"]
    live.poll_cycle(session, OPEN_NOW, fetch=fake_fetch(prices={"LT": "9999"}))
    assert session.scalar(select(func.count()).select_from(PriceQuote)) == before_quotes
    assert take_snapshot(session, on_date=date(2026, 10, 19))["total_value_paise"] == snap_before


def test_no_writes_outside_market_hours_except_manual(session, workbook):
    book(session, workbook)
    st.put(session, "live", {"enabled": True})
    live.mark_viewer(0.0)
    for now in (CLOSED_NOW, SAT, datetime(2026, 10, 19, 9, 14, 59, tzinfo=IST)):
        assert live.poll_cycle(session, now, fetch=fake_fetch())["ran"] is False
        assert live.scheduler_tick(session, now, mono=1.0, fetch=fake_fetch())["ran"] is False
    st.put(session, "market_holidays", {"holidays": [{"date": "2026-10-19", "name": "Test holiday"}]})
    res = live.scheduler_tick(session, OPEN_NOW, mono=1.0, fetch=fake_fetch())
    assert res == {"ran": False, "reason": "market closed (holiday: Test holiday)"}
    assert ticks(session) == 0
    assert live.poll_cycle(session, CLOSED_NOW, manual=True, fetch=fake_fetch())["ran"] is True  # explicit refresh
    assert ticks(session) == 32


def test_scheduler_requires_a_viewer_and_respects_interval(session, workbook):
    """The poller is shared: it runs while any user with live prices on is looking (GET /live marks a viewer only
    when that user's toggle is on; see test_live_route_marks_viewer_only_when_enabled)."""
    book(session, workbook)
    f = fake_fetch()
    assert live.scheduler_tick(session, OPEN_NOW, mono=100.0, fetch=f)["reason"] == "nobody is viewing live prices"
    live.mark_viewer(100.0)
    assert live.scheduler_tick(session, OPEN_NOW, mono=100.0, fetch=f)["ran"] is True
    live.STATE.last_poll_mono = 100.0  # the poll above used the real clock; pin it for the interval checks
    assert live.scheduler_tick(session, OPEN_NOW, mono=130.0, fetch=f)["reason"] == "next poll in 30s"
    assert live.scheduler_tick(session, OPEN_NOW, mono=160.0, fetch=f)["ran"] is True
    live.STATE.last_poll_mono = 160.0
    assert live.scheduler_tick(session, OPEN_NOW, mono=160.0 + 400, fetch=f)["reason"] == "nobody is viewing live prices"


def test_backoff_after_failed_cycles(session, workbook):
    book(session, workbook)
    st.put(session, "live", {"enabled": True})

    def broken(symbols):
        raise TimeoutError("read timed out")

    c = live.poll_cycle(session, OPEN_NOW, fetch=broken)
    assert c["succeeded"] == 0 and c["failed"] == 16 and c["next_interval_s"] == 120
    c = live.poll_cycle(session, OPEN_NOW, fetch=broken)
    assert c["next_interval_s"] == 240
    live.mark_viewer(1000.0)
    live.STATE.last_poll_mono = 1000.0
    assert live.scheduler_tick(session, OPEN_NOW, mono=1000.0 + 200, fetch=broken)["reason"] == "next poll in 40s"
    c = live.poll_cycle(session, OPEN_NOW, fetch=fake_fetch())
    assert c["next_interval_s"] == 60  # reset after a successful cycle


def test_manual_refresh_is_rate_limited(session, workbook):
    book(session, workbook)
    assert live.poll_cycle(session, CLOSED_NOW, manual=True, fetch=fake_fetch())["ran"] is True
    r = live.poll_cycle(session, CLOSED_NOW, manual=True, fetch=fake_fetch())
    assert r["ran"] is False and r["reason"].startswith("rate limited")


def test_retention_keeps_14_days(session, workbook):
    book(session, workbook)
    lt = session.scalar(select(Instrument).where(Instrument.symbol == "LT"))
    old = datetime(2026, 10, 4, 5, 0, tzinfo=UTC)    # 15 days before OPEN_NOW
    kept = datetime(2026, 10, 6, 5, 0, tzinfo=UTC)   # 13 days before
    session.add_all([IntradayTick(security_id=lt.security_id, ts=old, price=D("1"), source="t"),
                     IntradayTick(security_id=lt.security_id, ts=kept, price=D("1"), source="t")])
    session.flush()
    assert live.prune(session, OPEN_NOW) == 1
    assert [t.ts.replace(tzinfo=UTC) for t in session.scalars(select(IntradayTick))] == [kept]


def test_view_partial_failure_stale_badge_and_totals(session, workbook):
    book(session, workbook)
    st.put(session, "live", {"enabled": True})
    live.poll_cycle(session, OPEN_NOW, fetch=fake_fetch(prices={"LT": "120"}, fail=("ITC",)))
    v = live.live_view(session, OPEN_NOW)
    assert v["market"]["open"] and v["market"]["label"] == "Market open"
    rows = {r["symbol"]: r for r in v["rows"]}
    assert rows["LT"]["price"] == "120" and rows["LT"]["day_change"] == "20" and rows["LT"]["day_change_pct"] == "0.2"
    assert rows["LT"]["stale"] is False and rows["LT"]["prev_close_date"] == "2026-10-16"
    assert rows["LT"]["source"].startswith("Yahoo Finance") and rows["LT"]["quote_ts"].startswith("2026-10-19T05:29")
    assert rows["ITC"]["error"] == "no intraday data returned" and rows["ITC"]["price"] is None
    t = v["totals"]
    assert [e["name"] for e in t["excluded"]] == ["ITC"] and t["excluded"][0]["reason"].startswith("quote failed")
    assert len(t["included"]) == 15
    # 15 holdings x 1 share each; LT at 120, the rest at 110, previous closes 100
    assert t["value_paise"] == 12000 + 14 * 11000 and t["day_pnl_paise"] == 2000 + 14 * 1000
    assert v["funds"]["count"] == 3 and "not polled" in v["funds"]["note"]
    assert v["series"] and v["series"][-1]["value_paise"] == t["value_paise"]
    later = live.live_view(session, OPEN_NOW + timedelta(minutes=5))  # 10:59 quotes are now > 2 x 60 s old
    assert all(r["stale"] for r in later["rows"]) and later["totals"]["value_paise"] == 0
    assert all(e["reason"].startswith(("stale quote", "quote failed")) for e in later["totals"]["excluded"])


def test_view_when_closed_shows_market_closed_and_last_close(session, workbook):
    book(session, workbook)
    v = live.live_view(session, SAT)
    assert v["market"] == {**v["market"], "open": False, "label": "Market closed", "reason": "weekend"}
    assert v["totals"] is None and v["market"]["next_open"].startswith("2026-10-19T09:15")
    lt = next(r for r in v["rows"] if r["symbol"] == "LT")
    assert lt["last_close"] == "100" and lt["last_close_date"] == "2026-10-16"
    assert v["holidays_entered"] == 0 and "verify" in v["holiday_note"]


def test_settings_validation():
    with pytest.raises(st.SettingsError):
        st.validate("live_platform", {"poll_seconds": 10})
    with pytest.raises(st.SettingsError):
        st.validate("live_platform", {"poll_seconds": 301})
    assert st.validate("live_platform", {"poll_seconds": "30"}) == {"poll_seconds": 30}
    assert st.validate("live", {"enabled": 1, "poll_seconds": "30"}) == {"enabled": True}  # per user: on/off only
    assert "live_platform" in st.PLATFORM_SECTIONS and "market_holidays" in st.PLATFORM_SECTIONS
    with pytest.raises(st.SettingsError):
        st.validate("market_holidays", {"holidays": [{"date": "2026-13-01", "name": "x"}]})
    with pytest.raises(st.SettingsError):
        st.validate("market_holidays", {"holidays": [{"date": "2026-10-20", "name": ""}]})
    assert st.validate("market_holidays", {"holidays": [{"date": "2026-11-09", "name": "B"}, {"date": "2026-10-20", "name": "A"}]}) == \
        {"holidays": [{"date": "2026-10-20", "name": "A"}, {"date": "2026-11-09", "name": "B"}]}
    assert st.DEFAULTS["live"] == {"enabled": False} and st.DEFAULTS["market_holidays"] == {"holidays": []}


def test_live_route_marks_viewer_only_when_enabled(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app import db
    from app.main import app

    db.configure(f"sqlite:///{tmp_path / 'live.db'}")
    with TestClient(app) as c:
        r = c.get("/api/live")
        assert r.status_code == 200 and r.json()["rows"] == [] and live.STATE.last_viewer_mono is None
        c.put("/api/settings/live", json={"enabled": True})
        c.get("/api/live")
        assert live.STATE.last_viewer_mono is not None


def test_tick_queries_are_timezone_safe(session, workbook):
    """Regression: SQLite drops the zone without converting; an IST bound value once missed every UTC tick."""
    from app import repository as repo

    book(session, workbook)
    live.poll_cycle(session, OPEN_NOW, fetch=fake_fetch())
    session_start_ist = datetime(2026, 10, 19, 9, 15, tzinfo=IST)
    assert len(repo.ticks_since(session, session_start_ist)) == 32
    assert repo.ticks_since(session, datetime(2026, 10, 19, 11, 0, tzinfo=IST)) == []  # 05:30 UTC > 05:29 bars
    assert repo.prune_ticks(session, datetime(2026, 10, 19, 10, 59, tzinfo=IST)) == 16  # the 10:58 IST bars


def test_unpriced_funds_are_data_unavailable_not_zero(session, workbook):
    import_workbook(session, workbook)  # no NAVs stored
    v = live.live_view(session, SAT)
    assert v["funds"]["value_paise"] is None and len(v["funds"]["unpriced"]) == 3
