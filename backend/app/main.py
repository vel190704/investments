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


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
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
