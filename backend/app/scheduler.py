"""Daily market-data refresh (in-process, Asia/Kolkata)."""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.db import session_scope
from app.market.service import refresh_prices

log = logging.getLogger(__name__)


def _job() -> None:
    try:
        with session_scope() as s:
            res = refresh_prices(s, trigger="scheduled")
        log.info("Scheduled refresh: %s ok, %s errors", res["ok_count"], res["error_count"])
    except Exception:  # never let the scheduler thread die
        log.exception("Scheduled refresh failed")


def start_scheduler() -> BackgroundScheduler | None:
    st = get_settings()
    if not st.scheduler_enabled:
        return None
    sched = BackgroundScheduler(timezone="Asia/Kolkata")
    sched.add_job(_job, CronTrigger(hour=st.refresh_hour, minute=st.refresh_minute, timezone="Asia/Kolkata"),
                  id="daily_refresh", replace_existing=True, misfire_grace_time=3600)
    sched.start()
    return sched
