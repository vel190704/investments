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


def check_rls_role() -> dict | None:
    """Postgres: the app's role must not bypass Row Level Security (superuser or BYPASSRLS), or RLS is not an active
    second layer. Refuses outside development/test; returns the role's attributes (None on SQLite)."""
    from sqlalchemy import text

    from app.auth import DEV_ENVS, effective_env

    engine = get_engine()
    if engine.dialect.name != "postgresql":
        return None
    with engine.connect() as conn:
        name, superuser, bypass = conn.execute(text(
            "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).one()
    info = {"role": name, "superuser": superuser, "bypassrls": bypass}
    if (superuser or bypass) and effective_env() not in DEV_ENVS:
        raise UnsafeDatabaseRole(f"database role {name!r} bypasses Row Level Security (superuser={superuser}, "
                                 f"bypassrls={bypass}); connect as the app role from backend/deploy/app_role.sql")
    return info
