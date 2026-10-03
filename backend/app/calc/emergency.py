"""Emergency fund status. Kept entirely separate from the portfolio (never part of value, P&L,
XIRR, allocation, snapshots or the planner)."""

from __future__ import annotations

from decimal import Decimal


def emergency_status(monthly_expenses_paise: int, balance_paise: int, target_months: int) -> dict:
    target = monthly_expenses_paise * target_months
    pct = Decimal(balance_paise) / target if target else None
    return {
        "target_paise": target,
        "balance_paise": balance_paise,
        "remaining_paise": max(0, target - balance_paise),
        "percent_complete": str(pct) if pct is not None else None,
        "months_covered": str(Decimal(balance_paise) / monthly_expenses_paise) if monthly_expenses_paise else None,
        "target_months": target_months,
        "monthly_expenses_paise": monthly_expenses_paise,
        "complete": balance_paise >= target,
    }
