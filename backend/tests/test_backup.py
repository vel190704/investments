"""Backups end to end: encrypted dump with the read-only backup role, restore into a throwaway Postgres, verify against
the manifest (row counts + the app's own totals), and re-apply the deletion register after restoring an older dump.

Needs TEST_POSTGRES_URL, Docker and gpg (CI has all three; `make test-backup`)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url

from app import db
from app.tools import backup as bk

pytestmark = pytest.mark.skipif(
    not (os.environ.get("TEST_POSTGRES_URL") and shutil.which("docker") and shutil.which("gpg")),
    reason="needs TEST_POSTGRES_URL, docker and gpg (make test-backup)")
ME, BOB = "me@example.com", "bob@example.com"


@pytest.fixture
def gnupghome(tmp_path_factory):
    home = Path(f"/tmp/gpg-{uuid.uuid4().hex[:8]}")  # short path: gpg-agent socket paths are length-limited
    home.mkdir(mode=0o700)
    subprocess.run(["gpg", "--homedir", str(home), "--batch", "--passphrase", "", "--quick-gen-key",
                    "Backup Test <backup-test@example.invalid>", "default", "default", "never"],
                   check=True, capture_output=True)
    yield str(home)
    subprocess.run(["gpgconf", "--homedir", str(home), "--kill", "gpg-agent"], capture_output=True)
    shutil.rmtree(home, ignore_errors=True)


@pytest.fixture
def source(pg_url, workbook, tmp_path):
    """A 'production' database with two people's data, and the read-only backup role from deploy/backup_role.sql."""
    from app.importer.run import import_workbook
    from app.market.base import Quote
    from app.market.service import store_quote
    from app.models import Instrument
    from app.services.snapshots import take_snapshot
    from tests.conftest import make_user

    db.configure(pg_url)
    db.init_db()
    for email in (ME, BOB):
        uid = make_user(email)
        with db.session_scope(user_id=uid) as s:
            assert import_workbook(s, workbook)["ok"]
            for i in s.scalars(select(Instrument).where(Instrument.symbol.is_not(None))):
                store_quote(s, i.id, Quote(D("123.45"), date(2026, 10, 16), "t", i.symbol, D("120")))
            take_snapshot(s, on_date=date(2026, 10, 16))
    db.get_engine().dispose()
    role, pw = f"inv_backup_{uuid.uuid4().hex[:6]}", uuid.uuid4().hex
    sql = (Path(__file__).parents[1] / "deploy" / "backup_role.sql").read_text()
    sql = "\n".join(l for l in sql.splitlines() if not l.startswith("--"))
    sql = sql.replace("investments_backup", role).replace(":'backup_password'", f"'{pw}'")
    sql = sql.replace("FOR ROLE investments_app", "FOR ROLE postgres")  # the tables' owner in this test cluster
    admin = create_engine(pg_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        for stmt in filter(str.strip, sql.split(";")):
            c.execute(text(stmt))
    backup_url = make_url(pg_url).set(username=role, password=pw).render_as_string(hide_password=False)
    yield {"admin_url": pg_url, "backup_url": backup_url, "out": tmp_path / "backups"}
    db.configure("sqlite://")
    with admin.connect() as c:
        c.execute(text(f"DROP OWNED BY {role} CASCADE"))
        c.execute(text(f"DROP ROLE {role}"))
    admin.dispose()


def _backup(source, gnupghome):
    return bk.backup(source["backup_url"], source["out"], "backup-test@example.invalid", ME, gnupghome=gnupghome)


def test_backup_is_encrypted_outside_the_repo_and_restores_with_identical_totals(source, gnupghome):
    res = _backup(source, gnupghome)
    for p in (res["dump"], res["manifest"]):
        assert p.exists() and oct(p.stat().st_mode & 0o777) == "0o600"
        head = p.read_bytes()[:16]
        assert not head.startswith(b"PGDMP") and not head.startswith(b"{")  # never plaintext
    assert res["tables"] > 30 and res["rows"] > 100
    lines = []
    assert bk.restore_test(res["dump"], gnupghome, out=lines.append) == 0
    assert lines[0].endswith(": PASS") and "portfolio totals of the check user recomputed" in lines[0]


def test_verify_reports_a_mismatch(source, gnupghome):
    res = _backup(source, gnupghome)
    manifest = json.loads(bk._decrypt_bytes(res["manifest"], gnupghome))
    manifest["tables"]["transactions"] += 1
    manifest["check"]["totals"]["total_value_paise"] += 1
    with bk.restored(res["dump"], gnupghome) as url:
        problems = bk.verify(url, manifest)
    assert any(p.startswith("table transactions: expected") for p in problems)
    assert "portfolio totals of the check user differ from the backup-time values" in problems


def test_the_backup_role_is_read_only(source):
    eng = create_engine(source["backup_url"])
    try:
        with eng.connect() as c:
            assert c.execute(text("SELECT count(*) FROM transactions")).scalar() == 38  # sees every user's rows
            with pytest.raises(Exception, match="read-only|permission denied"):
                c.execute(text("DELETE FROM transactions"))
    finally:
        eng.dispose()


def test_refuses_to_write_inside_the_repository(source, gnupghome):
    with pytest.raises(SystemExit, match="inside the repository"):
        bk.backup(source["backup_url"], bk.REPO_ROOT / "data" / "x", "backup-test@example.invalid",
                  gnupghome=gnupghome)


def test_deletion_register_is_reapplied_after_restoring_an_older_dump(source, gnupghome, tmp_path):
    """Delete Bob, restore a dump made before that, re-apply the register: Bob is gone again, I am intact."""
    from app.models import Transaction, User
    from app.services.accounts import delete_user_data
    from app.tools.totals import user_id_for

    res = _backup(source, gnupghome)  # contains Bob
    db.configure(source["admin_url"])
    with db.session_scope(system=True) as s:
        bob_id = user_id_for(s, BOB)
        delete_user_data(s, bob_id)  # the live deletion
    db.get_engine().dispose()
    register = tmp_path / "private" / "deletions.csv"
    register.parent.mkdir()
    register.write_text(f"# private deletion register\ndeleted_at,user_id,email\n2026-10-18,{bob_id},{BOB}\n")
    manifest = json.loads(bk._decrypt_bytes(res["manifest"], gnupghome))
    with bk.restored(res["dump"], gnupghome) as url:
        eng = create_engine(url)
        with eng.connect() as c:
            assert c.execute(text("SELECT count(*) FROM users WHERE email = :e"), {"e": BOB}).scalar() == 1  # back
        eng.dispose()
        rep = bk.reapply_deletions(url, register, out=lambda _l: None)
        assert rep["reapplied"] == [bob_id]
        db.configure(url)
        with db.session_scope(system=True) as s:
            assert s.scalar(select(func.count()).select_from(User).where(User.email == BOB)) == 0
            assert s.scalar(select(func.count()).select_from(Transaction).where(Transaction.user_id == bob_id)) == 0
            me = user_id_for(s, ME)
        from app.tools.totals import totals_in_session
        with db.session_scope(user_id=me) as s:
            assert json.loads(json.dumps(totals_in_session(s))) == manifest["check"]["totals"]  # I am untouched
        db.get_engine().dispose()
        db.configure("sqlite://")
        assert bk.reapply_deletions(url, register, out=lambda _l: None)["absent"] == [str(bob_id)]  # idempotent
    with pytest.raises(SystemExit, match="inside the repository"):
        bk.read_register(bk.REPO_ROOT / "deletions.csv")


def test_prune_deletes_dumps_older_than_the_stated_retention(tmp_path):
    from datetime import UTC, datetime

    d = tmp_path / "b"
    d.mkdir()
    for stamp in ("20260901T010000Z", "20261009T010000Z", "20261017T010000Z"):
        (d / f"investments-{stamp}{bk.DUMP_SUFFIX}").write_bytes(b"x")
        (d / f"investments-{stamp}{bk.MANIFEST_SUFFIX}").write_bytes(b"x")
    removed = bk.prune(d, 7, now=datetime(2026, 10, 18, tzinfo=UTC))
    assert [p.name for p in removed] == [f"investments-20260901T010000Z{bk.DUMP_SUFFIX}",
                                         f"investments-20261009T010000Z{bk.DUMP_SUFFIX}"]
    assert sorted(p.name for p in d.iterdir()) == [f"investments-20261017T010000Z{bk.DUMP_SUFFIX}",
                                                   f"investments-20261017T010000Z{bk.MANIFEST_SUFFIX}"]
