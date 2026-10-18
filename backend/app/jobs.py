"""Background jobs run ONCE globally (not per user): market data for the union of securities any user holds;
per-user steps (snapshots, alerts, starter tags, weekly AI) loop users, each in its own user-bound session.

`job_lock(name)` makes sure two app instances never run the same job at once: a Postgres advisory lock
(pg_try_advisory_lock on a dedicated connection) or, on SQLite (single local instance), a process lock.
"""

from __future__ import annotations

import logging
import threading
import zlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy import select, text

from app.db import get_engine, session_scope
from app.logging_config import event

log = logging.getLogger("app.jobs")
_local_locks: dict[str, threading.Lock] = {}
_local_guard = threading.Lock()


def lock_key(name: str) -> int:
    """Stable signed 32-bit key for pg advisory locks."""
    v = zlib.crc32(f"investments-job:{name}".encode())
    return v - (1 << 32) if v >= (1 << 31) else v


@contextmanager
def job_lock(name: str) -> Iterator[bool]:
    """Yields True if this process holds the lock (run the job), False if another holder has it (skip)."""
    engine = get_engine()
    if engine.dialect.name == "postgresql":
        with engine.connect() as conn:
            got = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": lock_key(name)}).scalar())
            try:
                yield got
            finally:
                if got:
                    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": lock_key(name)})
                conn.commit()
        return
    with _local_guard:
        lk = _local_locks.setdefault(name, threading.Lock())
    got = lk.acquire(blocking=False)
    try:
        yield got
    finally:
        if got:
            lk.release()


def user_ids() -> list[int]:
    from app.models import User

    with session_scope(system=True) as s:
        return list(s.scalars(select(User.id).order_by(User.id)))


def for_each_user(name: str, fn: Callable) -> dict:
    """Run fn(session) for every user in that user's own session; one user's failure doesn't stop the others."""
    ok, failed = 0, []
    for uid in user_ids():
        try:
            with session_scope(user_id=uid) as s:
                fn(s)
            ok += 1
        except Exception:
            failed.append(uid)
            event(log, "job_user_step_failed", logging.ERROR, exc_info=True, job=name, target_user_id=uid)
    return {"ok_count": ok, "error_count": len(failed), "summary": f"{ok} users ok, {len(failed)} failed"}


def snapshot_all(trigger: str = "scheduled") -> dict:
    from app.services.snapshots import take_snapshot

    return for_each_user("snapshots", lambda s: take_snapshot(s, trigger=trigger))


def first_snapshots() -> dict:
    """Users with data but no snapshot yet get one from cached prices (was a single-user start-up step)."""
    from sqlalchemy import func

    from app.models import PortfolioSnapshot
    from app.services.snapshots import take_snapshot

    def step(s):
        if not s.scalar(select(func.count()).select_from(PortfolioSnapshot)):
            take_snapshot(s, trigger="startup")
    return for_each_user("first_snapshots", step)


def seed_all_sensitivities() -> dict:
    from app.services.macro import seed_starter_sensitivities

    return for_each_user("seed_sensitivities", seed_starter_sensitivities)


def catch_up_global(today) -> dict:
    """After downtime: record missed dates as (global) gaps, refresh shared prices once, snapshot every user."""
    from app.services.catchup import catch_up

    with session_scope(system=True) as s:
        res = catch_up(s, today)
    if res["ran"]:
        res["snapshots"] = snapshot_all(trigger="startup")
    return res
