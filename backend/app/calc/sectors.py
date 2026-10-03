"""Sector, geography and theme metrics. Pure. 'Many sectors' is not treated as diversification:
the numbers (largest sector, HHI) and the reason for each flag are shown."""

from __future__ import annotations

from decimal import Decimal

from app.calc.concentration import level_for, Threshold
from app.money import format_inr, format_pct

NON_SECTOR_PREFIXES = ("Debt, cash & other inside funds", "Not looked through", "Gold", "Debt", "Other commodities")
SECTOR_THRESHOLDS = {
    "largest_sector": Threshold("largest_sector", "Largest sector, % of equity exposure", Decimal("0.25"),
                                Decimal("0.40"), "fraction", "Value in the largest sector / total equity exposure."),
    "sector_hhi": Threshold("sector_hhi", "HHI of sector weights", Decimal(1500), Decimal(2500), "hhi",
                            "Sum of squared % sector weights within equity exposure (0–10,000)."),
}


def is_equity_sector(label: str) -> bool:
    return not label.startswith(NON_SECTOR_PREFIXES)


def sector_metrics(rows: list[dict], thresholds: dict[str, Threshold] = SECTOR_THRESHOLDS) -> dict:
    """rows: output of sector_lookthrough (value_paise per label). Uses equity sectors only."""
    eq = [r for r in rows if is_equity_sector(r["sector"]) and r["value_paise"] > 0]
    total = sum(r["value_paise"] for r in eq)
    if not total:
        return {"equity_value_paise": 0, "sectors": 0, "largest": None, "hhi": None, "flags": []}
    shares = {r["sector"]: Decimal(r["value_paise"]) / total for r in eq}
    largest = max(shares, key=lambda k: shares[k])
    hhi = sum((v * 100) ** 2 for v in shares.values())
    t1, t2 = thresholds["largest_sector"], thresholds["sector_hhi"]
    l1, l2 = level_for(shares[largest], t1), level_for(hhi, t2)
    lv = next(r["value_paise"] for r in eq if r["sector"] == largest)
    return {
        "equity_value_paise": total, "sectors": len(eq), "largest": {"sector": largest, "share": str(shares[largest])},
        "hhi": str(hhi.quantize(Decimal(1))),
        "shares": {k: str(v) for k, v in shares.items()},
        "flags": [
            {"key": "largest_sector", "title": "Sector concentration", "level": l1, "value": format_pct(shares[largest]),
             "reason": f"{largest} is {format_pct(shares[largest])} of equity exposure (including through funds).",
             "calculation": f"{format_inr(lv)} / {format_inr(total)} = {format_pct(shares[largest])}",
             "thresholds": f"LOW < {format_pct(t1.low, 0)} ≤ MODERATE < {format_pct(t1.high, 0)} ≤ HIGH"},
            {"key": "sector_hhi", "title": "Sector diversification (HHI)", "level": l2,
             "value": f"{hhi.quantize(Decimal(1)):,}",
             "reason": f"{len(eq)} sectors, but the HHI is {hhi.quantize(Decimal(1)):,}: the count of sectors alone "
                       "does not measure diversification.",
             "calculation": " + ".join(f"{(v * 100).quantize(Decimal('0.1'))}²" for v in
                                       sorted(shares.values(), reverse=True)[:5])
                            + (" + …" if len(shares) > 5 else "") + f" = {hhi.quantize(Decimal(1)):,}",
             "thresholds": f"LOW < {int(t2.low):,} ≤ MODERATE < {int(t2.high):,} ≤ HIGH"},
        ],
    }


def range_checks(rows: list[dict], ranges: dict[str, dict] | None) -> list[dict]:
    """User-set desired ranges (% of total portfolio). No defaults: returns [] when unset."""
    if not ranges:
        return []
    by = {r["sector"]: Decimal(r["pct"]) for r in rows}
    out = []
    for sector, rg in ranges.items():
        cur = by.get(sector, Decimal(0))
        lo, hi = Decimal(rg["min"]) / 100, Decimal(rg["max"]) / 100
        status = "BELOW RANGE" if cur < lo else "ABOVE RANGE" if cur > hi else "IN RANGE"
        out.append({"sector": sector, "current": str(cur), "min": str(lo), "max": str(hi), "status": status,
                    "reason": f"{sector} is {format_pct(cur)} of the portfolio; your range is "
                              f"{format_pct(lo)}–{format_pct(hi)}."})
    return out


def geography(direct_values: list[tuple[str, int]], total_paise: int) -> dict:
    """direct_values: [(region, value)] for every priced holding; India vs international split."""
    india = sum(v for r, v in direct_values if r == "India")
    intl: dict[str, int] = {}
    for r, v in direct_values:
        if r != "India":
            intl[r] = intl.get(r, 0) + v
    t = Decimal(total_paise) if total_paise else Decimal(1)
    return {"india_paise": india, "india_pct": str(Decimal(india) / t),
            "international_paise": sum(intl.values()), "international_pct": str(Decimal(sum(intl.values())) / t),
            "regions": [{"region": r, "value_paise": v, "pct": str(Decimal(v) / t)}
                        for r, v in sorted(intl.items(), key=lambda kv: -kv[1])]}


def theme_exposure(themes: dict[str, list[str]] | None, company_rows: list[dict], total_paise: int) -> list[dict]:
    """themes: {tag: [ISIN, ...]} (user-defined, no defaults). Uses total (direct + indirect) company exposure."""
    if not themes:
        return []
    by_isin = {c["isin"]: c for c in company_rows}
    t = Decimal(total_paise) if total_paise else Decimal(1)
    out = []
    for tag, isins in themes.items():
        members = [by_isin[i] for i in isins if i in by_isin]
        v = sum(c["total_paise"] for c in members)
        out.append({"tag": tag, "value_paise": v, "pct": str(Decimal(v) / t), "members": [
            {"isin": c["isin"], "name": c["name"], "total_paise": c["total_paise"]} for c in members],
            "missing": [i for i in isins if i not in by_isin]})
    return sorted(out, key=lambda x: -x["value_paise"])
