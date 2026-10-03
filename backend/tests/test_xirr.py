from datetime import date
from decimal import Decimal as D

import pytest

from app.calc.positions import TxnInput, replay
from app.calc.xirr import NA_NEEDS_DATED, portfolio_xirr, position_xirr, xirr


def test_xirr_matches_excel_reference():
    # Microsoft's documented XIRR example -> 0.373362535
    flows = [(date(2008, 1, 1), -10000), (date(2008, 3, 1), 2750), (date(2008, 10, 30), 4250),
             (date(2009, 2, 15), 3250), (date(2009, 4, 1), 2750)]
    assert xirr(flows) == pytest.approx(0.373362535, abs=1e-8)


def test_xirr_simple_one_year_doubling():
    assert xirr([(date(2023, 1, 1), -100), (date(2024, 1, 1), 200)]) == pytest.approx(1.0, abs=1e-6)


def test_xirr_leap_year_uses_actual_365():
    # 366 days: (2)^(365/366) - 1, as Excel computes
    assert xirr([(date(2024, 1, 1), -100), (date(2025, 1, 1), 200)]) == pytest.approx(2 ** (365 / 366) - 1, abs=1e-9)


def test_xirr_negative_return():
    assert xirr([(date(2023, 1, 1), -1000), (date(2024, 1, 1), 900)]) == pytest.approx(-0.1, abs=1e-6)


def test_xirr_needs_both_signs():
    assert xirr([(date(2023, 1, 1), -100), (date(2024, 1, 1), -50)]) is None
    assert xirr([(date(2023, 1, 1), -100)]) is None


def test_opening_only_instrument_is_na():
    p = replay([TxnInput(date(2026, 10, 3), "OPENING", D(1), 376800)])
    r = position_xirr(p, D("3693.40"), date(2026, 10, 3))
    assert r.rate is None and r.note == NA_NEEDS_DATED == "N/A (needs dated transactions)"


def test_opening_excluded_from_xirr_with_dated_buy():
    """OPENING units and money are excluded; only the dated BUY and its units count."""
    txns = [TxnInput(date(2023, 1, 1), "OPENING", D(100), 1_000_000),  # 100 units @ ₹100 (excluded)
            TxnInput(date(2025, 1, 1), "BUY", D(10), 100_000)]          # 10 units @ ₹100 on a real date
    p = replay(txns)
    r = position_xirr(p, D("110"), date(2026, 1, 1))  # 365 days later  # 10 dated units now worth ₹1,100
    assert r.rate == pytest.approx(0.10, abs=1e-6)
    # Had OPENING been included as a cashflow, the answer would be different:
    wrong = xirr([(date(2023, 1, 1), -1_000_000), (date(2025, 1, 1), -100_000), (date(2026, 1, 1), 1_210_000)])
    assert wrong != pytest.approx(0.10, abs=1e-3)


def test_portfolio_xirr_na_when_all_opening():
    p = replay([TxnInput(date(2026, 10, 3), "OPENING", D(1), 100)])
    assert portfolio_xirr([(p, D(1))], date(2026, 10, 3)).note == NA_NEEDS_DATED


def test_portfolio_xirr_combines_dated_instruments_only():
    a = replay([TxnInput(date(2025, 1, 1), "SIP", D(10), 100_000)])
    b = replay([TxnInput(date(2025, 1, 1), "OPENING", D(5), 50_000)])
    r = portfolio_xirr([(a, D("112")), (b, D("1"))], date(2026, 1, 1))
    assert r.rate == pytest.approx(0.12, abs=1e-6)
