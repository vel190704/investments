"""Postgres-only checks (skipped without TEST_POSTGRES_URL): migrations, Row Level Security, advisory locks, and the
full cross-user attack on Postgres."""

import threading

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app import db
from app.db import Base
from tests.conftest import make_user


def test_migrations_apply_on_postgres_without_drift(pg_url):
    db.configure(pg_url)
    db.init_db()
    with db.get_engine().connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata) == []
        rls = dict(conn.execute(text("SELECT relname, relforcerowsecurity FROM pg_class WHERE relname IN "
                                     "('transactions', 'app_settings', 'price_quotes')")).all())
    assert rls == {"transactions": True, "app_settings": True, "price_quotes": False}


def test_row_level_security_isolates_users_for_a_non_superuser_role(pg_url):
    """Defence in depth: even raw SQL without any WHERE clause sees only the current user's rows."""
    db.configure(pg_url)
    db.init_db()
    a, b = make_user("alice@example.com"), make_user("bob@example.com")
    from app.models import AppSetting

    for uid in (a, b):
        with db.session_scope(user_id=uid) as s:
            s.add(AppSetting(key="drift", value={"tolerance_pp": str(uid)}))
    with db.get_engine().begin() as c:  # an app role WITHOUT bypassrls, like production (docs/DEPLOY.md)
        c.execute(text("DROP ROLE IF EXISTS rls_app; CREATE ROLE rls_app LOGIN PASSWORD 'x' NOSUPERUSER NOBYPASSRLS"))
        c.execute(text("GRANT ALL ON ALL TABLES IN SCHEMA public TO rls_app; "
                       "GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO rls_app"))
    app_url = make_url(pg_url).set(username="rls_app", password="x")
    eng = create_engine(app_url)
    try:
        with eng.begin() as c:
            c.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(a)})
            rows = c.execute(text("SELECT user_id FROM app_settings")).scalars().all()
            assert rows == [a]  # no WHERE clause, still only Alice's row
            with pytest.raises(Exception):  # WITH CHECK: cannot write a row for Bob
                with c.begin_nested():
                    c.execute(text("INSERT INTO app_settings (user_id, key, value, updated_at) "
                                   "VALUES (:b, 'themes', '{}', now())"), {"b": b})
        with eng.begin() as c:
            assert c.execute(text("SELECT count(*) FROM app_settings")).scalar() == 0  # no user set: nothing
        with eng.begin() as c:
            c.execute(text("SELECT set_config('app.system', 'on', true)"))
            assert c.execute(text("SELECT count(*) FROM app_settings")).scalar() == 2
    finally:
        eng.dispose()
        with db.get_engine().begin() as c:
            c.execute(text("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM rls_app; "
                           "REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM rls_app; DROP ROLE rls_app"))


def test_advisory_lock_lets_only_one_holder_run_a_job(pg_url):
    from app.jobs import job_lock

    db.configure(pg_url)
    db.init_db()
    holding, release, results = threading.Event(), threading.Event(), []

    def first():
        with job_lock("prices") as mine:
            results.append(("first", mine))
            holding.set()
            release.wait(10)

    t = threading.Thread(target=first)
    t.start()
    holding.wait(10)
    with job_lock("prices") as mine:  # a second instance at the same time
        results.append(("second", mine))
    with job_lock("news") as mine:  # a different job is independent
        results.append(("other", mine))
    release.set()
    t.join(10)
    with job_lock("prices") as mine:  # released afterwards
        results.append(("later", mine))
    assert results == [("first", True), ("second", False), ("other", True), ("later", True)]


def test_cross_user_attack_on_postgres(pg_url, tmp_path, monkeypatch):
    """The same every-route attack as tests/test_isolation.py, on Postgres (with RLS in place)."""
    from fastapi.testclient import TestClient

    from app.main import app
    from tests import test_isolation as iso

    db.configure(pg_url)
    iso._offline(monkeypatch)
    with TestClient(app) as c:
        a_book = iso.write_workbook(tmp_path / "alice.xlsx")
        b_book = iso.write_workbook(tmp_path / "bob.xlsx", txn_rows=iso.bob_rows())
        for who, book in ((iso.ALICE, a_book), (iso.BOB, b_book)):
            r = c.post("/api/import", headers={"X-Dev-User": who}, files={"file": ("w.xlsx", book.read_bytes())})
            assert r.status_code == 200 and r.json()["report"]["ok"], r.text
        ids = iso._bob_objects(c, tmp_path, b_book)
        problems, changed, covered = iso._attack(c, ids, a_book)
    assert problems == [] and changed == {} and len(covered) > 80


def test_sqlite_to_postgres_tool_keeps_totals_identical(pg_url, tmp_path, workbook):
    """A single-user (pre-Phase-6 shape) SQLite file moves into one Postgres account with identical totals."""
    from app.importer.run import import_workbook
    from app.market.base import Quote
    from app.market.service import store_quote
    from app.models import Instrument
    from app.services.snapshots import take_snapshot
    from app.tools import sqlite_to_postgres as tool
    from datetime import date
    from decimal import Decimal as D
    from sqlalchemy import select

    src = tmp_path / "single.db"
    db.configure(f"sqlite:///{src}")
    db.init_db()
    uid = make_user("owner@localhost")  # what 0008 names the owner of a single-user file
    with db.session_scope(user_id=uid) as s:
        assert import_workbook(s, workbook)["ok"]
        for i in s.scalars(select(Instrument).where(Instrument.symbol.is_not(None))):
            store_quote(s, i.id, Quote(D("123.45"), date(2026, 10, 16), "t", i.symbol, D("120")))
        take_snapshot(s, on_date=date(2026, 10, 16))
    db.get_engine().dispose()
    assert tool.main(["--sqlite", str(src), "--postgres", pg_url, "--owner-email", "me@example.com"]) == 0
    with pytest.raises(SystemExit, match="already has accounts"):  # never into a database that has accounts
        tool.copy_all(f"sqlite:///{src}", pg_url, "me@example.com")
