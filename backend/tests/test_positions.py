from datetime import date
from decimal import Decimal as D

import pytest

from app.calc.positions import OversellError, TxnInput, replay


def t(d, typ, q, amt, ch=0, seq=0):
    return TxnInput(date.fromisoformat(d), typ, D(q) if q is not None else None, amt, ch, seq)


def test_opening_counts_toward_quantity_and_invested():
    p = replay([t("2026-10-03", "OPENING", "10.945", 250000)])
    assert p.quantity == D("10.945")
    assert p.invested_paise == 250000
    assert p.opening_quantity == D("10.945") and p.dated_quantity == 0
    assert not p.has_dated_buys
    assert p.avg_cost.quantize(D("0.0001")) == D("228.4148")


def test_average_cost_buys_and_charges():
    p = replay([t("2024-01-01", "BUY", 10, 100000, 2000), t("2024-02-01", "SIP", 10, 120000)])
    assert p.quantity == 20
    assert p.invested_paise == 222000
    assert p.avg_cost == D("111")


def test_sell_reduces_cost_pro_rata_and_books_realised():
    p = replay([t("2024-01-01", "BUY", 10, 100000), t("2024-01-02", "BUY", 10, 200000),
                t("2024-06-01", "SELL", 5, 100000, 1000)])
    # avg cost 150/unit -> 5 units cost 750; proceeds 1000 - 10 charges = 990 -> realised 240
    assert p.quantity == 15
    assert p.invested_paise == 225000
    assert p.realised_paise == D(24000)


def test_sell_entire_position_closes_it():
    p = replay([t("2024-01-01", "BUY", 3, 30000), t("2024-02-01", "SELL", 3, 36000)])
    assert not p.is_open and p.invested_paise == 0 and p.realised_paise == 6000


def test_oversell_raises():
    with pytest.raises(OversellError):
        replay([t("2024-01-01", "BUY", 1, 100), t("2024-01-02", "SELL", 2, 300)])


def test_dividend_does_not_change_quantity_or_cost():
    p = replay([t("2024-01-01", "BUY", 1, 100000), t("2024-03-01", "DIVIDEND", None, 1500)])
    assert p.quantity == 1 and p.invested_paise == 100000 and p.dividends_paise == 1500


def test_same_day_ordering_opening_before_sell():
    p = replay([t("2024-01-01", "SELL", 1, 500), t("2024-01-01", "OPENING", 2, 800)])
    assert p.quantity == 1


def test_mixed_opening_and_dated_units_tracked_for_xirr():
    p = replay([t("2024-01-01", "OPENING", 10, 100000), t("2024-06-01", "BUY", 10, 150000),
                t("2024-09-01", "SELL", 4, 80000)])
    # sell is split 50/50 between opening and dated units
    assert p.opening_quantity == 8 and p.dated_quantity == 8
    assert p.xirr_flows == [(date(2024, 6, 1), D(-150000)), (date(2024, 9, 1), D(40000))]
