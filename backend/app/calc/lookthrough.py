"""Fund look-through: total company exposure (direct + through funds), sector look-through and
pairwise fund overlap. Pure functions. Companies are matched by ISIN only, never by name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.money import format_inr, format_pct, round_paise

EQUITY_ISIN = re.compile(r"^IN[A-Z0-9]{5}01[A-Z0-9]{2}[0-9]$")  # security-type code 01 = equity shares
STALE_MONTHS = 2
LOOKTHROUGH_THRESHOLDS = (Decimal("0.05"), Decimal("0.10"))  # total % of portfolio: LOW < 5% <= MODERATE < 10% <= HIGH


def is_equity_isin(isin: str | None) -> bool:
    return bool(isin and EQUITY_ISIN.match(isin.strip().upper()))


def months_between(earlier: date, later: date) -> int:
    """Whole calendar months from `earlier` to `later` (day-of-month aware)."""
    m = (later.year - earlier.year) * 12 + (later.month - earlier.month)
    if later.day < earlier.day:
        m -= 1
    return m


def is_stale(as_of: date, today: date, months: int = STALE_MONTHS) -> bool:
    return months_between(as_of, today) > months


@dataclass(frozen=True)
class FundRow:
    isin: str | None
    name: str
    industry: str | None
    weight: Decimal  # fraction of the fund's NAV
    is_equity: bool


@dataclass(frozen=True)
class FundLook:
    instrument_id: int
    name: str
    value_paise: int
    rows: list[FundRow] | None  # None = no disclosure (not looked through)
    label: str | None = None  # e.g. "AMC disclosure as of 2026-09-30" / "approximated from index weights, as of …"
    as_of: date | None = None


@dataclass(frozen=True)
class DirectHolding:
    instrument_id: int
    name: str
    isin: str | None
    value_paise: int
    asset_type: str  # STOCK | ETF | MF
    sector: str


@dataclass
class CompanyExposure:
    isin: str
    name: str
    direct_paise: int = 0
    indirect: dict[int, Decimal] = field(default_factory=dict)  # fund instrument_id -> paise (unrounded)

    @property
    def indirect_paise(self) -> int:
        return round_paise(sum(self.indirect.values(), Decimal(0)))

    @property
    def total_paise(self) -> int:
        return self.direct_paise + self.indirect_paise


def company_exposure(direct: list[DirectHolding], funds: list[FundLook], total_paise: int,
                     thresholds: tuple[Decimal, Decimal] = LOOKTHROUGH_THRESHOLDS) -> dict:
    companies: dict[str, CompanyExposure] = {}
    unmatched_direct = []
    for d in direct:
        if d.asset_type != "STOCK":
            continue
        if not is_equity_isin(d.isin):
            unmatched_direct.append({"instrument_id": d.instrument_id, "name": d.name,
                                     "reason": "ISIN not confirmed — cannot be combined with fund holdings"})
            continue
        c = companies.setdefault(d.isin, CompanyExposure(d.isin, d.name))
        c.direct_paise += d.value_paise
        c.name = d.name  # prefer the direct holding's display name
    fund_names = {f.instrument_id: f.name for f in funds}
    for f in funds:
        if not f.rows:
            continue
        for r in f.rows:
            if not (r.is_equity and is_equity_isin(r.isin)):
                continue
            c = companies.setdefault(r.isin, CompanyExposure(r.isin, r.name))
            c.indirect[f.instrument_id] = c.indirect.get(f.instrument_id, Decimal(0)) + Decimal(f.value_paise) * r.weight

    t = Decimal(total_paise) if total_paise else None
    low, high = thresholds
    rows = []
    for c in sorted(companies.values(), key=lambda c: (-c.total_paise, c.name)):
        total_pct = Decimal(c.total_paise) / t if t else None
        level = None if total_pct is None else ("LOW" if total_pct < low else "MODERATE" if total_pct < high else "HIGH")
        via = [{"instrument_id": fid, "fund": fund_names[fid], "paise": round_paise(v),
                "pct": str(v / t) if t else None} for fid, v in sorted(c.indirect.items(), key=lambda kv: -kv[1])]
        reason = None
        if total_pct is not None and level != "LOW":
            parts = []
            if c.direct_paise:
                parts.append(f"{format_pct(Decimal(c.direct_paise) / t)} held directly")
            parts += [f"{format_pct(Decimal(v['paise']) / t)} through {v['fund']}" for v in via if v["paise"]]
            reason = f"{c.name} is {format_pct(total_pct)} of the portfolio including indirect exposure ({'; '.join(parts)})."
        rows.append({
            "isin": c.isin, "name": c.name, "direct_paise": c.direct_paise, "indirect_paise": c.indirect_paise,
            "total_paise": c.total_paise,
            "direct_pct": str(Decimal(c.direct_paise) / t) if t else None,
            "indirect_pct": str(Decimal(c.indirect_paise) / t) if t else None,
            "total_pct": str(total_pct) if total_pct is not None else None,
            "via": via, "level": level, "reason": reason,
            "calculation": (f"{format_inr(c.direct_paise)} direct + " + " + ".join(
                f"{format_inr(v['paise'])} via {v['fund']}" for v in via) + f" = {format_inr(c.total_paise)}; "
                f"÷ {format_inr(total_paise)} = {format_pct(total_pct)}") if total_pct is not None else None,
        })
    return {
        "companies": rows,
        "unmatched_direct": unmatched_direct,
        "not_looked_through": [{"instrument_id": f.instrument_id, "name": f.name, "value_paise": f.value_paise}
                               for f in funds if not f.rows],
        "coverage": [{"instrument_id": f.instrument_id, "name": f.name, "label": f.label,
                      "as_of": f.as_of.isoformat() if f.as_of else None,
                      "equity_weight": str(sum((r.weight for r in f.rows if r.is_equity and is_equity_isin(r.isin)),
                                               Decimal(0)))}
                     for f in funds if f.rows],
        "thresholds": {"low": str(low), "high": str(high),
                       "rule": f"LOW < {format_pct(low, 0)} ≤ MODERATE < {format_pct(high, 0)} ≤ HIGH (total % of portfolio)"},
    }


def sector_lookthrough(direct: list[DirectHolding], funds: list[FundLook], isin_sector: dict[str, str],
                       total_paise: int) -> list[dict]:
    """Sector exposure across the whole portfolio (direct + through funds), as % of total value.

    Fund equity rows take the NSE sector of their ISIN when known, else the AMC's industry label.
    """
    buckets: dict[str, dict] = {}

    def add(label: str, paise: Decimal, contributor: str, origin: str) -> None:
        b = buckets.setdefault(label, {"sector": label, "value": Decimal(0), "contributors": {}, "origins": set()})
        b["value"] += paise
        b["contributors"][contributor] = b["contributors"].get(contributor, Decimal(0)) + paise
        b["origins"].add(origin)

    for d in direct:
        if d.asset_type == "MF":
            continue
        add(d.sector, Decimal(d.value_paise), d.name, "direct")
    for f in funds:
        if not f.rows:
            add(f"Not looked through — {f.name}", Decimal(f.value_paise), f.name, "fund (no disclosure)")
            continue
        covered = Decimal(0)
        for r in f.rows:
            covered += r.weight
            paise = Decimal(f.value_paise) * r.weight
            if r.is_equity and is_equity_isin(r.isin):
                nse = isin_sector.get(r.isin)
                label = nse or (f"{r.industry} (AMC label)" if r.industry else "Unclassified (AMC gave no industry)")
                add(label, paise, f"{r.name} via {f.name}", "fund")
            else:
                add("Debt, cash & other inside funds", paise, f.name, "fund")
        rest = Decimal(1) - covered
        if rest > 0:
            add("Debt, cash & other inside funds", Decimal(f.value_paise) * rest, f"{f.name} (undisclosed remainder)", "fund")
    t = Decimal(total_paise) if total_paise else Decimal(1)
    out = []
    for b in sorted(buckets.values(), key=lambda b: -b["value"]):
        contributors = sorted(b["contributors"].items(), key=lambda kv: -kv[1])
        out.append({
            "sector": b["sector"], "value_paise": round_paise(b["value"]), "pct": str(b["value"] / t),
            "contributors": [{"name": n, "value_paise": round_paise(v), "pct": str(v / t)} for n, v in contributors[:5]],
            "count": len(contributors), "origins": sorted(b["origins"]),
        })
    return out


def pairwise_overlap(funds: list[FundLook]) -> list[dict]:
    """Overlap(A, B) = Σ over common equity ISINs of min(weight_A, weight_B)."""
    looked = [f for f in funds if f.rows]
    out = []
    for i, a in enumerate(looked):
        wa = _weights(a)
        for b in looked[i + 1:]:
            wb = _weights(b)
            common = sorted(set(wa) & set(wb), key=lambda k: -min(wa[k][0], wb[k][0]))
            overlap = sum((min(wa[k][0], wb[k][0]) for k in common), Decimal(0))
            out.append({
                "fund_a": a.name, "fund_b": b.name, "fund_a_id": a.instrument_id, "fund_b_id": b.instrument_id,
                "overlap": str(overlap), "common_count": len(common),
                "common": [{"isin": k, "name": wa[k][1], "weight_a": str(wa[k][0]), "weight_b": str(wb[k][0]),
                            "min": str(min(wa[k][0], wb[k][0]))} for k in common[:25]],
                "labels": [a.label, b.label],
            })
    return sorted(out, key=lambda x: -Decimal(x["overlap"]))


def _weights(f: FundLook) -> dict[str, tuple[Decimal, str]]:
    w: dict[str, tuple[Decimal, str]] = {}
    for r in f.rows or []:
        if r.is_equity and is_equity_isin(r.isin):
            prev = w.get(r.isin, (Decimal(0), r.name))
            w[r.isin] = (prev[0] + r.weight, prev[1])
    return w
