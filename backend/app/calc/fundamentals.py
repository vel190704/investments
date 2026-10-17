"""Fundamental metrics: definitions, plausibility bounds, manual-entry validation, portfolio medians.

Rule: a value is shown only if the source provided it AND it is inside the bounds below. Otherwise the
UI shows "N/A" with the reason. Nothing is estimated or filled in.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from statistics import median


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    unit: str  # "inr" | "ratio" | "fraction" | "text"
    lo: Decimal | None
    hi: Decimal | None
    applies_to: str  # STOCK | MF
    auto_field: str | None = None  # yfinance info key; None = manual only
    auto_scale: Decimal = Decimal(1)  # source value × scale = stored value
    manual: bool = False
    note: str = ""
    computed: bool = False  # derived from statements in app.calc.valuation (not a single info field)


D = Decimal
METRICS: dict[str, Metric] = {m.key: m for m in [
    Metric("market_cap", "Market cap", "inr", D(1), D("1e15"), "STOCK", "marketCap"),
    Metric("pe", "P/E (trailing)", "ratio", D("0.01"), D(1000), "STOCK", "trailingPE",
           note="Yahoo omits trailing P/E for loss-making companies."),
    Metric("roe", "ROE", "fraction", D(-2), D(2), "STOCK", "returnOnEquity"),
    Metric("debt_to_equity", "Debt / equity", "ratio", D(0), D(50), "STOCK", "debtToEquity", D("0.01"),
           note="Yahoo reports debt/equity as a percentage (97.6 = 0.98×); shown here as a ratio."),
    Metric("revenue_growth", "Revenue growth (YoY, latest quarter)", "fraction", D(-1), D(10), "STOCK", "revenueGrowth"),
    Metric("profit_growth", "Profit growth (YoY, latest quarter)", "fraction", D(-1), D(20), "STOCK", "earningsGrowth"),
    Metric("beta", "Beta", "ratio", D(-3), D(5), "STOCK", "beta"),
    Metric("ps", "P/S (trailing)", "ratio", D(0), D(200), "STOCK", computed=True, manual=True),
    Metric("peg", "PEG", "ratio", D(0), D(100), "STOCK", computed=True, manual=True,
           note="PEG = P/E ÷ (earnings growth × 100); growth = Yahoo earningsGrowth (latest quarter YoY)."),
    Metric("fcf_latest", "Free cash flow (latest FY)", "inr", D("-1e15"), D("1e15"), "STOCK", computed=True, manual=True),
    Metric("fcf_margin", "FCF margin", "fraction", D(-5), D(5), "STOCK", computed=True, manual=True),
    Metric("fcf_yield", "FCF yield", "fraction", D(-5), D(5), "STOCK", computed=True, manual=True),
    Metric("interest_coverage", "Interest coverage", "ratio", D(-1000), D(10000), "STOCK", computed=True, manual=True),
    Metric("roce", "ROCE", "fraction", D(-2), D(2), "STOCK", manual=True),
    Metric("promoter_holding", "Promoter holding", "fraction", D(0), D(1), "STOCK", manual=True),
    Metric("alpha", "Alpha (annual)", "fraction", D(-1), D(1), "STOCK", manual=True),
    Metric("category", "Category (SEBI)", "text", None, None, "MF", note="From the AMFI NAVAll.txt section header."),
    Metric("expense_ratio", "Expense ratio (TER)", "fraction", D(0), D("0.03"), "MF", manual=True),
    Metric("exit_load", "Exit load", "text", None, None, "MF", manual=True),
    Metric("tracking_error", "Tracking error", "fraction", D(0), D("0.10"), "MF", manual=True),
    Metric("tracking_difference", "Tracking difference", "fraction", D("-0.10"), D("0.10"), "MF", manual=True),
]}
INDEX_ONLY = {"tracking_error", "tracking_difference"}
NO_RELIABLE_SOURCE = "N/A (no reliable source)"
NOT_PROVIDED = "N/A (not provided by source)"


def check_auto(metric: str, raw) -> tuple[str, Decimal | None, str | None]:
    """(status, value, note) for a source value: OK / MISSING / REJECTED."""
    m = METRICS[metric]
    if raw is None or raw == "" or (isinstance(raw, float) and raw != raw):  # None, '' or NaN
        return "MISSING", None, None
    try:
        v = Decimal(repr(raw) if isinstance(raw, float) else str(raw)) * m.auto_scale
    except (InvalidOperation, ValueError):
        return "REJECTED", None, f"non-numeric value {raw!r}"
    if not v.is_finite() or (m.lo is not None and v < m.lo) or (m.hi is not None and v > m.hi):
        return "REJECTED", None, f"implausible value {raw!r} rejected (allowed {m.lo}–{m.hi} after scaling)"
    return "OK", v, None


class ManualEntryError(ValueError):
    pass


def check_manual(metric: str, value: str, source_note: str, as_of: date, today: date) -> tuple[Decimal | None, str | None]:
    """Validate a manual entry. Percent metrics are entered in % (e.g. 18.5) and stored as fractions."""
    m = METRICS.get(metric)
    if m is None or not m.manual:
        raise ManualEntryError(f"{metric!r} cannot be entered manually")
    if not source_note or not source_note.strip():
        raise ManualEntryError("A source note is required (where the number came from)")
    if as_of is None or as_of > today:
        raise ManualEntryError("An as-of date is required and cannot be in the future")
    if m.unit == "text":
        if not str(value).strip():
            raise ManualEntryError("Value must not be empty")
        return None, str(value).strip()[:300]
    try:
        v = Decimal(str(value).strip().replace("%", ""))
    except InvalidOperation:
        raise ManualEntryError("Value must be a number") from None
    if m.unit == "fraction":
        v = v / 100
    elif m.unit == "inr":  # company-level amounts are entered in ₹ crore
        v = v * Decimal(10_000_000)
    if (m.lo is not None and v < m.lo) or (m.hi is not None and v > m.hi):
        scale = 100 if m.unit == "fraction" else Decimal("1e-7") if m.unit == "inr" else 1
        raise ManualEntryError(f"{m.label} must be between {m.lo * scale} and {m.hi * scale}"
                               + ("%" if m.unit == "fraction" else ""))
    return v, None


def portfolio_median(own_id: int, sector: str, metric: str, values: dict[int, tuple[str, Decimal | None]],
                     min_others: int = 3) -> Decimal | None:
    """Median of the metric across MY OTHER holdings in the same sector; None if fewer than min_others."""
    others = [v for iid, (sec, v) in values.items() if iid != own_id and sec == sector and v is not None]
    if sector == "Unclassified" or len(others) < min_others:
        return None
    return Decimal(str(median(others)))
