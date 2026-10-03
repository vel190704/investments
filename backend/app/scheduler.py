"""Daily market-data refresh (in-process, Asia/Kolkata)."""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.db import session_scope
from app.market.service import refresh_prices

log = logging.getLogger(__name__)


def _classify_and_fundamentals() -> None:
    """Daily: classifications (official lists, cached 7 days). Sundays: fundamentals."""
    from datetime import datetime

    from app.services.classification import refresh_classification
    from app.services.fundamentals import refresh_fundamentals
    from app.timeutil import IST

    try:
        with session_scope() as s:
            refresh_classification(s)
        if datetime.now(IST).weekday() == 6:
            with session_scope() as s:
                refresh_fundamentals(s)
    except Exception:
        log.exception("Classification/fundamentals refresh failed")


def _job() -> None:
    """Daily: refresh prices, then store today's snapshot (refresh_prices takes it)."""
    _classify_and_fundamentals()
    try:
        with session_scope() as s:
            res = refresh_prices(s, trigger="scheduled")
        log.info("Scheduled refresh: %s ok, %s errors; snapshot %s", res["ok_count"], res["error_count"],
                 (res.get("snapshot") or {}).get("snapshot_date"))
    except Exception:  # never let the scheduler thread die
        log.exception("Scheduled refresh failed")
        try:  # still record today's snapshot from cached prices
            from app.services.snapshots import take_snapshot

            with session_scope() as s:
                take_snapshot(s, trigger="scheduled")
        except Exception:
            log.exception("Scheduled snapshot failed")


def start_scheduler() -> BackgroundScheduler | None:
    st = get_settings()
    if not st.scheduler_enabled:
        return None
    sched = BackgroundScheduler(timezone="Asia/Kolkata")
    sched.add_job(_job, CronTrigger(hour=st.refresh_hour, minute=st.refresh_minute, timezone="Asia/Kolkata"),
                  id="daily_refresh", replace_existing=True, misfire_grace_time=3600)
    sched.start()
    return sched
