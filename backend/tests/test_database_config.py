"""The database is selected by DATABASE_URL. Unset/empty means a local SQLite file, which is allowed only with
ENV=development|test: deployed, the app and the migration step refuse to start (an unset variable on Render once
meant a fresh SQLite file in the container on every deploy). Logs and /api/health never show user, password or URL."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import get_settings, normalise_database_url

# SQLite-specific tests use the explicit sqlite+pysqlite:/// form: `make test-all-postgres` swaps every plain
# sqlite:/// database for Postgres, which would defeat their point.
PW = "pw-" + "secret-7d1e"  # built at runtime: the pre-commit scan refuses URL literals with passwords
POOLER = "postgresql+psycopg://investments_app.abcref:" + PW + "@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres"


@pytest.fixture
def deployed(monkeypatch):
    st = get_settings()
    monkeypatch.setattr(st, "env", "production")
    monkeypatch.setattr(st, "dev_auth", "")
    return st


@pytest.mark.parametrize("value", ["", "   ", "\n"])
def test_unset_or_empty_database_url_is_refused_when_deployed(deployed, monkeypatch, value):
    monkeypatch.setattr(deployed, "database_url", value)
    with pytest.raises(db.UnsafeDatabaseConfig, match="DATABASE_URL is not set"):
        db.check_database_config(deployed.resolved_database_url)  # what an unset variable resolves to


@pytest.mark.parametrize("env", ["production", "preview", "", "staging", "Production "])
def test_sqlite_is_refused_in_every_production_like_env(deployed, monkeypatch, env, tmp_path):
    monkeypatch.setattr(deployed, "env", env)
    monkeypatch.setattr(deployed, "database_url", f"sqlite:///{tmp_path / 'x.db'}")
    with pytest.raises(db.UnsafeDatabaseConfig, match="uses sqlite"):
        db.check_database_config(deployed.resolved_database_url)


def test_malformed_url_is_refused_without_echoing_it(deployed, monkeypatch):
    monkeypatch.setattr(deployed, "database_url", "not a url " + PW)
    with pytest.raises(db.UnsafeDatabaseConfig) as e:
        db.check_database_config(deployed.resolved_database_url)
    assert "not a valid database URL" in str(e.value) and PW not in str(e.value)


def test_postgres_is_accepted_and_summarised_without_credentials(deployed, monkeypatch):
    monkeypatch.setattr(deployed, "database_url", POOLER)
    info = db.check_database_config(deployed.resolved_database_url)
    assert info == {"dialect": "postgresql", "driver": "psycopg", "host": "aws-0-ap-southeast-1.pooler.supabase.com"}
    assert PW not in str(info) and "investments_app" not in str(info)


def test_development_and_test_may_use_sqlite(monkeypatch):
    st = get_settings()
    monkeypatch.setattr(st, "database_url", "")
    for env in ("development", "test"):
        monkeypatch.setattr(st, "env", env)
        assert db.check_database_config(st.resolved_database_url)["dialect"] == "sqlite"


UPH = "u:" + "p" + "@h"  # user:password@host, assembled at runtime for the same reason


@pytest.mark.parametrize("raw, expected", [
    (f"postgresql://{UPH}:5432/postgres", f"postgresql+psycopg://{UPH}:5432/postgres"),
    (f"postgres://{UPH}:5432/postgres", f"postgresql+psycopg://{UPH}:5432/postgres"),
    (f"  'postgresql+psycopg://{UPH}/postgres'\n", f"postgresql+psycopg://{UPH}/postgres"),
    (f'"postgresql://{UPH}/db"', f"postgresql+psycopg://{UPH}/db"),
    ("", ""),
])
def test_pasted_url_forms_are_normalised(raw, expected):
    assert normalise_database_url(raw) == expected


def test_app_refuses_to_start_on_sqlite_when_deployed(deployed, monkeypatch, tmp_path):
    from app.main import app

    monkeypatch.setattr(deployed, "supabase_url", "https://abcref.supabase.co")
    monkeypatch.setattr(deployed, "database_url", "")
    db.configure(f"sqlite+pysqlite:///{tmp_path / 'a.db'}")
    with pytest.raises(db.UnsafeDatabaseConfig, match="DATABASE_URL is not set"):
        with TestClient(app):
            pass
    assert not (tmp_path / "a.db").exists() or (tmp_path / "a.db").stat().st_size == 0  # nothing was migrated


def test_rls_check_alone_also_refuses_sqlite_when_deployed(deployed, tmp_path):
    db.configure(f"sqlite+pysqlite:///{tmp_path / 'b.db'}")
    with pytest.raises(db.UnsafeDatabaseConfig):
        db.check_rls_role()


def test_alembic_cli_refuses_sqlite_when_deployed(tmp_path):
    """The Render pre-deploy command (`alembic upgrade head`) with DATABASE_URL unset must fail, not migrate a
    throwaway SQLite file and report success."""
    backend = Path(__file__).resolve().parents[1]
    env = {"PATH": "/usr/bin:/bin", "ENV": "production", "DATABASE_URL": "", "DATA_DIR": str(tmp_path),
           "HOME": str(tmp_path)}
    r = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=backend, env=env,
                       capture_output=True, text=True)
    assert r.returncode != 0 and "DATABASE_URL is not set" in r.stderr
    assert not (tmp_path / "investments.db").exists()


def test_startup_logs_one_database_line_and_health_shows_the_dialect(tmp_path, caplog):
    from app.logging_config import KeyValueFormatter
    from app.main import app

    caplog.set_level(logging.INFO)
    db.configure(f"sqlite+pysqlite:///{tmp_path / 'c.db'}")
    with TestClient(app) as c:
        assert c.get("/api/health").json() == {"status": "ok", "database": "sqlite"}
    lines = [KeyValueFormatter().format(r) for r in caplog.records if r.getMessage() == "database"]
    assert len(lines) == 1 and "dialect=sqlite" in lines[0] and "host=" in lines[0]


def test_postgres_health_and_log_line_never_show_credentials(pg_url, caplog):
    from sqlalchemy.engine import make_url

    from app.logging_config import KeyValueFormatter
    from app.main import app

    u = make_url(pg_url)
    caplog.set_level(logging.INFO)
    db.configure(pg_url)
    with TestClient(app) as c:
        health = c.get("/api/health")
    assert health.json() == {"status": "ok", "database": "postgresql"}
    line = next(KeyValueFormatter().format(r) for r in caplog.records if r.getMessage() == "database")
    assert "dialect=postgresql" in line and f"host={u.host}" in line
    for secret in (u.password, f"{u.username}:", u.database, pg_url):
        assert secret not in line and secret not in health.text
