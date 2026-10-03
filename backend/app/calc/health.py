"""Portfolio Health: separate dimensions, no overall score, no ranking.

LOW / MODERATE / HIGH is assigned only where a threshold exists in code (editable in Settings › health).
Dimensions without an objective threshold are information only (level None).
"""

from __future__ import annotations

import math
from decimal import Decimal

from app.calc.concentration import Threshold, level_for
from app.money import format_inr, format_pct

MIN_QUOTES_FOR_VOLATILITY = 60
TRADING_DAYS = 252


def _rule(t: Threshold) -> str:
    f = (lambda v: format_pct(v, 0)) if t.unit == "fraction" else (lambda v: f"{int(v):,}")
    return f"LOW < {f(t.low)} ≤ MODERATE < {f(t.high)} ≤ HIGH"


def dim(key: str, title: str, *, level: str | None = None, value: str | None = None, reason: str = "",
        calculation: str | None = None, thresholds: str | None = None, available: bool = True,
        info_only: bool = False) -> dict:
    return {"key": key, "title": title, "level": level, "value": value, "reason": reason, "calculation": calculation,
            "thresholds": thresholds, "available": available, "info_only": info_only}


def company_dimension(companies: list[dict], looked_through: bool, t: Threshold) -> dict:
    title = "Company concentration (look-through)"
    if not companies or companies[0]["total_pct"] is None:
        return dim("company", title, available=False, reason="No priced company exposure yet.")
    top = companies[0]
    share = Decimal(top["total_pct"])
    lvl = level_for(share, t)
    via = [v for v in top["via"] if v["paise"]]
    parts = ([f"{format_pct(Decimal(top['direct_pct']))} held directly"] if top["direct_paise"] else []) + \
            [f"{format_pct(Decimal(v['pct']))} through {v['fund']}" for v in via]
    reason = f"{top['name']} is {format_pct(share)} of the portfolio"
    reason += f" including indirect exposure ({'; '.join(parts)})." if via else " (direct holding)."
    if not looked_through:
        reason += " Fund holdings are not included yet: upload fund disclosures on the Overlap page."
    return dim("company", title, level=lvl, value=format_pct(share), reason=reason,
               calculation=f"{top['calculation']}; {lvl} by the rule {_rule(t)}", thresholds=_rule(t))


def sector_dimension(metrics: dict) -> dict:
    title = "Sector concentration"
    if not metrics.get("largest"):
        return dim("sector", title, available=False, reason="No classified equity exposure yet.")
    f = next(x for x in metrics["flags"] if x["key"] == "largest_sector")
    h = next(x for x in metrics["flags"] if x["key"] == "sector_hhi")
    return dim("sector", title, level=f["level"], value=f["value"],
               reason=f"{f['reason']} Sector HHI is {h['value']} across {metrics['sectors']} sectors ({h['level']}).",
               calculation=f"{f['calculation']}; HHI {h['calculation']}", thresholds=f["thresholds"])


def drift_dimension(rows: list[dict] | None, tolerance_pp: Decimal, high_multiple: Decimal) -> dict:
    title = "Asset allocation drift"
    if rows is None:
        return dim("drift", title, available=False, reason="Set your targets in Settings to assess drift.")
    worst = max(rows, key=lambda r: abs(Decimal(r["deviation_pp"])))
    dev = abs(Decimal(worst["deviation_pp"]))
    hi = tolerance_pp * high_multiple
    lvl = "LOW" if dev <= tolerance_pp else "MODERATE" if dev <= hi else "HIGH"
    return dim("drift", title, level=lvl, value=f"{dev.quantize(Decimal('0.1'))} pp",
               reason=f"Largest deviation: {worst['reason']}", calculation=worst["calculation"],
               thresholds=f"LOW ≤ {tolerance_pp} pp (your band) < MODERATE ≤ {hi} pp < HIGH")


def overlap_dimension(pairs: list[dict], t: Threshold) -> dict:
    title = "Fund overlap"
    if not pairs:
        return dim("overlap", title, available=False,
                   reason="Needs holdings disclosures (or index weights) for at least two funds.")
    p = pairs[0]
    ov = Decimal(p["overlap"])
    lvl = level_for(ov, t)
    common = ", ".join(c["name"] for c in p["common"][:3])
    return dim("overlap", title, level=lvl, value=format_pct(ov),
               reason=f"{p['fund_a']} and {p['fund_b']} overlap by {format_pct(ov)} ({p['common_count']} common "
                      f"holdings{': ' + common if common else ''}).",
               calculation=f"Σ min(weight in A, weight in B) over common ISINs = {format_pct(ov)}",
               thresholds=_rule(t))


def international_dimension(geo: dict) -> dict:
    share = Decimal(geo["international_pct"])
    regions = "; ".join(f"{r['region']} {format_pct(Decimal(r['pct']))}" for r in geo["regions"]) or "none"
    return dim("international", "International exposure", value=format_pct(share), info_only=True,
               reason=f"{format_pct(share)} of the portfolio is international ({regions}). Information only: there "
                      "is no objective threshold for this.",
               calculation=f"{format_inr(geo['international_paise'])} international / total")


def liquidity_dimension(direct_paise: int, fund_paise: int, total_paise: int) -> dict:
    t = Decimal(total_paise) if total_paise else Decimal(1)
    return dim("liquidity", "Liquidity (simple split)", info_only=True,
               value=f"{format_pct(Decimal(direct_paise) / t)} direct / {format_pct(Decimal(fund_paise) / t)} funds",
               reason="Share of value in directly held, exchange-traded stocks/ETFs vs mutual funds (redeemed at "
                      "end-of-day NAV, usually paid T+1 to T+3). Information only; not a market-liquidity measure.",
               calculation=f"{format_inr(direct_paise)} direct, {format_inr(fund_paise)} funds, of {format_inr(total_paise)}")


def annualised_volatility(closes: list[Decimal]) -> float | None:
    if len(closes) < MIN_QUOTES_FOR_VOLATILITY:
        return None
    rets = [float(closes[i] / closes[i - 1]) - 1 for i in range(1, len(closes)) if closes[i - 1] > 0]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(TRADING_DAYS)


def volatility_dimension(series: dict[str, tuple[int, list[Decimal]]]) -> dict:
    """series: {name: (value_paise, stored daily closes oldest→newest)}."""
    title = "Volatility exposure"
    total = sum(v for v, _ in series.values())
    covered = {n: (v, annualised_volatility(c)) for n, (v, c) in series.items()}
    have = {n: (v, vol) for n, (v, vol) in covered.items() if vol is not None}
    cov_value = sum(v for v, _ in have.values())
    if not have or not total or Decimal(cov_value) / total < Decimal("0.5"):
        most = max((len(c) for _, c in series.values()), default=0)
        return dim("volatility", title, available=False, info_only=True,
                   reason=f"N/A: needs at least {MIN_QUOTES_FOR_VOLATILITY} stored daily prices per holding for "
                          f"holdings worth half the portfolio (most so far: {most}). History is never downloaded "
                          "or estimated; it builds from the daily refresh.")
    wavg = sum(v * vol for v, vol in have.values()) / cov_value
    return dim("volatility", title, value=f"{wavg * 100:.1f}% a year", info_only=True,
               reason=f"Value-weighted average annualised volatility of {len(have)} holdings with enough stored "
                      f"history (covering {format_pct(Decimal(cov_value) / total)} of value). Ignores correlation, "
                      "so it overstates the portfolio's volatility. Information only.",
               calculation=f"stdev(daily returns) × √{TRADING_DAYS}, weighted by value")


def emergency_dimension(status: dict | None, high_below: Decimal, moderate_below: Decimal) -> dict:
    title = "Emergency-fund coverage"
    if status is None:
        return dim("emergency", title, available=False, reason="Not entered (Settings › Emergency fund).")
    cov = Decimal(status["percent_complete"])
    lvl = "HIGH" if cov < high_below else "MODERATE" if cov < moderate_below else "LOW"
    return dim("emergency", title, level=lvl, value=format_pct(cov),
               reason=f"The emergency fund covers {format_pct(cov)} of your {status['target_months']}-month target "
                      f"({format_inr(status['balance_paise'])} of {format_inr(status['target_paise'])}). Kept "
                      "separate from the portfolio.",
               calculation=f"{format_inr(status['balance_paise'])} / {format_inr(status['target_paise'])} = {format_pct(cov)}",
               thresholds=f"HIGH below {format_pct(high_below, 0)} < MODERATE below {format_pct(moderate_below, 0)} ≤ LOW")
