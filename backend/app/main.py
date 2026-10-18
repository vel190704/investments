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
    from app.services.catchup import catch_up
    from app.timeutil import today_ist

    try:
        with session_scope() as s:
            if not s.scalar(select(func.count()).select_from(Instrument)):
                return
            res = catch_up(s, today_ist())
            if res["ran"]:
                r = res["refresh"] or {}
                event(log, "startup_catchup", gaps=len(res["gaps_recorded"]), gap_dates=res["gaps_recorded"],
                      refresh_ok=r.get("ok_count"), refresh_errors=r.get("error_count"))
                return
            res = refresh_if_stale(s, get_settings().startup_refresh_max_age_hours)
        if res:
            event(log, "startup_refresh", refresh_ok=res["ok_count"], refresh_errors=res["error_count"])
        else:
            event(log, "startup_refresh", skipped="prices are fresh")
    except Exception:
        event(log, "startup_refresh", logging.ERROR, exc_info=True, outcome="failed")


def ensure_first_snapshot() -> dict | None:
    """Phase 2: if no snapshot exists yet, store one immediately from cached prices."""
    from sqlalchemy import func, select

    from app.models import PortfolioSnapshot
    from app.services.snapshots import take_snapshot

    with session_scope() as s:
        if s.scalar(select(func.count()).select_from(PortfolioSnapshot)):
            return None
        return take_snapshot(s, trigger="startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        from app.services.macro import seed_starter_sensitivities

        with session_scope() as s:
            seed_starter_sensitivities(s)
    except Exception:
        log.exception("Seeding starter sensitivity tags failed")
    try:
        first = ensure_first_snapshot()
        if first:
            log.info("Stored first snapshot for %s", first["snapshot_date"])
    except Exception:
        log.exception("First snapshot failed")
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
