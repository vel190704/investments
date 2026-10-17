"""Valuation metrics from a normalised yfinance payload (pure).

Payload: {"info": {...}, "income"|"cashflow"|"balance": {line name: {"YYYY-MM-DD": float|None}}}
Every result is {status: OK|N/A, value, reason, formula, inputs, as_of}. Nothing is estimated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from statistics import median

LINES = {  # metric: (statement, [candidate line names, first present wins])
    "revenue": ("income", ["Total Revenue", "Operating Revenue"]),
    "net_income": ("income", ["Net Income", "Net Income Common Stockholders"]),
    "ebit": ("income", ["EBIT"]),
    "interest_expense": ("income", ["Interest Expense"]),
    "diluted_eps": ("income", ["Diluted EPS"]),
    "fcf": ("cashflow", ["Free Cash Flow"]),
    "equity": ("balance", ["Stockholders Equity", "Common Stock Equity"]),
    "total_debt": ("balance", ["Total Debt"]),
}
BOUNDS = {
    "ps": (Decimal("0"), Decimal("200")),
    "pe": (Decimal("0"), Decimal("1000")),
    "peg": (Decimal("0"), Decimal("100")),
    "earnings_growth": (Decimal("-1"), Decimal("10")),
}
HIST_PE_WINDOW_DAYS = 7


@dataclass
class Result:
    status: str  # OK | N/A
    value: Decimal | None = None
    reason: str | None = None
    formula: str | None = None
    inputs: dict = field(default_factory=dict)
    as_of: str | None = None

    def as_dict(self) -> dict:
        return {"status": self.status, "value": str(self.value) if self.value is not None else None,
                "reason": self.reason, "formula": self.formula, "inputs": self.inputs, "as_of": self.as_of}


def na(reason: str, formula: str | None = None, inputs: dict | None = None) -> Result:
    return Result("N/A", None, reason, formula, inputs or {})


def dec(v) -> Decimal | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    try:
        return Decimal(repr(v) if isinstance(v, float) else str(v))
    except InvalidOperation:
        return None


def annual(payload: dict) -> dict[str, dict[date, Decimal]]:
    """{metric: {fiscal_year_end: value}} with missing values dropped."""
    out: dict[str, dict[date, Decimal]] = {}
    for metric, (stmt, names) in LINES.items():
        rows = payload.get(stmt) or {}
        for n in names:
            if n in rows:
                series = {date.fromisoformat(k[:10]): dec(v) for k, v in rows[n].items()}
                series = {k: v for k, v in series.items() if v is not None}
                if series:
                    out[metric] = dict(sorted(series.items()))
                    break
    return out


def _bounded(key: str, v: Decimal | None, label: str) -> Result:
    if v is None:
        return na(f"{label} not provided by source")
    lo, hi = BOUNDS[key]
    if not (lo < v <= hi):
        return na(f"implausible {label} {v} rejected (allowed above {lo} up to {hi})")
    return Result("OK", v)


def ps(payload: dict) -> Result:
    r = _bounded("ps", dec((payload.get("info") or {}).get("priceToSalesTrailing12Months")), "P/S")
    r.formula = "priceToSalesTrailing12Months (Yahoo)"
    return r


def peg(payload: dict) -> Result:
    info = payload.get("info") or {}
    pe, g = dec(info.get("trailingPE")), dec(info.get("earningsGrowth"))
    formula = "PEG = P/E ÷ (earnings growth × 100)"
    inputs = {"pe": str(pe) if pe is not None else None, "earnings_growth": str(g) if g is not None else None,
              "growth_basis": "Yahoo earningsGrowth (latest quarter, year on year)"}
    if pe is None:
        return na("P/E not available (e.g. loss-making or not provided)", formula, inputs)
    if not (BOUNDS["pe"][0] < pe <= BOUNDS["pe"][1]):
        return na(f"implausible P/E {pe}", formula, inputs)
    if g is None:
        return na("earnings growth not provided by source", formula, inputs)
    if g <= 0:
        return na("earnings growth is zero or negative, so PEG is not meaningful", formula, inputs)
    if g > BOUNDS["earnings_growth"][1]:
        return na(f"implausible earnings growth {g * 100}%", formula, inputs)
    value = pe / (g * 100)
    if value > BOUNDS["peg"][1]:
        return na(f"implausible PEG {value}", formula, inputs)
    return Result("OK", value, None, formula, inputs)


def _latest(series: dict[date, Decimal]) -> tuple[date, Decimal] | None:
    return (max(series), series[max(series)]) if series else None


def fcf_latest(payload: dict) -> Result:
    s = annual(payload).get("fcf", {})
    last = _latest(s)
    if last is None:
        return na("free cash flow not reported in the cash-flow statement")
    trend = [{"fiscal_year_end": d.isoformat(), "value": str(v)} for d, v in s.items()]
    return Result("OK", last[1], None, "Free Cash Flow, latest fiscal year (cash-flow statement)",
                  {"trend": trend}, last[0].isoformat())


def fcf_margin(payload: dict) -> Result:
    a = annual(payload)
    f, r = a.get("fcf", {}), a.get("revenue", {})
    common = sorted(set(f) & set(r))
    formula = "FCF margin = FCF ÷ Total Revenue (same fiscal year)"
    if not common:
        return na("FCF and revenue are not both reported for the same year", formula)
    y = common[-1]
    if r[y] <= 0:
        return na("revenue is zero or negative", formula)
    return Result("OK", f[y] / r[y], None, formula, {"fcf": str(f[y]), "revenue": str(r[y])}, y.isoformat())


def fcf_yield(payload: dict) -> Result:
    last = _latest(annual(payload).get("fcf", {}))
    mcap = dec((payload.get("info") or {}).get("marketCap"))
    formula = "FCF yield = latest annual FCF ÷ market cap"
    if last is None:
        return na("free cash flow not reported", formula)
    if mcap is None or mcap <= 0:
        return na("market cap not provided", formula)
    return Result("OK", last[1] / mcap, None, formula, {"fcf": str(last[1]), "market_cap": str(mcap)},
                  last[0].isoformat())


def interest_coverage(payload: dict) -> Result:
    a = annual(payload)
    e, i = a.get("ebit", {}), a.get("interest_expense", {})
    common = sorted(set(e) & set(i))
    formula = "Interest coverage = EBIT ÷ interest expense (latest fiscal year)"
    if not common:
        return na("EBIT and interest expense are not both reported", formula)
    y = common[-1]
    if i[y] <= 0:
        return na("interest expense is zero or not positive", formula, {"interest_expense": str(i[y])})
    return Result("OK", e[y] / i[y], None, formula, {"ebit": str(e[y]), "interest_expense": str(i[y])}, y.isoformat())


def compute_all(payload: dict) -> dict[str, Result]:
    return {"ps": ps(payload), "peg": peg(payload), "fcf_latest": fcf_latest(payload),
            "fcf_margin": fcf_margin(payload), "fcf_yield": fcf_yield(payload),
            "interest_coverage": interest_coverage(payload)}


def history(series: dict[str, dict[date, Decimal]], prices: dict[date, Decimal]) -> list[dict]:
    """Per fiscal year: ROE, net margin, FCF, FCF margin, EPS and historical P/E (only with a stored price
    within ±HIST_PE_WINDOW_DAYS of the fiscal year end)."""
    years = sorted(set().union(*[set(v) for v in series.values()])) if series else []
    out = []
    for y in years:
        g = lambda m: series.get(m, {}).get(y)  # noqa: E731
        ni, eq, rev, f, eps = g("net_income"), g("equity"), g("revenue"), g("fcf"), g("diluted_eps")
        near = [(abs((d - y).days), d, p) for d, p in prices.items() if abs((d - y).days) <= HIST_PE_WINDOW_DAYS]
        pe_row = {"value": None, "reason": "no stored price near the fiscal year end (history is never estimated)"}
        if near and eps and eps > 0:
            _, d, p = min(near)
            pe_row = {"value": str(p / eps), "reason": None, "price_date": d.isoformat(), "price": str(p), "eps": str(eps)}
        elif near and (eps is None or eps <= 0):
            pe_row = {"value": None, "reason": "EPS missing or not positive for that year"}
        out.append({
            "fiscal_year_end": y.isoformat(),
            "roe": str(ni / eq) if ni is not None and eq and eq > 0 else None,
            "net_margin": str(ni / rev) if ni is not None and rev and rev > 0 else None,
            "fcf": str(f) if f is not None else None,
            "fcf_margin": str(f / rev) if f is not None and rev and rev > 0 else None,
            "eps": str(eps) if eps is not None else None,
            "pe": pe_row,
        })
    return out


def median_or_na(values: list[Decimal], min_count: int = 3) -> tuple[Decimal | None, str | None]:
    vals = [v for v in values if v is not None]
    if len(vals) < min_count:
        return None, f"N/A: only {len(vals)} peer(s) have a value (need at least {min_count})"
    return Decimal(str(median(vals))), None


def hist_pe_median(rows: list[dict]) -> Decimal | None:
    vals = [Decimal(r["pe"]["value"]) for r in rows if r["pe"]["value"]]
    return Decimal(str(median(vals))) if vals else None
