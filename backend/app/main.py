"""FastAPI app. Run bound to 127.0.0.1 only (see Makefile)."""

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.middleware import install as install_middleware
from app.api.routes import router
from app.config import get_settings
from app.db import init_db, session_scope
from app.logging_config import configure_logging, event

configure_logging()
log = logging.getLogger(__name__)


def _startup_refresh() -> None:
    """Catch up after downtime (prices + today's snapshot + honest gaps), else refresh if quotes are stale."""
    from sqlalchemy import func, select

    from app.market.service import refresh_if_stale
    from app.models import Instrument
    from app.timeutil import today_ist

    from app.jobs import catch_up_global, job_lock

    try:
        with job_lock("startup_refresh") as mine:
            if not mine:
                event(log, "startup_refresh", skipped="another instance is running it")
                return
            with session_scope(system=True) as s:
                if not s.scalar(select(func.count()).select_from(Instrument)):
                    return
            res = catch_up_global(today_ist())
            if res["ran"]:
                r = res["refresh"] or {}
                event(log, "startup_catchup", gaps=len(res["gaps_recorded"]), gap_dates=res["gaps_recorded"],
                      refresh_ok=r.get("ok_count"), refresh_errors=r.get("error_count"))
                return
            with session_scope(system=True) as s:
                res = refresh_if_stale(s, get_settings().startup_refresh_max_age_hours)
        if res:
            event(log, "startup_refresh", refresh_ok=res["ok_count"], refresh_errors=res["error_count"])
        else:
            event(log, "startup_refresh", skipped="prices are fresh")
    except Exception:
        event(log, "startup_refresh", logging.ERROR, exc_info=True, outcome="failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.auth import check_startup_config
    from app.jobs import first_snapshots, seed_all_sensitivities

    check_startup_config()  # refuses dev auth outside development/test
    from app.db import check_rls_role

    role = check_rls_role()  # before any migration: refuses (outside dev/test) a Postgres role that bypasses RLS
    if role:
        event(log, "database_role", **role)
    init_db()
    for name, fn in (("seed_sensitivities", seed_all_sensitivities), ("first_snapshots", first_snapshots)):
        try:
            res = fn()
            event(log, name, **res)
        except Exception:
            event(log, name, logging.ERROR, exc_info=True, outcome="failed")
    sched = None
    if get_settings().scheduler_enabled:
        from app.scheduler import start_scheduler

        sched = start_scheduler()
        threading.Thread(target=_startup_refresh, daemon=True).start()
    yield
    if sched:
        sched.shutdown(wait=False)


app = FastAPI(title="Personal Investment Dashboard", version="0.1.0", lifespan=lifespan)
install_middleware(app)
app.include_router(router)
