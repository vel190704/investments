"""Behind a TRANSACTION-mode pooler (PgBouncer; like Supabase's port-6543 pooler), many clients share a few server
connections. The per-request user context must therefore live in the transaction (set_config(..., true) = SET LOCAL),
never in the session, or a later client on the same server connection could inherit it.

Needs the test stack in tests/pooler/docker-compose.yml (`make test-pooler`); skipped otherwise.
"""

from __future__ import annotations

import os
import random
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, text

from app import db

POOLED = os.environ.get("TEST_POOLER_URL")  # app role through PgBouncer (transaction mode)
DIRECT = os.environ.get("TEST_POOLER_DIRECT_URL")  # app role straight to Postgres (migrations)
pytestmark = pytest.mark.skipif(not (POOLED and DIRECT), reason="pooler stack not running (make test-pooler)")


@pytest.fixture(scope="module")
def migrated():
    """Fresh schema in the pooler stack's database, migrated over the DIRECT connection (DDL never via a
    transaction pooler), then two users with a settings row each."""
    eng = create_engine(DIRECT)
    with eng.begin() as c:
        c.execute(text("SELECT set_config('app.system', 'on', true)"))
        c.execute(text("DROP OWNED BY pooler_app CASCADE"))  # the role's own tables from a previous run
    eng.dispose()
    db.configure(DIRECT)
    db.init_db()
    from tests.conftest import make_user
    from app.models import AppSetting

    a, b = make_user("alice@example.com"), make_user("bob@example.com")
    for uid in (a, b):
        with db.session_scope(user_id=uid) as s:
            s.add(AppSetting(key="drift", value={"tolerance_pp": str(uid)}))
    db.get_engine().dispose()
    return a, b


def _pollute(engine, uid: int, n: int = 12) -> None:
    """Leave a SESSION-level app.user_id on the pooled server connections (what a careless client, or a psql
    session through the same pooler, could do). The app must be immune to it."""
    def one(_):
        with engine.begin() as c:
            c.execute(text("SELECT set_config('app.user_id', :u, false)"), {"u": str(uid)})
    with ThreadPoolExecutor(n) as ex:
        list(ex.map(one, range(n)))


def _app_tx(c, uid: int | None) -> set:
    """Exactly what app/tenancy.py does at the start of every transaction, then an unfiltered read."""
    c.execute(text("SELECT set_config('app.user_id', :u, true), set_config('app.system', 'off', true)"),
              {"u": "" if uid is None else str(uid)})
    return set(c.execute(text("SELECT user_id FROM app_settings")).scalars())


def test_transaction_local_context_never_crosses_users_through_the_pooler(migrated):
    a, b = migrated
    eng = create_engine(POOLED, connect_args={"prepare_threshold": None}, pool_size=40, max_overflow=0)
    problems, lock = [], threading.Lock()
    try:
        with eng.connect() as c:  # really through the pooler, as the app role
            assert c.execute(text("SELECT current_user")).scalar() == "pooler_app"
        _pollute(eng, b)  # worst case: every pooled server connection carries Bob's id at session level

        def worker(_):
            rnd = random.Random()
            for _ in range(25):
                uid = rnd.choice((a, b))
                with eng.begin() as c:
                    seen = _app_tx(c, uid)
                if seen != {uid}:
                    with lock:
                        problems.append(f"as {uid} saw {sorted(seen)}")
                with eng.begin() as c:  # a no-user transaction, as the app runs it: must see nothing
                    seen = _app_tx(c, None)
                if seen:
                    with lock:
                        problems.append(f"no user, saw {sorted(seen)}")

        with ThreadPoolExecutor(32) as ex:
            list(ex.map(worker, range(32)))
    finally:
        eng.dispose()
    assert problems == []  # 800 user transactions + 800 no-user transactions over 4 shared server connections


def test_negative_control_session_level_settings_do_leak_through_the_pooler(migrated):
    """Why the app must use transaction-local settings: a session-level value set by one client is visible to
    other clients' later transactions on the same pooled server connection. (Uses a probe setting the app never
    reads, so it cannot contaminate the app's own context.)"""
    eng = create_engine(POOLED, connect_args={"prepare_threshold": None}, pool_size=40, max_overflow=0)
    try:
        with ThreadPoolExecutor(12) as ex:
            list(ex.map(lambda _: _probe_set(eng), range(12)))
        seen = []
        for _ in range(40):
            with eng.begin() as c:
                seen.append(c.execute(text("SELECT current_setting('app.leak_probe', true)")).scalar())
        assert "left-over" in seen, "the pooler test could not detect session-level leakage"
    finally:
        eng.dispose()


def _probe_set(engine):
    with engine.begin() as c:
        c.execute(text("SELECT set_config('app.leak_probe', 'left-over', false)"))


def test_concurrent_requests_as_alternating_users_through_the_pooler(migrated, monkeypatch):
    """200 concurrent API requests as Alice and Bob through PgBouncer, with the application-level filter OFF so
    Postgres RLS (set per transaction) is the only thing keeping them apart."""
    from fastapi.testclient import TestClient
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    from app import tenancy
    from app.main import app

    a, b = migrated
    db.configure(POOLED)
    event.remove(Session, "do_orm_execute", tenancy._scope_to_user)
    try:
        with TestClient(app) as c:
            for who in ("alice@example.com", "bob@example.com"):  # each sets a distinctive drift tolerance
                assert c.put("/api/settings/drift", headers={"X-Dev-User": who},
                             json={"tolerance_pp": "7" if who.startswith("alice") else "9"}).status_code == 200
            plan = [random.choice(("alice@example.com", "bob@example.com")) for _ in range(200)]

            def call(who):
                r = c.get("/api/settings", headers={"X-Dev-User": who})
                got = r.json()["sections"]["drift"]["value"]["tolerance_pp"]
                return who, r.status_code, got

            with ThreadPoolExecutor(24) as ex:
                results = list(ex.map(call, plan))
    finally:
        event.listen(Session, "do_orm_execute", tenancy._scope_to_user)
        db.get_engine().dispose()
    wrong = [(w, s, g) for w, s, g in results if s != 200 or g != ("7" if w.startswith("alice") else "9")]
    assert wrong == [] and len(results) == 200


def test_job_lock_works_through_the_pooler(migrated):
    from app.jobs import job_lock

    db.configure(POOLED)
    try:
        holding, release, out = threading.Event(), threading.Event(), []

        def first():
            with job_lock("prices") as mine:
                out.append(mine)
                holding.set()
                release.wait(10)

        t = threading.Thread(target=first)
        t.start()
        holding.wait(10)
        with job_lock("prices") as mine:
            out.append(mine)
        release.set()
        t.join(10)
        with job_lock("prices") as mine:
            out.append(mine)
        assert out == [True, False, True]
    finally:
        db.get_engine().dispose()
