"""XIRR (Excel-compatible: Actual/365, annual compounding).

Rates are solved in float; the cash flows themselves come from exact paise values.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.calc.positions import Position

NA_NEEDS_DATED = "N/A (needs dated transactions)"


def _npv(rate: float, flows: list[tuple[float, float]]) -> float:
    return sum(cf / (1.0 + rate) ** t for t, cf in flows)


def _dnpv(rate: float, flows: list[tuple[float, float]]) -> float:
    return sum(-t * cf / (1.0 + rate) ** (t + 1) for t, cf in flows)


NA_ONE_FLOW = "N/A (only one cash flow)"
NA_SAME_DAY = "N/A (all cash flows on the same day)"
NA_NO_SIGN_CHANGE = "N/A (cash flows do not change sign)"
NA_NO_CONVERGENCE = "N/A (did not converge)"
NA_PRICE = "N/A (price unavailable)"


@dataclass(frozen=True)
class XirrResult:
    rate: float | None
    note: str | None  # reason when rate is None
    flows: int = 0


def solve_xirr(cashflows: list[tuple[date, float | Decimal | int]]) -> XirrResult:
    """Annualised r with sum(cf / (1+r)^(days/365)) = 0, or N/A with the reason."""
    n = len(cashflows)
    if n == 0:
        return XirrResult(None, NA_NEEDS_DATED, 0)
    if n == 1:
        return XirrResult(None, NA_ONE_FLOW, 1)
    amounts = [float(cf) for _, cf in cashflows]
    d0 = min(d for d, _ in cashflows)
    flows = [((d - d0).days / 365.0, float(cf)) for d, cf in cashflows]
    if all(t == 0 for t, _ in flows):
        return XirrResult(None, NA_SAME_DAY, n)
    if not (any(a < 0 for a in amounts) and any(a > 0 for a in amounts)):
        return XirrResult(None, NA_NO_SIGN_CHANGE, n)

    # Newton-Raphson from a 10% guess.
    rate = 0.1
    for _ in range(100):
        try:
            f = _npv(rate, flows)
            df = _dnpv(rate, flows)
        except (OverflowError, ZeroDivisionError):
            break
        if df == 0:
            break
        new = rate - f / df
        if new <= -0.999999:
            break
        if abs(new - rate) < 1e-12:
            return XirrResult(new, None, n)
        rate = new

    # Bisection fallback on [-99.99%, 10000%].
    lo, hi = -0.9999, 100.0
    try:
        flo, fhi = _npv(lo, flows), _npv(hi, flows)
    except OverflowError:
        return XirrResult(None, NA_NO_CONVERGENCE, n)
    if flo * fhi > 0:
        return XirrResult(None, NA_NO_CONVERGENCE, n)
    for _ in range(300):
        mid = (lo + hi) / 2
        fm = _npv(mid, flows)
        if abs(fm) < 1e-9 or (hi - lo) < 1e-12:
            return XirrResult(mid, None, n)
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return XirrResult((lo + hi) / 2, None, n)


def xirr(cashflows: list[tuple[date, float | Decimal | int]]) -> float | None:
    return solve_xirr(cashflows).rate


def _dated_flows(pos: Position, price: Decimal | None, valuation_date: date) -> list[tuple[date, Decimal]] | None:
    """Dated (non-OPENING) flows plus the terminal value of dated units; None if a price is missing."""
    flows = list(pos.xirr_flows)
    if pos.dated_quantity > 0:
        if price is None:
            return None
        flows.append((valuation_date, pos.dated_quantity * price * 100))
    return flows


def position_xirr(pos: Position, price: Decimal | None, valuation_date: date) -> XirrResult:
    """XIRR of the dated (non-OPENING) money in one instrument."""
    if not pos.has_dated_buys:
        return XirrResult(None, NA_NEEDS_DATED)
    flows = _dated_flows(pos, price, valuation_date)
    if flows is None:
        return XirrResult(None, NA_PRICE)
    return solve_xirr(flows)


def group_xirr(items: list[tuple[str, Position, Decimal | None]], valuation_date: date) -> XirrResult:
    """XIRR across several instruments (asset class or whole portfolio); items: (name, position, price)."""
    flows: list[tuple[date, Decimal]] = []
    for name, pos, price in items:
        if not pos.has_dated_buys:
            continue
        f = _dated_flows(pos, price, valuation_date)
        if f is None:
            return XirrResult(None, f"N/A (price unavailable for {name})")
        flows.extend(f)
    if not flows:
        return XirrResult(None, NA_NEEDS_DATED)
    return solve_xirr(flows)


def portfolio_xirr(items: list[tuple[Position, Decimal | None]], valuation_date: date) -> XirrResult:
    return group_xirr([(str(i), p, pr) for i, (p, pr) in enumerate(items)], valuation_date)
