"""Engine/session factory. The only module that knows which database is in use."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    is_sqlite = url.startswith("sqlite")
    engine = create_engine(
        url,
        # Postgres: no server-side prepared statements (Supabase's transaction pooler can't keep them)
        connect_args={"check_same_thread": False} if is_sqlite else {"prepare_threshold": None},
        pool_pre_ping=not is_sqlite,
        future=True,
    )
    if is_sqlite:
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()
    return engine


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def configure(url: str | None = None) -> Engine:
    """(Re)configure the global engine. Tests call this with an in-memory/temp URL."""
    global _engine, _SessionLocal
    settings = get_settings()
    url = url or settings.resolved_database_url
    if url.startswith("sqlite:///"):
        from pathlib import Path

        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    _engine = make_engine(url)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        configure()
    assert _engine is not None
    return _engine


def init_db() -> None:
    """Bring the schema to the latest migration (backing up a file DB first if needed)."""
    from app import models  # noqa: F401  (register tables)
    from app.migrate import migrate

    migrate(get_engine())


@contextmanager
def session_scope(user_id: int | None = None, system: bool = False) -> Iterator[Session]:
    """A unit of work for one user (`user_id`) or an explicit system job (`system=True`).
    Per-user tables are filtered and stamped by app/tenancy.py; with neither set they are off limits."""
    import app.tenancy  # noqa: F401  (registers the isolation events)

    if _SessionLocal is None:
        configure()
    assert _SessionLocal is not None
    session = _SessionLocal(info={"user_id": user_id, "system": system})
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class UnsafeDatabaseRole(RuntimeError):
    pass


class UnsafeDatabaseConfig(RuntimeError):
    pass


def database_summary(url=None) -> dict:
    """Dialect, driver and host of a database URL (default: the configured engine's): never the user, password,
    database name or URL."""
    from sqlalchemy.engine import make_url

    u = make_url(url) if url is not None else get_engine().url
    return {"dialect": u.get_backend_name(), "driver": u.get_driver_name(), "host": u.host or "(local file)"}


def check_database_config(url: str | None = None) -> dict:
    """Outside ENV=development|test the database must be PostgreSQL: an unset DATABASE_URL would otherwise mean a
    SQLite file inside the container, which is wiped on every deploy. Checks `url`, or else the engine actually in
    use. Used by the app at start-up and by the migration step (migrations/env.py). Messages never contain the URL.
    Returns database_summary()."""
    from sqlalchemy.exc import ArgumentError

    from app.auth import DEV_ENVS, effective_env

    st = get_settings()
    deployed = effective_env() not in DEV_ENVS
    try:
        info = database_summary(url)
    except (ArgumentError, ValueError):
        raise UnsafeDatabaseConfig("DATABASE_URL is not a valid database URL (its value is not shown). Expected "
                                   "postgresql+psycopg://<user>:<password>@<host>:5432/postgres; a password with "
                                   "@ : / # ? or % must be URL-encoded.") from None
    if deployed and info["dialect"] != "postgresql":
        if not st.database_url.strip():
            raise UnsafeDatabaseConfig(
                f"DATABASE_URL is not set (ENV is {st.env.strip() or 'unset'}, treated as {effective_env()}). "
                "Refusing to start with a local SQLite file, which would lose all data on the next deploy. Set "
                "DATABASE_URL to the Supabase session pooler URL: postgresql+psycopg://investments_app.<project-ref>:"
                "<password>@<pooler host>:5432/postgres (docs/DEPLOY.md §2).")
        raise UnsafeDatabaseConfig(f"DATABASE_URL uses {info['dialect']}; outside development/test only PostgreSQL "
                                   "is allowed (postgresql+psycopg://...).")
    return info


def check_rls_role() -> dict | None:
    """Postgres: the app's role must not bypass Row Level Security (superuser or BYPASSRLS), or RLS is not an active
    second layer. Refuses outside development/test; returns the role's attributes (None on SQLite)."""
    from sqlalchemy import text

    from app.auth import DEV_ENVS, effective_env

    engine = get_engine()
    if engine.dialect.name != "postgresql":
        if effective_env() not in DEV_ENVS:  # belt and braces: check_database_config refuses this first
            raise UnsafeDatabaseConfig(f"the database is {engine.dialect.name}, not PostgreSQL: refusing to start")
        return None
    with engine.connect() as conn:
        name, superuser, bypass = conn.execute(text(
            "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).one()
    info = {"role": name, "superuser": superuser, "bypassrls": bypass}
    if (superuser or bypass) and effective_env() not in DEV_ENVS:
        raise UnsafeDatabaseRole(f"database role {name!r} bypasses Row Level Security (superuser={superuser}, "
                                 f"bypassrls={bypass}); connect as the app role from backend/deploy/app_role.sql")
    return info
