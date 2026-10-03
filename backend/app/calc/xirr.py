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


def xirr(cashflows: list[tuple[date, float | Decimal | int]]) -> float | None:
    """Return the annualised rate r with sum(cf / (1+r)^(days/365)) = 0, or None."""
    if len(cashflows) < 2:
        return None
    amounts = [float(cf) for _, cf in cashflows]
    if not (any(a < 0 for a in amounts) and any(a > 0 for a in amounts)):
        return None
    d0 = min(d for d, _ in cashflows)
    flows = [((d - d0).days / 365.0, float(cf)) for d, cf in cashflows]
    if all(t == 0 for t, _ in flows):
        return None

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
            return new
        rate = new

    # Bisection fallback on [-99.99%, 10000%].
    lo, hi = -0.9999, 100.0
    try:
        flo, fhi = _npv(lo, flows), _npv(hi, flows)
    except OverflowError:
        return None
    if flo * fhi > 0:
        return None
    for _ in range(300):
        mid = (lo + hi) / 2
        fm = _npv(mid, flows)
        if abs(fm) < 1e-9 or (hi - lo) < 1e-12:
            return mid
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


@dataclass(frozen=True)
class XirrResult:
    rate: float | None
    note: str | None  # e.g. NA_NEEDS_DATED
    flows: int = 0


def position_xirr(pos: Position, price: Decimal | None, valuation_date: date) -> XirrResult:
    """XIRR of the dated (non-OPENING) money in one instrument."""
    if not pos.has_dated_buys:
        return XirrResult(None, NA_NEEDS_DATED)
    if pos.dated_quantity > 0 and price is None:
        return XirrResult(None, "N/A (price unavailable)")
    flows = list(pos.xirr_flows)
    if pos.dated_quantity > 0 and price is not None:
        flows.append((valuation_date, pos.dated_quantity * price * 100))
    rate = xirr(flows)
    return XirrResult(rate, None if rate is not None else "N/A (could not solve)", len(flows))


def portfolio_xirr(items: list[tuple[Position, Decimal | None]], valuation_date: date) -> XirrResult:
    flows: list[tuple[date, Decimal]] = []
    for pos, price in items:
        if not pos.has_dated_buys:
            continue
        if pos.dated_quantity > 0 and price is None:
            return XirrResult(None, "N/A (price unavailable for a holding with dated transactions)")
        flows.extend(pos.xirr_flows)
        if pos.dated_quantity > 0:
            flows.append((valuation_date, pos.dated_quantity * price * 100))
    if not flows:
        return XirrResult(None, NA_NEEDS_DATED)
    rate = xirr(flows)
    return XirrResult(rate, None if rate is not None else "N/A (could not solve)", len(flows))
