"""In-process jobs (Asia/Kolkata): the daily end-of-day refresh, and intraday quotes during market hours."""

import logging
import time
import uuid

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.db import session_scope
from app.logging_config import REQUEST_ID, event

log = logging.getLogger("app.jobs")


def run_job(name: str, fn, *args, **kwargs):
    """Run one job step with start/end/duration/outcome logged; its lines carry rid=job:<name>-<id>.
    Holds the job's global lock (Postgres advisory lock), so two instances never run the same step.
    Never raises (a failing step must not kill the scheduler thread); returns fn's result or None."""
    from app.jobs import job_lock

    token = REQUEST_ID.set(f"job:{name}-{uuid.uuid4().hex[:6]}")
    t0 = time.perf_counter()
    try:
        with job_lock(name) as mine:
            if not mine:
                event(log, "job_skipped", job=name, reason="another instance holds the lock")
                return None
            event(log, "job_start", job=name)
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                from app.observability import capture

                capture(exc)
                event(log, "job_end", logging.ERROR, exc_info=True, job=name, outcome="failed",
                      duration_ms=round((time.perf_counter() - t0) * 1000))
                return None
            summary = {k: result[k] for k in ("ok_count", "error_count", "summary", "added", "created")
                       if isinstance(result, dict) and k in result}
            event(log, "job_end", job=name, outcome="ok", duration_ms=round((time.perf_counter() - t0) * 1000),
                  **summary)
            return result
    except Exception:  # the lock itself failed (e.g. database unreachable)
        event(log, "job_end", logging.ERROR, exc_info=True, job=name, outcome="lock failed")
        return None
    finally:
        REQUEST_ID.reset(token)


def _system(fn):
    """A global step: one system session (market data for every user's holdings)."""
    def step(*args, **kwargs):
        with session_scope(system=True) as s:
            return fn(s, *args, **kwargs)
    return step


def _job() -> None:
    """Daily, once globally: classifications, prices (shared), then each user's snapshot; news and macro (shared);
    each user's alerts; Sundays also fundamentals and each opted-in user's weekly AI job."""
    from datetime import datetime

    from app.jobs import for_each_user, seed_all_sensitivities, snapshot_all
    from app.market.service import refresh_prices
    from app.services.alerts import evaluate_alerts
    from app.services.analysis import weekly_job
    from app.services.classification import refresh_classification
    from app.services.fundamentals import refresh_fundamentals
    from app.services.live import prune as prune_ticks
    from app.services.macro import refresh_macro
    from app.services.news import refresh_news
    from app.timeutil import IST

    sunday = datetime.now(IST).weekday() == 6
    run_job("classification", _system(refresh_classification))
    run_job("seed_sensitivities", seed_all_sensitivities)
    if sunday:
        run_job("fundamentals", _system(refresh_fundamentals))
    run_job("prices", _system(lambda s: refresh_prices(s, trigger="scheduled")))
    run_job("snapshots", snapshot_all)  # from shared prices (cached ones if the refresh failed)
    run_job("news", _system(refresh_news))
    run_job("macro", _system(refresh_macro))
    run_job("alerts", lambda: for_each_user("alerts", evaluate_alerts))
    run_job("intraday_retention", _system(lambda s: {"summary": f"{prune_ticks(s)} old ticks removed"}))
    if sunday:
        run_job("weekly_ai", lambda: for_each_user("weekly_ai", weekly_job))


LIVE_TICK_SECONDS = 15


def _live_tick() -> None:
    """Every 15 s: poll intraday quotes if live prices are on, the market is open, someone is watching and a poll
    is due (interval/backoff). Quiet when nothing happens; each real poll logs one live_poll line."""
    from app.services.live import scheduler_tick

    from app.jobs import job_lock

    try:
        with job_lock("live_prices") as mine:
            if not mine:
                return
            with session_scope(system=True) as s:
                res = scheduler_tick(s)
            if not res.get("ran"):
                log.debug("live_tick skipped", extra={"fields": {"reason": res.get("reason")}})
    except Exception:
        event(log, "live_tick", logging.ERROR, exc_info=True, outcome="failed")


def start_scheduler() -> BackgroundScheduler | None:
    st = get_settings()
    if not st.scheduler_enabled:
        return None
    sched = BackgroundScheduler(timezone="Asia/Kolkata")
    sched.add_job(_job, CronTrigger(hour=st.refresh_hour, minute=st.refresh_minute, timezone="Asia/Kolkata"),
                  id="daily_refresh", replace_existing=True, misfire_grace_time=3600)
    from apscheduler.triggers.interval import IntervalTrigger

    sched.add_job(_live_tick, IntervalTrigger(seconds=LIVE_TICK_SECONDS), id="live_prices", replace_existing=True,
                  max_instances=1, coalesce=True)
    sched.start()
    event(log, "scheduler_started", live_tick_s=LIVE_TICK_SECONDS, daily_at=f"{st.refresh_hour:02d}:{st.refresh_minute:02d} IST")
    return sched
