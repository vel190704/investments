import shutil
import sqlite3

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, func, select, text

from app import db
from app.config import REPO_ROOT
from app.db import Base
from app.migrate import BASELINE, backup_sqlite, current_state, head_revision, migrate
from app.models import Instrument, Transaction

REAL_DB = REPO_ROOT / "data" / "investments.db"


def test_models_and_migrations_have_no_drift(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    migrate(engine, backup=False)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert diff == []


def test_empty_db_upgrades_to_head(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'e.db'}")
    res = migrate(engine)
    assert res["to"] == head_revision() and res["backup"] is None  # nothing to back up
    assert current_state(engine)[0] == head_revision()


def _phase1_db(path):
    """Simulate a Phase 1 database: built with create_all at the baseline schema, no alembic_version."""
    engine = create_engine(f"sqlite:///{path}")
    from alembic import command
    from app.migrate import alembic_config

    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, BASELINE)
        conn.execute(text("DROP TABLE alembic_version"))
        conn.execute(text("INSERT INTO instruments (id, instrument_key, asset_type, name, symbol, exposure, "
                          "created_at, updated_at) VALUES (1, 'EQ:LT', 'STOCK', 'Larsen & Toubro', 'LT', "
                          "'DOMESTIC', '2026-10-03', '2026-10-03')"))
        conn.execute(text("INSERT INTO transactions (instrument_id, date, type, quantity, price, amount_paise, "
                          "charges_paise, platform, source, row_key, imported_at) VALUES (1, '2026-10-03', "
                          "'OPENING', '1', '3768', 376800, 0, 'Groww', 'excel', 'k#1', '2026-10-03')"))
    return engine


def test_phase1_database_is_stamped_backed_up_and_preserved(tmp_path, monkeypatch):
    from app import config

    monkeypatch.setattr(config.get_settings(), "data_dir", tmp_path)
    engine = _phase1_db(tmp_path / "p1.db")
    res = migrate(engine)
    assert res["stamped_baseline"] and res["to"] == head_revision()
    assert res["backup"] and (tmp_path / "backups").exists()
    with engine.connect() as conn:
        assert conn.execute(text("SELECT amount_paise, source FROM transactions")).one() == (376800, "excel")
        assert conn.execute(text("SELECT name FROM instruments")).scalar() == "Larsen & Toubro"
    # the backup is a readable copy of the pre-migration DB
    with sqlite3.connect(res["backup"]) as b:
        assert b.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
    # running again is a no-op
    assert migrate(engine)["backup"] is None


def test_backup_includes_wal_contents(tmp_path):
    path = tmp_path / "w.db"
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE t (x)")
    con.execute("INSERT INTO t VALUES (42)")
    con.commit()  # data may still live only in the -wal file
    out = backup_sqlite(path, "test", backup_dir=tmp_path / "b")
    con.close()
    assert sqlite3.connect(out).execute("SELECT x FROM t").fetchone()[0] == 42


@pytest.mark.skipif(not REAL_DB.exists(), reason="no local database")
def test_real_database_copy_migrates_with_data_preserved(tmp_path, monkeypatch):
    from app import config

    monkeypatch.setattr(config.get_settings(), "data_dir", tmp_path)
    copy = tmp_path / "copy.db"
    backup_sqlite(REAL_DB, "src", backup_dir=tmp_path)  # consistent snapshot of the live file
    shutil.copy(next(tmp_path.glob("investments-*-src.db")), copy)
    with sqlite3.connect(copy) as c:
        before = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("instruments", "transactions", "price_quotes", "identifier_candidates")}
    db.configure(f"sqlite:///{copy}")
    db.init_db()
    with db.session_scope() as s:
        assert s.scalar(select(func.count()).select_from(Transaction)) == before["transactions"]
        assert s.scalar(select(func.count()).select_from(Instrument)) == before["instruments"]
    with sqlite3.connect(copy) as c:
        for t, n in before.items():
            assert c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == n


def test_transaction_source_check_constraint(session, workbook):
    from sqlalchemy.exc import IntegrityError

    from app.importer.run import import_workbook

    import_workbook(session, workbook)
    with pytest.raises(IntegrityError):
        session.execute(text("UPDATE transactions SET source = 'nonsense'"))
        session.flush()
