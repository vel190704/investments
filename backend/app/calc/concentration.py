"""Company concentration metrics and LOW/MODERATE/HIGH flags.

Scope: direct stock holdings only (ETFs are not companies; mutual-fund look-through is Phase 3).
Thresholds are defined here and returned by the API so the UI shows them verbatim.
Level rule: LOW if v < low; MODERATE if low <= v < high; HIGH if v >= high.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal

from app.money import format_inr, format_pct


@dataclass(frozen=True)
class Threshold:
    key: str
    label: str
    low: Decimal
    high: Decimal
    unit: str  # "fraction" | "hhi"
    explanation: str


THRESHOLDS: dict[str, Threshold] = {
    t.key: t
    for t in [
        Threshold("largest_company_of_direct_equity", "Largest company, % of direct equity",
                  Decimal("0.15"), Decimal("0.25"), "fraction",
                  "Value of the biggest single stock / value of all direct stocks."),
        Threshold("top3_of_direct_equity", "Top 3 companies, % of direct equity",
                  Decimal("0.40"), Decimal("0.60"), "fraction",
                  "Value of the three biggest stocks / value of all direct stocks."),
        Threshold("hhi_direct_equity", "HHI of direct-equity weights",
                  Decimal("1500"), Decimal("2500"), "hhi",
                  "Herfindahl-Hirschman Index: sum of squared % weights (0-10,000). "
                  "1,500 and 2,500 are the conventional 'moderately' / 'highly' concentrated cut-offs."),
        Threshold("largest_company_of_portfolio", "Largest company, % of total portfolio",
                  Decimal("0.05"), Decimal("0.10"), "fraction",
                  "Value of the biggest single stock / total portfolio value (direct holdings)."),
    ]
}


def level_for(value: Decimal, t: Threshold) -> str:
    if value < t.low:
        return "LOW"
    if value < t.high:
        return "MODERATE"
    return "HIGH"


def _fmt_threshold(v: Decimal, unit: str) -> str:
    return format_pct(v, 0) if unit == "fraction" else f"{int(v):,}"


def _level_reason(level: str, t: Threshold) -> str:
    lo, hi = _fmt_threshold(t.low, t.unit), _fmt_threshold(t.high, t.unit)
    return {"LOW": f"LOW because < {lo}", "MODERATE": f"MODERATE because {lo} to < {hi}",
            "HIGH": f"HIGH because ≥ {hi}"}[level]


@dataclass
class Flag:
    key: str
    title: str
    level: str
    value: str
    reason: str
    calculation: str
    thresholds: str


def company_concentration(companies: list[tuple[str, int]], total_portfolio_paise: int) -> dict:
    """companies: [(display name, current value paise)] for direct stocks with a price."""
    companies = sorted([c for c in companies if c[1] > 0], key=lambda c: c[1], reverse=True)
    equity_total = sum(v for _, v in companies)
    result: dict = {
        "scope": "Direct stock holdings only. ETFs are not companies; mutual-fund look-through is not included yet.",
        "direct_equity_value_paise": equity_total,
        "total_portfolio_value_paise": total_portfolio_paise,
        "companies": [],
        "largest": None,
        "top3_share_of_direct_equity": None,
        "hhi": None,
        "flags": [],
        "thresholds": [
            {**asdict(t), "low": str(t.low), "high": str(t.high)} for t in THRESHOLDS.values()
        ],
    }
    if equity_total == 0:
        return result

    eq = Decimal(equity_total)
    tot = Decimal(total_portfolio_paise) if total_portfolio_paise else None
    rows = []
    for name, v in companies:
        rows.append({
            "name": name,
            "value_paise": v,
            "share_of_direct_equity": Decimal(v) / eq,
            "share_of_portfolio": (Decimal(v) / tot) if tot else None,
        })
    result["companies"] = rows

    largest = rows[0]
    top3 = rows[:3]
    top3_value = sum(r["value_paise"] for r in top3)
    top3_share = Decimal(top3_value) / eq
    hhi = sum((r["share_of_direct_equity"] * 100) ** 2 for r in rows)
    result["largest"] = largest
    result["top3_share_of_direct_equity"] = top3_share
    result["hhi"] = hhi

    flags: list[Flag] = []

    t = THRESHOLDS["largest_company_of_direct_equity"]
    lvl = level_for(largest["share_of_direct_equity"], t)
    flags.append(Flag(
        t.key, "Company concentration (direct equity)", lvl,
        format_pct(largest["share_of_direct_equity"]),
        f"{largest['name']} is {format_pct(largest['share_of_direct_equity'])} of direct equity.",
        f"{format_inr(largest['value_paise'])} / {format_inr(equity_total)} = "
        f"{format_pct(largest['share_of_direct_equity'])}; {_level_reason(lvl, t)}.",
        f"LOW < {_fmt_threshold(t.low, t.unit)} ≤ MODERATE < {_fmt_threshold(t.high, t.unit)} ≤ HIGH",
    ))

    t = THRESHOLDS["top3_of_direct_equity"]
    lvl = level_for(top3_share, t)
    names = ", ".join(r["name"] for r in top3)
    flags.append(Flag(
        t.key, "Top-3 concentration (direct equity)", lvl, format_pct(top3_share),
        f"{names} together are {format_pct(top3_share)} of direct equity.",
        f"{format_inr(top3_value)} / {format_inr(equity_total)} = {format_pct(top3_share)}; "
        f"{_level_reason(lvl, t)}.",
        f"LOW < {_fmt_threshold(t.low, t.unit)} ≤ MODERATE < {_fmt_threshold(t.high, t.unit)} ≤ HIGH",
    ))

    t = THRESHOLDS["hhi_direct_equity"]
    lvl = level_for(hhi, t)
    terms = " + ".join(f"{(r['share_of_direct_equity'] * 100).quantize(Decimal('0.1'))}²" for r in rows[:4])
    more = " + …" if len(rows) > 4 else ""
    flags.append(Flag(
        t.key, "Diversification across companies (HHI)", lvl, f"{hhi.quantize(Decimal('1')):,}",
        f"HHI of {len(rows)} direct stocks is {hhi.quantize(Decimal('1')):,}.",
        f"{terms}{more} = {hhi.quantize(Decimal('1')):,}; {_level_reason(lvl, t)}.",
        f"LOW < {_fmt_threshold(t.low, t.unit)} ≤ MODERATE < {_fmt_threshold(t.high, t.unit)} ≤ HIGH",
    ))

    if tot:
        t = THRESHOLDS["largest_company_of_portfolio"]
        share = largest["share_of_portfolio"]
        lvl = level_for(share, t)
        flags.append(Flag(
            t.key, "Single-company weight (total portfolio)", lvl, format_pct(share),
            f"{largest['name']} is {format_pct(share)} of the total portfolio.",
            f"{format_inr(largest['value_paise'])} / {format_inr(total_portfolio_paise)} = "
            f"{format_pct(share)}; {_level_reason(lvl, t)}.",
            f"LOW < {_fmt_threshold(t.low, t.unit)} ≤ MODERATE < {_fmt_threshold(t.high, t.unit)} ≤ HIGH",
        ))

    result["flags"] = [asdict(f) for f in flags]
    return result
