"""Build the LLM input for one holding from stored data only. Every value carries an id.

Never included: rupee amounts of the portfolio, quantities, invested/value/P&L, platform, account details,
other holdings' names, or journal text unless the holding is opted in.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.money import format_pct

NEWS_DAYS, NEWS_MAX = 30, 10


class InputError(ValueError):
    pass


def _fmt_fact(c: dict) -> str:
    if c.get("display_na"):
        return c["display_na"]
    if c.get("text"):
        return c["text"]
    v = Decimal(c["value"])
    if c["unit"] == "inr":  # company market cap (not a portfolio amount)
        return f"{int(v / Decimal(10_000_000)):,} crore (INR)"
    if c["unit"] == "fraction":
        return format_pct(v)
    if c["metric"] == "debt_to_equity":
        return f"{v.quantize(Decimal('0.01'))}x"
    return f"{v.quantize(Decimal('0.01'))}"


def build_input(s: Session, instrument_id: int, today: date) -> dict:
    from app.calc.lookthrough import company_exposure
    from app.models import NewsItem, ThesisEntry, ThesisOptIn
    from app.services.classification import sectors_by_instrument
    from app.services.fundamentals import report as fundamentals_report
    from app.services.lookthrough import inputs as lt_inputs
    from app.services.macro import sensitivities, snapshot
    from app.timeutil import as_utc

    rows, priced, total, direct, funds = lt_inputs(s)
    row = next((r for r in rows if r.inst.id == instrument_id), None)
    if row is None:
        raise InputError("Not a current holding")
    if row.inst.asset_type != "STOCK":
        raise InputError("AI analysis covers direct stocks only; for funds and ETFs see look-through and sectors.")
    inst = row.inst
    sec = sectors_by_instrument(s)[inst.id]
    out: dict = {
        "task": "Scenario and context analysis of one listed company held in a private portfolio.",
        "holding": {"id": "h:company", "company": inst.name, "nse_symbol": inst.symbol,
                    "sector": {"id": "h:sector", "value": sec.sector, "source": sec.source or "unclassified"}},
    }
    port = {"note": "Percentages of the total portfolio; no amounts are shared."}
    if row.value_paise is not None and total:
        port["weight"] = {"id": "p:weight", "value": format_pct(Decimal(row.value_paise) / total)}
        exp = next((c for c in company_exposure(direct, funds, total)["companies"] if c["isin"] == inst.isin), None)
        if exp:
            port["total_exposure_incl_funds"] = {"id": "p:total", "value": format_pct(Decimal(exp["total_pct"]))}
    else:
        port["weight"] = {"id": "p:weight", "value": "N/A (no price)"}
    out["portfolio"] = port

    fr = next((x for x in fundamentals_report(s)["stocks"] if x["instrument_id"] == inst.id), None)
    facts, medians = [], []
    for c in (fr["metrics"] if fr else []):
        facts.append({"id": f"f:{c['metric']}", "metric": c["label"], "value": _fmt_fact(c),
                      "source": c.get("source") or "none", "as_of": c.get("as_of") or "N/A"})
        if c.get("portfolio_sector_median"):
            medians.append({"id": f"f:{c['metric']}:median", "metric": c["label"],
                            "within_my_portfolio_sector_median": _fmt_fact({**c, "value": c["portfolio_sector_median"],
                                                                            "display_na": None, "text": None})})
    out["fundamentals"] = facts
    out["within_my_portfolio_medians"] = medians

    cutoff = today - timedelta(days=NEWS_DAYS)
    news = [n for n in s.scalars(select(NewsItem).where(NewsItem.isin == inst.isin).order_by(NewsItem.published_at.desc()))
            if as_utc(n.published_at).date() >= cutoff][:NEWS_MAX] if inst.isin else []
    out["news"] = [{"id": f"n:{n.id}", "title": n.title, "source": n.source, "date": as_utc(n.published_at).date().isoformat(),
                    "category": n.category} for n in news]
    out["macro"] = [{"id": f"m:{m['key']}", "indicator": m["label"], "value": m["display"], "unit": m["unit"],
                     "as_of": m["as_of"] or "N/A"} for m in snapshot(s)]
    tags = sensitivities(s).get(sec.sector, [])
    out["sector_sensitivity_tags"] = {"id": "s:tags", "sector": sec.sector, "tags": tags,
                                      "note": "user-reviewed or starter general sector characteristics, not company facts"}
    _add_valuation(s, inst.id, out)
    _add_opted_in_notes(s, inst.id, out)
    out["allowed_scenarios"] = ["rate_cut", "rate_rise", "weaker_rupee", "higher_crude", "sector_regulation",
                                "demand_slowdown"]
    return out


def data_as_of(inp: dict) -> date | None:
    dates = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("as_of", "date") and isinstance(v, str) and len(v) == 10 and v[4] == "-":
                    dates.append(date.fromisoformat(v))
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(inp)
    return max(dates) if dates else None


def input_hash(inp: dict, model: str, prompt_version: str) -> str:
    canon = json.dumps({"input": inp, "model": model, "prompt": prompt_version}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canon.encode()).hexdigest()


def _opted_in(s: Session, iid: int) -> bool:
    from app.models import ThesisOptIn

    opt = s.get(ThesisOptIn, iid)
    return bool(opt and opt.send_to_llm)


def _add_opted_in_notes(s: Session, iid: int, out: dict) -> None:
    """Thesis + qualitative notes, ONLY when the holding's opt-in box is ticked."""
    from app.models import ThesisEntry
    from app.services.qualitative import latest

    if not _opted_in(s, iid):
        return
    t = s.scalar(select(ThesisEntry).where(ThesisEntry.instrument_id == iid).order_by(ThesisEntry.version.desc()))
    if t:
        out["my_thesis"] = {"id": "t:latest", "why_i_hold_it": t.why, "what_would_change_my_view": t.change_view,
                            "horizon": t.horizon}
    q = latest(s, iid)
    if q:
        out["my_qualitative_notes"] = {"id": "q:latest", "moat_type": q.moat_type, "moat_note": q.moat_note,
                                       "capital_allocation_note": q.capital_allocation_note,
                                       "source_note": q.source_note, "as_of": q.as_of.isoformat()}


def _add_valuation(s: Session, iid: int, out: dict) -> None:
    from app.services.valuation import stock_view

    view = stock_view(s, iid)
    out["framework_check"] = {
        "note": "The investor's own rubric; each check stands alone (no overall score).",
        "checks": [{"id": f"fc:{c['key']}", "check": c["title"], "status": c["status"], "value": c["value"] or "N/A",
                    "rule": c["rule"], "reason": c["reason"]} for c in view["framework"]],
    }
    out["peer_comparison"] = {
        "label": "peers chosen by the investor", "why_these_peers": view["peers"]["note"] or "not given",
        "metrics": [{"id": f"pc:{c['metric']}", "metric": c["metric"], "this_company": c["mine"] or "N/A",
                     "peer_median": c["peer_median"] or (c["median_note"] or "N/A (no peers set)"),
                     "peer_values": {p["symbol"]: p["value"] or "N/A" for p in c["peers"]}}
                    for c in view["peers"]["comparisons"]],
    }
    out["own_history"] = [{"id": f"hist:{r['fiscal_year_end']}", "fiscal_year_end": r["fiscal_year_end"],
                           "roe": r["roe"] or "N/A", "net_margin": r["net_margin"] or "N/A",
                           "free_cash_flow_inr": r["fcf"] or "N/A", "fcf_margin": r["fcf_margin"] or "N/A",
                           "diluted_eps": r["eps"] or "N/A",
                           "pe": r["pe"]["value"] or f"N/A ({r['pe']['reason']})"} for r in view["history"]]


def _fund_type(category: str | None, name: str) -> str:
    return "index" if ("Index" in (category or "") or "index" in name.lower() or "etf" in name.lower()) else "active"


def build_fund_input(s: Session, iid: int, today: date) -> dict:
    """Fund card input, built by code only from stored data (percentages; no amounts)."""
    from app.calc.lookthrough import is_equity_isin, is_stale, pairwise_overlap
    from app.services.fundamentals import report as fundamentals_report
    from app.services.lookthrough import inputs as lt_inputs, nse_sector_by_isin

    rows, priced, total, direct, funds = lt_inputs(s)
    row = next((r for r in rows if r.inst.id == iid), None)
    if row is None or row.inst.asset_type != "MF":
        raise InputError("Fund cards are for mutual funds you hold")
    inst = row.inst
    facts = next((f for f in fundamentals_report(s)["funds"] if f["instrument_id"] == iid), None)
    fmap = {c["metric"]: c for c in (facts["metrics"] if facts else [])}
    category = (fmap.get("category") or {}).get("text")
    ftype = _fund_type(category, inst.name)

    def fact(key):
        c = fmap.get(key) or {}
        return {"id": f"ff:{key}", "value": _fmt_fact(c) if c else "N/A", "source": c.get("source") or "none",
                "as_of": c.get("as_of") or "N/A"}

    out: dict = {
        "task": "Context analysis of one mutual fund in a private portfolio.",
        "fund": {"id": "fund:name", "name": inst.name, "category": category or "N/A (scheme code not confirmed)",
                 "fund_type": ftype},
        "focus": (["tracking difference", "cost", "concentration in top constituents"] if ftype == "index"
                  else ["concentration", "sector tilts", "overlap with my other holdings"]),
        "costs": {"expense_ratio": fact("expense_ratio"), "exit_load": fact("exit_load"),
                  "tracking_difference": fact("tracking_difference"), "tracking_error": fact("tracking_error")},
    }
    if row.value_paise is not None and total:
        out["portfolio"] = {"id": "p:fund_share", "share_of_my_portfolio": format_pct(Decimal(row.value_paise) / total)}
    else:
        out["portfolio"] = {"id": "p:fund_share", "share_of_my_portfolio": "N/A (no NAV)"}
    me = next((f for f in funds if f.instrument_id == iid), None)
    if me is None or not me.rows:
        out["holdings"] = {"id": "hold:none", "status": "N/A: no portfolio disclosure uploaded for this fund"}
    else:
        eq = sorted([r for r in me.rows if r.is_equity and is_equity_isin(r.isin)], key=lambda r: -r.weight)
        direct_isins = {d.isin for d in direct if d.isin}
        sector_of = nse_sector_by_isin(s)
        sectors: dict[str, Decimal] = {}
        for r in eq:
            label = sector_of.get(r.isin) or (f"{r.industry} (AMC label)" if r.industry else "Unclassified")
            sectors[label] = sectors.get(label, Decimal(0)) + r.weight
        top10 = sum((r.weight for r in eq[:10]), Decimal(0))
        common_direct = [r for r in eq if r.isin in direct_isins]
        out["holdings"] = {
            "id": "hold:disclosure", "source": me.label, "as_of": me.as_of.isoformat() if me.as_of else "N/A",
            "stale": bool(me.as_of and is_stale(me.as_of, today)),
            "top_holdings": [{"id": f"th:{r.isin}", "company": r.name, "weight_of_fund": format_pct(r.weight, 2)}
                             for r in eq[:10]],
            "top10_weight_of_fund": {"id": "th:top10", "value": format_pct(top10, 2)},
            "sector_weights_of_fund": [{"id": f"sw:{i}", "sector": k, "weight_of_fund": format_pct(v_, 2)}
                                       for i, (k, v_) in enumerate(sorted(sectors.items(), key=lambda kv: -kv[1])[:10])],
            "overlap_with_my_direct_stocks": {
                "id": "od:direct", "combined_weight_of_fund": format_pct(sum((r.weight for r in common_direct), Decimal(0)), 2),
                "companies": [r.name for r in common_direct[:10]]},
        }
        out["overlap_with_my_other_funds"] = [
            {"id": f"ov:{p['fund_b_id'] if p['fund_a_id'] == iid else p['fund_a_id']}",
             "other_fund": p["fund_b"] if p["fund_a_id"] == iid else p["fund_a"], "overlap": format_pct(Decimal(p["overlap"]), 2),
             "common_holdings": p["common_count"]}
            for p in pairwise_overlap(funds) if iid in (p["fund_a_id"], p["fund_b_id"])]
    _add_opted_in_notes(s, iid, out)
    return out


def build_portfolio_input(s: Session, today: date) -> dict:
    """Flags only, as percentages and levels. Calculation strings (which contain amounts) and the emergency
    fund (personal finances) are deliberately excluded."""
    from app.services.health import health
    from app.services.lookthrough import lookthrough
    from app.services.portfolio import drift_block, load_rows

    rows, _ = load_rows(s)
    total = sum(r.value_paise for r in rows if r.value_paise is not None)
    if not total:
        raise InputError("No priced holdings yet")
    h = health(s)
    out: dict = {"task": "Factual summary of what the portfolio flags show."}
    out["health"] = [{"id": f"hd:{d['key']}", "dimension": d["title"], "level": d["level"] or "information only",
                      "value": d["value"] or "N/A", "reason": d["reason"]}
                     for d in h["dimensions"] if d["key"] != "emergency" and d["available"]]
    lk = lookthrough(s)
    out["top_company_exposure"] = [{"id": f"c:{c['isin']}", "company": c["name"], "total_pct": format_pct(Decimal(c["total_pct"]), 2),
                                    "direct_pct": format_pct(Decimal(c["direct_pct"]), 2),
                                    "via_funds_pct": format_pct(Decimal(c["indirect_pct"]), 2), "level": c["level"]}
                                   for c in lk["companies"][:5] if c["total_pct"]]
    d = drift_block(s, rows, total)
    out["allocation_drift"] = ([{"id": f"d:{r['asset_class']}", "asset_class": r["asset_class"], "current": format_pct(Decimal(r["current"])),
                                 "target": format_pct(Decimal(r["target"])), "status": r["status"]} for r in d["rows"]]
                               if d["targets_set"] else {"id": "d:none", "status": "targets not set"})
    out["not_looked_through"] = {"id": "lt:missing", "funds": [f["name"] for f in lk["not_looked_through"]]}
    return out
