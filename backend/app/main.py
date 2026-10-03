"""FastAPI app. Run bound to 127.0.0.1 only (see Makefile)."""

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.config import get_settings
from app.db import init_db, session_scope

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def _startup_refresh() -> None:
    from app.market.service import refresh_if_stale

    try:
        with session_scope() as s:
            res = refresh_if_stale(s, get_settings().startup_refresh_max_age_hours)
        if res:
            log.info("Start-up refresh: %s ok, %s errors", res["ok_count"], res["error_count"])
    except Exception:
        log.exception("Start-up refresh failed")


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
app.include_router(router)
