from datetime import date, datetime
from decimal import Decimal as D

import pandas as pd
from sqlalchemy import select

from app.importer.run import import_workbook
from app.market.amfi_provider import AmfiNavProvider
from app.market.base import FetchError, InstrumentRef, Quote
from app.market.service import refresh_prices
from app.market.yfinance_provider import quote_from_history
from app.models import Instrument, PriceQuote
from app.resolve.sources import parse_amfi
from tests.test_resolve import AMFI


def test_quote_from_history_drops_zero_volume_holiday_bar():
    idx = pd.to_datetime(["2026-09-30", "2026-10-01", "2026-10-02"])
    df = pd.DataFrame({"Close": [457.47, 455.10, 455.10], "Volume": [1000, 900, 0]}, index=idx)
    q = quote_from_history(df, "HNGSNGBEES.NS")
    assert q.price == D("455.1") and q.price_date == date(2026, 10, 1)
    assert q.previous_close == D("457.47") and q.previous_date == date(2026, 9, 30)


def test_quote_from_empty_history_is_error():
    assert isinstance(quote_from_history(pd.DataFrame(), "X.NS"), FetchError)


def test_amfi_provider_requires_confirmed_scheme_code():
    p = AmfiNavProvider(loader=lambda max_age_hours: (parse_amfi(AMFI), datetime.now()))
    out = p.fetch([InstrumentRef(1, "MF", None, None, "x"), InstrumentRef(2, "MF", None, "148745", "y"),
                   InstrumentRef(3, "MF", None, "999999", "z")])
    assert isinstance(out[1], FetchError) and "not confirmed" in out[1].message
    assert out[2].price == D("20.2442") and out[2].source == "AMFI NAVAll.txt"
    assert isinstance(out[3], FetchError)


class FakeProvider:
    name = "fake"

    def __init__(self, prices, fail=()):
        self.prices, self.fail = prices, set(fail)

    def supports(self, ref):
        return True

    def fetch(self, refs):
        out = {}
        for r in refs:
            key = r.symbol or r.name
            if key in self.fail:
                out[r.instrument_id] = FetchError("boom")
            elif key in self.prices:
                out[r.instrument_id] = Quote(D(self.prices[key]), date(2026, 10, 1), "fake", key, D("100"))
        return out


def test_refresh_survives_failures_and_caches_quotes(session, workbook):
    import_workbook(session, workbook)
    res = refresh_prices(session, providers=[FakeProvider({"LT": "3693.4", "ITC": "260"}, fail={"SBIN"})])
    assert res["ok_count"] == 2 and res["error_count"] == 17
    assert any(r.get("error") == "boom" for r in res["results"])
    assert len(session.scalars(select(PriceQuote)).all()) == 2
    # refreshing the same market date updates rather than duplicates
    refresh_prices(session, providers=[FakeProvider({"LT": "3700"})])
    lt = session.scalar(select(Instrument).where(Instrument.symbol == "LT"))
    qs = session.scalars(select(PriceQuote).where(PriceQuote.instrument_id == lt.id)).all()
    assert len(qs) == 1 and qs[0].price == D("3700")


def test_amfi_previous_nav_comes_from_cache(session, workbook):
    import_workbook(session, workbook)
    kotak = session.scalar(select(Instrument).where(Instrument.name.like("Kotak%")))
    kotak.scheme_code = "148745"
    from app.market.service import store_quote
    store_quote(session, kotak.id, Quote(D("20.10"), date(2026, 9, 30), "AMFI NAVAll.txt", "148745"))
    session.flush()
    row = store_quote(session, kotak.id, Quote(D("20.2442"), date(2026, 10, 1), "AMFI NAVAll.txt", "148745"))
    assert row.previous_close == D("20.10") and row.previous_date == date(2026, 9, 30)
