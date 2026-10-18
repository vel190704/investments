"""The app's own portfolio totals for one user, used to prove that a data move or a restore preserved the numbers."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

TOTAL_KEYS = ("total_value_paise", "total_invested_paise", "invested_in_priced_paise", "pnl_paise",
              "today_change_paise", "realised_paise", "dividends_paise", "open_holdings", "transactions", "snapshots",
              "latest_snapshot")


def user_id_for(s: Session, email: str) -> int | None:
    """In a system session."""
    from app.models import User

    return s.scalar(select(User.id).where(func.lower(User.email) == email.strip().lower()))


def totals_in_session(s: Session) -> dict:
    """In a session bound to one user (app/tenancy.py scopes every query)."""
    from app.models import PortfolioSnapshot, Transaction
    from app.services.portfolio import load_rows, summary

    sm = summary(s)
    snaps = list(s.scalars(select(PortfolioSnapshot).order_by(PortfolioSnapshot.snapshot_date)))
    latest = snaps[-1] if snaps else None
    return {
        **{k: sm[k] for k in ("total_value_paise", "total_invested_paise", "invested_in_priced_paise", "pnl_paise",
                              "realised_paise", "dividends_paise")},
        "today_change_paise": sm["today_change"]["paise"],
        "open_holdings": len(load_rows(s)[0]),
        "transactions": s.scalar(select(func.count()).select_from(Transaction)),
        "snapshots": len(snaps),
        "latest_snapshot": [latest.snapshot_date.isoformat(), latest.total_value_paise, latest.total_invested_paise]
        if latest else None,
    }
