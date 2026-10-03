"""Projection calculator: mathematical future-value scenarios (not predictions).

Method (stated in the UI):
- monthly rate r = (1 + R)^(1/12) − 1, so R is an effective annual rate;
- contributions are made at the END of each month;
- the monthly contribution rises by the step-up % at the start of each new year (months 13, 25, ...);
- FV = P(1+r)^n + Σ_{k=1..n} C_k (1+r)^(n−k); with no step-up: FV = P(1+r)^n + C((1+r)^n − 1)/r
  (C·n when r = 0). Nominal rupees; inflation is not modelled.
"""

from __future__ import annotations

from decimal import Decimal, localcontext

from app.money import format_inr, round_paise

FORMULA = "FV = P(1+r)^n + Σ C_k (1+r)^(n−k), with r = (1+R)^(1/12) − 1 and C_k stepped up yearly"
ASSUMPTIONS = [
    "The annual return R is a constant, effective annual rate applied every month as r = (1+R)^(1/12) − 1.",
    "Contributions are made at the end of each month.",
    "The monthly contribution rises by the step-up % once a year, from month 13, 25, 37, …",
    "Nominal rupees: inflation, taxes, fees and exit loads are not modelled.",
    "Real markets do not return a constant rate; these are mathematical scenarios, not predictions.",
]


def monthly_rate(annual_pct: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 40
        return (Decimal(1) + annual_pct / 100) ** (Decimal(1) / Decimal(12)) - 1


def project(start_paise: int, monthly_paise: int, annual_pct: Decimal, years: int,
            step_up_pct: Decimal = Decimal(0)) -> dict:
    if years < 1 or years > 50:
        raise ValueError("years must be between 1 and 50")
    if start_paise < 0 or monthly_paise < 0:
        raise ValueError("amounts must not be negative")
    if annual_pct <= -100:
        raise ValueError("annual return must be above -100%")
    with localcontext() as ctx:
        ctx.prec = 40
        r = monthly_rate(annual_pct)
        value = Decimal(start_paise)
        contrib = Decimal(monthly_paise)
        total_contrib = Decimal(0)
        yearly = []
        for m in range(1, years * 12 + 1):
            if m > 1 and (m - 1) % 12 == 0:
                contrib = contrib * (1 + step_up_pct / 100)
            value = value * (1 + r) + contrib
            total_contrib += contrib
            if m % 12 == 0:
                yearly.append({"year": m // 12, "value_paise": round_paise(value),
                               "contributions_paise": round_paise(total_contrib),
                               "start_paise": start_paise})
        end = round_paise(value)
        contributed = round_paise(total_contrib)
    growth = end - start_paise - contributed
    return {
        "annual_return_pct": str(annual_pct), "years": years, "step_up_pct": str(step_up_pct),
        "start_paise": start_paise, "monthly_paise": monthly_paise, "monthly_rate": str(r.quantize(Decimal("1e-10"))),
        "total_contributions_paise": contributed, "growth_paise": growth, "ending_value_paise": end,
        "growth_share_of_end": str(Decimal(growth) / end) if end else None,
        "yearly": yearly,
    }


def closed_form_no_step_up(start_paise: int, monthly_paise: int, annual_pct: Decimal, years: int) -> int:
    """FV = P(1+r)^n + C((1+r)^n − 1)/r  (C·n when r = 0). Used to cross-check the loop in tests and the UI."""
    with localcontext() as ctx:
        ctx.prec = 40
        r = monthly_rate(annual_pct)
        n = years * 12
        g = (1 + r) ** n
        annuity = Decimal(monthly_paise) * n if r == 0 else Decimal(monthly_paise) * (g - 1) / r
        return round_paise(Decimal(start_paise) * g + annuity)


def sentence(p: dict) -> str:
    step = f", stepped up {p['step_up_pct']}% each year" if Decimal(p["step_up_pct"]) else ""
    return (f"If the portfolio averaged {p['annual_return_pct']}% annually and contributions were "
            f"{format_inr(p['monthly_paise'], decimals=False)} a month{step} for {p['years']} years, "
            f"the mathematical future value would be approximately {format_inr(p['ending_value_paise'], decimals=False)}.")
