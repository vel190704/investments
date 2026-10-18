"""Startup catch-up: after the app was off, fetch current prices, take today's snapshot, and record the missed
calendar dates as gaps. Nothing is interpolated or back-filled."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import PortfolioSnapshot, SnapshotGap

GAP_REASON = "no snapshot: the app was not running"


def missed_dates(last: date | None, today: date) -> list[date]:
    """Calendar dates strictly between the last snapshot and today (none if no snapshot ever existed)."""
    if last is None or last >= today - timedelta(days=1):
        return []
    return [last + timedelta(days=i) for i in range(1, (today - last).days)]


def catch_up(s: Session, today: date, refresh=None) -> dict:
    """In a user session: that user's last snapshot. In a system session (start-up): the latest snapshot of any
    user; the caller then snapshots every user (jobs.catch_up_global). Gaps are global: the app was down for all."""
    from app.market.service import refresh_prices

    last = s.scalar(select(func.max(PortfolioSnapshot.snapshot_date)))
    if last is not None and last >= today:
        return {"ran": False, "reason": "today's snapshot exists"}
    gaps = missed_dates(last, today)
    existing = set(s.scalars(select(SnapshotGap.gap_date)))
    for d in gaps:
        if d not in existing:
            s.add(SnapshotGap(gap_date=d, reason=GAP_REASON))
    s.flush()
    res = (refresh or (lambda ss: refresh_prices(ss, trigger="startup")))(s)  # takes today's snapshot
    return {"ran": True, "gaps_recorded": [d.isoformat() for d in gaps], "refresh": {k: res.get(k) for k in ("ok_count", "error_count")},
            "snapshot": res.get("snapshot")}
