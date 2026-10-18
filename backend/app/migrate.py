"""Schema migrations (Alembic) + SQLite backups.

`migrate()` is called by `init_db()` on every start:
- a DB created by Phase 1 (`create_all`, no `alembic_version`) is stamped as the baseline;
- if migrations are pending and the DB is a SQLite file with data, it is backed up first
  (data/backups/, via SQLite's online backup API so WAL contents are included);
- then `alembic upgrade head` runs.
CLI: `python -m app.migrate [--backup-only]`.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from app.config import get_settings

log = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parents[1]
BASELINE = "0001_baseline"


def alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def sqlite_path(engine: Engine) -> Path | None:
    if engine.url.get_backend_name() != "sqlite":
        return None
    db = engine.url.database
    return Path(db) if db and db != ":memory:" else None


def backup_sqlite(path: Path, label: str = "manual", backup_dir: Path | None = None) -> Path:
    """Consistent copy of a live SQLite DB (includes WAL) into data/backups/."""
    backup_dir = backup_dir or get_settings().data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"{path.stem}-{stamp}-{label}.db"
    src = sqlite3.connect(path)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


def current_state(engine: Engine) -> tuple[str | None, list[str]]:
    with engine.connect() as conn:
        rev = MigrationContext.configure(conn).get_current_revision()
        tables = inspect(conn).get_table_names()
    return rev, tables


def migrate(engine: Engine, backup: bool = True) -> dict:
    cfg = alembic_config()
    head = head_revision()
    rev, tables = current_state(engine)
    result = {"from": rev, "to": head, "stamped_baseline": False, "backup": None}

    if rev is None and "instruments" in tables:
        # Phase 1 database created with create_all(): it matches the baseline exactly.
        with engine.begin() as conn:
            cfg.attributes["connection"] = conn
            command.stamp(cfg, BASELINE)
        rev = BASELINE
        result["stamped_baseline"] = True

    if rev == head:
        return result

    path = sqlite_path(engine)
    if backup and path is not None and path.exists() and tables:
        result["backup"] = str(backup_sqlite(path, label=f"pre-{head}"))
        log.info("Backed up %s to %s before migrating", path, result["backup"])

    with engine.connect() as conn:
        if conn.dialect.name == "sqlite":  # batch migrations rebuild referenced tables: no FK checks meanwhile
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.commit()
        with conn.begin():
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
        if conn.dialect.name == "sqlite":
            bad = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
            conn.commit()
            if bad:
                raise RuntimeError(f"foreign key problems after migration: {bad[:5]}")
    log.info("Migrated database from %s to %s", rev, head)
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Apply migrations or back up the database.")
    ap.add_argument("--backup-only", action="store_true")
    args = ap.parse_args(argv)
    from app.db import get_engine

    engine = get_engine()
    path = sqlite_path(engine)
    if args.backup_only:
        if path is None or not path.exists():
            print("No SQLite database file to back up.")
            return 1
        print(f"Backup written: {backup_sqlite(path)}")
        return 0
    res = migrate(engine)
    print(f"Database at revision {res['to']} (was {res['from'] or 'unversioned'})"
          + (" — stamped Phase 1 baseline" if res["stamped_baseline"] else "")
          + (f"; backup: {res['backup']}" if res["backup"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
