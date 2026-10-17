"""Framework check: each rule from MY rubric is MEETS / DOES NOT MEET / N/A / NOT APPLICABLE.
No overall score, ranking or verdict."""

from __future__ import annotations

from decimal import Decimal

from app.money import format_pct, group_indian

MEETS, FAILS, NA, NOT_APPLICABLE = "MEETS", "DOES NOT MEET", "N/A", "NOT APPLICABLE"
DEFAULT_RUBRIC = {"pe_vs_peer_tolerance_pct": "0", "peg_max": "1.0", "roe_min_pct": "15", "de_max": "2.0",
                  "fcf_positive": True, "fcf_not_declining": True}
DEFAULT_SECTOR_RULES = {"Financial Services": ["debt_to_equity", "interest_coverage"]}


def format_crore(rupees: Decimal) -> str:
    """Company-level rupee amount as ₹ crore with Indian grouping, e.g. -7,840 Cr -> "−₹7,840 Cr"."""
    cr = int((abs(rupees) / Decimal(10_000_000)).quantize(Decimal(1)))
    return f"{'−' if rupees < 0 else ''}₹{group_indian(str(cr))} Cr"


def _c(key, title, status, value, rule, reason, sources=None, display=None) -> dict:
    """value: plain figures (this is what the AI input carries); display: the same for people, e.g. ₹ crore."""
    return {"key": key, "title": title, "status": status, "value": value, "display": display or value, "rule": rule,
            "reason": reason, "sources": sources or []}


def checks(metrics: dict[str, dict], peer_median_pe: Decimal | None, peer_note: str | None,
           own_hist_pe: Decimal | None, fcf_series: list[tuple[str, Decimal]], sector: str,
           rubric: dict | None = None, sector_rules: dict | None = None) -> list[dict]:
    """metrics: {key: {"value": Decimal|None, "source": str, "as_of": str|None}} for pe, peg, roe, debt_to_equity,
    interest_coverage. fcf_series: [(fiscal_year_end, value)] oldest -> newest."""
    r = {**DEFAULT_RUBRIC, **(rubric or {})}
    not_app = set((sector_rules if sector_rules is not None else DEFAULT_SECTOR_RULES).get(sector, []))
    v = {k: (metrics.get(k) or {}).get("value") for k in ("pe", "peg", "roe", "debt_to_equity", "interest_coverage")}
    src = {k: [(metrics.get(k) or {}).get("source")] for k in v}
    out = []

    tol = Decimal(r["pe_vs_peer_tolerance_pct"]) / 100
    if v["pe"] is None:
        out.append(_c("pe_vs_peers", "P/E vs peer median", NA, None, f"P/E ≤ peer median × (1 + {format_pct(tol, 0)})",
                      "P/E not available"))
    elif peer_median_pe is None:
        out.append(_c("pe_vs_peers", "P/E vs peer median", NA, f"{v['pe']:.2f}", "needs a peer median",
                      peer_note or "no peer median (set peers on the Valuation page)", src["pe"]))
    else:
        limit = peer_median_pe * (1 + tol)
        ok = v["pe"] <= limit
        out.append(_c("pe_vs_peers", "P/E vs peer median", MEETS if ok else FAILS,
                      f"{v['pe']:.2f} vs {peer_median_pe:.2f}", f"P/E ≤ peer median × (1 + {format_pct(tol, 0)})",
                      f"P/E {v['pe']:.2f} is {'at or below' if ok else 'above'} {limit:.2f}", src["pe"] + ["peers chosen by me"]))
    if v["pe"] is None or own_hist_pe is None:
        out.append(_c("pe_vs_history", "P/E vs own history", NA, f"{v['pe']:.2f}" if v["pe"] is not None else None,
                      "P/E ≤ median of own historical P/E",
                      "no historical P/E (needs stored prices near past fiscal year ends)" if v["pe"] is not None
                      else "P/E not available", src["pe"]))
    else:
        ok = v["pe"] <= own_hist_pe
        out.append(_c("pe_vs_history", "P/E vs own history", MEETS if ok else FAILS, f"{v['pe']:.2f} vs {own_hist_pe:.2f}",
                      "P/E ≤ median of own historical P/E", f"P/E {'at or below' if ok else 'above'} own history median",
                      src["pe"]))

    def simple(key, title, val, ok_fn, rule, fmt, metric_key):
        if metric_key in not_app:
            out.append(_c(key, title, NOT_APPLICABLE, None, rule, f"not applicable for {sector} (sector rules)"))
        elif val is None:
            out.append(_c(key, title, NA, None, rule, "value not available", src.get(metric_key)))
        else:
            ok = ok_fn(val)
            out.append(_c(key, title, MEETS if ok else FAILS, fmt(val), rule, f"{fmt(val)} {'meets' if ok else 'does not meet'} the rule",
                          src.get(metric_key)))

    peg_max = Decimal(r["peg_max"])
    simple("peg", "PEG", v["peg"], lambda x: x < peg_max, f"PEG < {peg_max}", lambda x: f"{x:.2f}", "peg")
    roe_min = Decimal(r["roe_min_pct"]) / 100
    simple("roe", "ROE", v["roe"], lambda x: x > roe_min, f"ROE > {format_pct(roe_min, 0)}", lambda x: format_pct(x), "roe")
    de_max = Decimal(r["de_max"])
    simple("debt_to_equity", "Debt / equity", v["debt_to_equity"], lambda x: x < de_max, f"D/E < {de_max}",
           lambda x: f"{x:.2f}x", "debt_to_equity")
    if "interest_coverage" in not_app:
        out.append(_c("interest_coverage", "Interest coverage", NOT_APPLICABLE, None, "shown for context",
                      f"not applicable for {sector} (sector rules)"))
    else:
        ic = v["interest_coverage"]
        out.append(_c("interest_coverage", "Interest coverage", NA if ic is None else "INFO", f"{ic:.2f}x" if ic is not None else None,
                      "context only (no threshold in the rubric)", "value not available" if ic is None else "shown for context",
                      src["interest_coverage"]))

    if r.get("fcf_positive", True):
        if not fcf_series:
            out.append(_c("fcf_positive", "FCF positive", NA, None, "latest annual FCF > 0", "FCF not reported"))
        else:
            y, val = fcf_series[-1]
            out.append(_c("fcf_positive", "FCF positive", MEETS if val > 0 else FAILS, f"{val} ({y})", "latest annual FCF > 0",
                          f"latest FCF is {'positive' if val > 0 else 'zero or negative'}", ["annual cash-flow statement"],
                          display=f"{format_crore(val)} ({y})"))
    if r.get("fcf_not_declining", True):
        if len(fcf_series) < 2:
            out.append(_c("fcf_not_declining", "FCF not declining", NA, None, "latest FCF ≥ previous year",
                          "needs at least two fiscal years of FCF"))
        else:
            (y0, p), (y1, c) = fcf_series[-2], fcf_series[-1]
            ok = c >= p
            out.append(_c("fcf_not_declining", "FCF not declining", MEETS if ok else FAILS, f"{c} ({y1}) vs {p} ({y0})",
                          "latest FCF ≥ previous year", f"FCF {'did not decline' if ok else 'declined'} year on year",
                          ["annual cash-flow statement"], display=f"{format_crore(c)} ({y1}) vs {format_crore(p)} ({y0})"))
    return out
