"""Planner, projection and emergency-fund services (DB + settings -> pure calc)."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app import repository as repo
from app.calc import planner as pl
from app.calc.emergency import emergency_status
from app.calc.projection import ASSUMPTIONS as PROJ_ASSUMPTIONS
from app.calc.projection import FORMULA, closed_form_no_step_up, project, sentence
from app.services import settings as st
from app.services.portfolio import load_rows, sim_holdings


def plan_lines(session: Session) -> list[pl.PlanLine]:
    return [pl.PlanLine(p.name, p.is_bucket, p.allocation_fraction, p.instrument_id) for p in repo.plan_items(session)]


def planner(session: Session, budget_paise: int | None, picks: list[int]) -> dict:
    holdings, excluded = sim_holdings(session)
    lines = plan_lines(session)
    default_budget = sum(p.monthly_amount_paise for p in repo.plan_items(session))
    budget = budget_paise if budget_paise is not None else default_budget
    targets = st.targets(session)
    tol = st.tolerance_pp(session)
    th = st.concentration_thresholds(session)
    out = {
        "budget_paise": budget, "default_budget_paise": default_budget,
        "budget_source": "monthly_plan sheet" if budget_paise is None else "temporary override (file unchanged)",
        "presets_rupees": pl.PRESET_BUDGETS_RUPEES, "assumptions": pl.ASSUMPTIONS, "excluded": excluded,
        "targets_set": targets is not None, "picks": picks,
        "pickable": [{"instrument_id": h.instrument_id, "short_name": h.short_name, "name": h.name,
                      "asset_class": h.asset_class, "price": str(h.price)}
                     for h in holdings if h.asset_type != "MF"],
        "modes": [],
    }
    if not holdings or budget <= 0:
        return out
    if not lines:
        out["modes"].append({"mode": "plan", "label": "Current monthly_plan proportions", "available": False,
                             "reason": "No monthly_plan rows imported."})
    else:
        out["modes"].append(pl.plan_mode(holdings, budget, lines, picks, st.TARGET_CLASSES, targets, tol, th))
    out["modes"].append(pl.targets_mode(holdings, budget, lines, picks, st.TARGET_CLASSES, targets, tol, th))
    return out


def projection(session: Session, start_paise: int | None, monthly_paise: int | None, years: int | None,
               step_up: Decimal | None, custom_rate: Decimal | None) -> dict:
    cfg = st.get(session, "projection")
    rows, _ = load_rows(session)
    current = sum(r.value_paise for r in rows if r.value_paise is not None)
    unpriced = [r.inst.name for r in rows if r.value_paise is None]
    plan_total = sum(p.monthly_amount_paise for p in repo.plan_items(session))
    start = current if start_paise is None else start_paise
    monthly = plan_total if monthly_paise is None else monthly_paise
    yrs = years or cfg["default_years"]
    step = Decimal(cfg["default_step_up"]) if step_up is None else step_up
    named = [("Conservative", Decimal(cfg["conservative"])), ("Base", Decimal(cfg["base"])),
             ("Higher", Decimal(cfg["higher"]))]
    if custom_rate is not None:
        named.append(("Custom", custom_rate))
    scenarios = []
    for name, rate in named:
        p = project(start, monthly, rate, yrs, step)
        scenarios.append({"name": name, **p, "sentence": sentence(p)})
    return {
        "inputs": {"start_paise": start, "monthly_paise": monthly, "years": yrs, "step_up_pct": str(step)},
        "defaults": {"start_paise": current, "start_source": "current portfolio value (priced holdings)",
                     "start_excludes": unpriced, "monthly_paise": plan_total, "monthly_source": "monthly_plan sheet",
                     "years": cfg["default_years"], "step_up_pct": cfg["default_step_up"]},
        "rates_reviewed": cfg["reviewed"],
        "rates_note": None if cfg["reviewed"] else
        "Scenario rates are placeholders (6% / 9% / 12%) shipped with the app. Review and set your own in Settings.",
        "formula": FORMULA,
        "closed_form_check_paise": closed_form_no_step_up(start, monthly, named[1][1], yrs) if step == 0 else None,
        "assumptions": PROJ_ASSUMPTIONS,
        "scenarios": scenarios,
    }


def emergency_fund(session: Session) -> dict:
    v = st.get(session, "emergency_fund")
    return {
        "is_set": v is not None,
        "status": emergency_status(v["monthly_expenses_paise"], v["balance_paise"], v["target_months"]) if v else None,
        "note": "Kept separate: the emergency fund is never included in portfolio value, P&L, XIRR, allocation, "
                "snapshots or the planner.",
    }
