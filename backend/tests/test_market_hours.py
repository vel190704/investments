from datetime import date, datetime
from decimal import Decimal as D

import pytest

from app.calc.intraday import LiveRow, day_change, is_stale, live_totals, portfolio_series
from app.calc.market_hours import holidays_from_setting, is_trading_day, market_status
from app.timeutil import IST

HOL = {date(2026, 10, 20): "Diwali (example)"}


def at(y, m, d, hh, mm, ss=0):
    return datetime(2026 if y is None else y, m, d, hh, mm, ss, tzinfo=IST)


@pytest.mark.parametrize("now, open_, reason", [
    (at(2026, 10, 19, 9, 14, 59), False, "before open"),
    (at(2026, 10, 19, 9, 15, 0), True, "open"),          # open boundary inclusive
    (at(2026, 10, 19, 12, 0), True, "open"),
    (at(2026, 10, 19, 15, 29, 59), True, "open"),
    (at(2026, 10, 19, 15, 30, 0), False, "after close"),  # close boundary exclusive
    (at(2026, 10, 17, 11, 0), False, "weekend"),          # Saturday
    (at(2026, 10, 18, 11, 0), False, "weekend"),          # Sunday
    (at(2026, 10, 20, 11, 0), False, "holiday: Diwali (example)"),
])
def test_market_status_ist(now, open_, reason):
    st = market_status(now, HOL)
    assert (st.open, st.reason) == (open_, reason)


def test_status_uses_ist_even_for_utc_input():
    from datetime import UTC
    assert market_status(datetime(2026, 10, 19, 3, 45, tzinfo=UTC), HOL).open is True   # 09:15 IST
    assert market_status(datetime(2026, 10, 19, 10, 0, tzinfo=UTC), HOL).open is False  # 15:30 IST


def test_next_open_skips_weekend_and_holiday():
    st = market_status(at(2026, 10, 16, 16, 0), HOL)  # Friday after close; Monday 19 open
    assert st.next_open == at(2026, 10, 19, 9, 15)
    st = market_status(at(2026, 10, 19, 16, 0), HOL)  # Monday after close; Tuesday 20 is a holiday
    assert st.next_open == at(2026, 10, 21, 9, 15)
    assert not is_trading_day(date(2026, 10, 20), HOL) and is_trading_day(date(2026, 10, 21), HOL)


def test_holidays_from_setting():
    assert holidays_from_setting({"holidays": [{"date": "2026-10-20", "name": "X"}]}) == {date(2026, 10, 20): "X"}
    assert holidays_from_setting(None) == {}


NOW = at(2026, 10, 19, 11, 0)


def test_stale_after_two_poll_intervals():
    assert not is_stale(at(2026, 10, 19, 10, 58, 0), NOW, 60)   # exactly 120 s
    assert is_stale(at(2026, 10, 19, 10, 57, 59), NOW, 60)
    assert is_stale(None, NOW, 60)


def test_day_change():
    ch, pct = day_change(D("110"), D("100"))
    assert ch == D("10") and pct == D("0.1")
    assert day_change(D("110"), None) == (None, None)


def test_partial_failure_totals_use_only_fresh_quotes():
    fresh = at(2026, 10, 19, 10, 59)
    rows = [LiveRow(1, "LT", D("2"), D("3700"), fresh, D("3650")),
            LiveRow(2, "SBIN", D("10"), D("950"), at(2026, 10, 19, 10, 50), D("940")),     # stale
            LiveRow(3, "ITC", D("5"), None, None, D("260"), error="ReadTimeout"),          # failed
            LiveRow(4, "BEL", D("1"), D("400"), fresh, None)]                               # no prev close
    t = live_totals(rows, NOW, 60)
    assert t["value_paise"] == 2 * 370000 + 40000
    assert t["day_pnl_paise"] == 2 * (370000 - 365000)  # BEL has no previous close: not in day P&L
    assert t["included"] == [1, 4] and t["no_previous_close"] == ["BEL"]
    assert [(e["name"], e["reason"].split(" (")[0].split(":")[0]) for e in t["excluded"]] == [
        ("SBIN", "stale quote"), ("ITC", "quote failed")]


def test_portfolio_series_last_traded_price_never_filled_before_first_trade():
    t = lambda m: at(2026, 10, 19, 9, m)  # noqa: E731
    ticks = {1: [(t(15), D("100")), (t(17), D("101"))], 2: [(t(16), D("50"))]}
    s = portfolio_series(ticks, {1: D("1"), 2: D("2")})
    # 09:15 omitted (instrument 2 had not traded yet); 09:16 uses 1's 09:15 price; 09:17 uses 2's 09:16 price
    assert s == [{"ts": t(16).isoformat(), "value_paise": 10000 + 10000},
                 {"ts": t(17).isoformat(), "value_paise": 10100 + 10000}]
    assert portfolio_series({}, {1: D("1")}) == []


def test_parse_recorded_yfinance_download():
    """Recorded real response (2026-10-16 session, trimmed): 3 tickers, 1-minute bars, IST index."""
    from pathlib import Path

    import pandas as pd

    from app.market.intraday import parse_download

    df = pd.read_csv(Path(__file__).parent / "fixtures" / "yf_download_1m_3tickers.csv", header=[0, 1], index_col=0)
    df.index = pd.to_datetime(df.index)
    out = parse_download(df, ["LT.NS", "SBIN.NS", "MOSCHIP.NS", "NOPE.NS"])
    lt = out["LT.NS"]
    assert len(lt) == int(df[("LT.NS", "Close")].notna().sum())  # NaN minutes (no trade) skipped, never filled
    assert lt[0][0].isoformat() == "2026-10-16T03:45:00+00:00"  # 09:15 IST in UTC
    assert all(isinstance(p, D) and p > 0 for _, p in lt) and lt == sorted(lt)
    assert out["NOPE.NS"] == "no intraday data returned"
    assert len(out["MOSCHIP.NS"]) == int(df[("MOSCHIP.NS", "Close")].notna().sum())


def test_fetch_intraday_maps_symbols_and_reports_missing():
    import pandas as pd

    from app.market.intraday import fetch_intraday

    idx = pd.DatetimeIndex(["2026-10-19 09:15:00+05:30", "2026-10-19 09:16:00+05:30"])
    df = pd.DataFrame({("LT.NS", "Close"): [3700.0, float("nan")], ("ITC.NS", "Close"): [float("nan")] * 2}, index=idx)
    out = fetch_intraday(["LT", "ITC", "BEL"], download=lambda t: df)
    assert out["LT"] == [(datetime(2026, 10, 19, 3, 45, tzinfo=__import__("datetime").UTC), D("3700.0"))]
    assert out["ITC"] == "no trades in the returned bars" and out["BEL"] == "no intraday data returned"
