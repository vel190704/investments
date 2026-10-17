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
    opt = s.get(ThesisOptIn, inst.id)
    if opt and opt.send_to_llm:
        t = s.scalar(select(ThesisEntry).where(ThesisEntry.instrument_id == inst.id).order_by(ThesisEntry.version.desc()))
        if t:
            out["my_thesis"] = {"id": "t:latest", "why_i_hold_it": t.why, "what_would_change_my_view": t.change_view,
                                "horizon": t.horizon}
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
