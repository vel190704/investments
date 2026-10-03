from datetime import date
from decimal import Decimal as D

import pytest

from app.calc.positions import TxnInput, replay
from app.calc.xirr import (
    NA_NEEDS_DATED, NA_NO_CONVERGENCE, NA_NO_SIGN_CHANGE, NA_ONE_FLOW, NA_SAME_DAY, group_xirr, portfolio_xirr,
    position_xirr, solve_xirr, xirr,
)


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


# ---- Phase 2: reference values and edge cases
def test_exact_reference_two_years_ten_percent():
    # 1000 grows to 1210 over exactly 730 days = 2 × 365 (2021, 2022 not leap) -> exactly 10% p.a.
    assert xirr([(date(2021, 1, 1), -1000), (date(2023, 1, 1), 1210)]) == pytest.approx(0.10, abs=1e-9)


def test_exact_reference_two_contributions():
    # -1000 at t0, -1000 at t0+365d, value 1000·1.1² + 1000·1.1 = 2310 at t0+730d -> 10%
    flows = [(date(2021, 1, 1), -1000), (date(2022, 1, 1), -1000), (date(2023, 1, 1), 2310)]
    assert xirr(flows) == pytest.approx(0.10, abs=1e-9)


def test_reference_monthly_sip_matches_npv_zero():
    from datetime import timedelta
    d0 = date(2025, 1, 1)
    flows = [(d0 + timedelta(days=30 * k), -1000) for k in range(12)] + [(date(2026, 1, 1), 12800)]
    r = xirr(flows)
    npv = sum(cf / (1 + r) ** ((d - d0).days / 365) for d, cf in flows)
    assert abs(npv) < 1e-6 and 0.05 < r < 0.20


@pytest.mark.parametrize("flows,note", [
    ([], NA_NEEDS_DATED),
    ([(date(2024, 1, 1), -100)], NA_ONE_FLOW),
    ([(date(2024, 1, 1), -100), (date(2024, 1, 1), 120)], NA_SAME_DAY),
    ([(date(2024, 1, 1), -100), (date(2025, 1, 1), -50)], NA_NO_SIGN_CHANGE),
    ([(date(2024, 1, 1), 100), (date(2025, 1, 1), 50)], NA_NO_SIGN_CHANGE),
])
def test_edge_cases_have_reasons(flows, note):
    r = solve_xirr(flows)
    assert r.rate is None and r.note == note


def test_non_convergence_reported():
    # Total loss within a day: the root lies below -99.99% -> outside the solver bracket
    r = solve_xirr([(date(2024, 1, 1), -1_000_000), (date(2024, 1, 2), 1)])
    assert r.rate is None and r.note == NA_NO_CONVERGENCE


def test_sell_and_dividend_rows_are_cash_flows():
    p = replay([TxnInput(date(2023, 1, 1), "BUY", D(10), 100_000),
                TxnInput(date(2024, 1, 1), "DIVIDEND", None, 5_000),
                TxnInput(date(2024, 1, 1), "SELL", D(10), 105_000)])
    # -1000 then +50 +1050 a year later -> 10%
    r = position_xirr(p, None, date(2025, 1, 1))
    assert r.rate == pytest.approx(0.10, abs=1e-6)


def test_dividend_after_full_sale_counts():
    p = replay([TxnInput(date(2023, 1, 1), "BUY", D(10), 100_000),
                TxnInput(date(2023, 6, 1), "SELL", D(10), 100_000),
                TxnInput(date(2023, 7, 1), "DIVIDEND", None, 2_000)])
    assert p.xirr_flows[-1] == (date(2023, 7, 1), D(2000))


def test_group_xirr_includes_closed_positions_and_names_missing_price():
    closed = replay([TxnInput(date(2025, 1, 1), "BUY", D(1), 100_000), TxnInput(date(2026, 1, 1), "SELL", D(1), 110_000)])
    open_ = replay([TxnInput(date(2025, 1, 1), "BUY", D(1), 100_000)])
    r = group_xirr([("A", closed, None), ("B", open_, D("1100"))], date(2026, 1, 1))
    assert r.rate == pytest.approx(0.10, abs=1e-6)
    r = group_xirr([("B", open_, None)], date(2026, 1, 1))
    assert r.rate is None and r.note == "N/A (price unavailable for B)"
