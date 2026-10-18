"""Per-user isolation, enforced in one place.

A session carries its owner in `session.info`:
- `{"user_id": 7}`  — a request (or a job's per-user step): every ORM SELECT/UPDATE/DELETE on a `UserOwned` table
  gets `user_id = 7` added (including `session.get()` and relationship loads), and new rows are stamped with 7;
- `{"system": True}` — an explicit system job (global refresh, admin maintenance): no filter;
- neither — touching a `UserOwned` table raises TenantError (fail closed).

Postgres also gets `app.user_id` / `app.system` per transaction for Row Level Security (defence in depth).
"""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from app.models import UserOwned


class TenantError(RuntimeError):
    """A per-user table was touched without a user (or by the wrong user)."""


def current_user_id(session: Session) -> int | None:
    return session.info.get("user_id")


def is_system(session: Session) -> bool:
    return bool(session.info.get("system"))


def _touches_user_data(state: ORMExecuteState) -> bool:
    return any(issubclass(m.class_, UserOwned) for m in state.all_mappers)


@event.listens_for(Session, "do_orm_execute")
def _scope_to_user(state: ORMExecuteState) -> None:
    s = state.session
    if is_system(s) or not (state.is_select or state.is_update or state.is_delete):
        return
    uid = current_user_id(s)
    if uid is None:
        if _touches_user_data(state):
            raise TenantError("query on per-user data without a user context (use a user or system session)")
        return
    state.statement = state.statement.options(
        with_loader_criteria(UserOwned, lambda cls: cls.user_id == uid, include_aliases=True))


@event.listens_for(Session, "before_flush")
def _stamp_owner(session: Session, _ctx, _instances) -> None:
    uid = current_user_id(session)
    system = is_system(session)
    for obj in session.new:
        if not isinstance(obj, UserOwned):
            continue
        if obj.user_id is None:
            if uid is None:
                raise TenantError(f"new {type(obj).__name__} without a user context")
            obj.user_id = uid
        elif uid is not None and obj.user_id != uid and not system:
            raise TenantError(f"{type(obj).__name__} belongs to another user")
    if uid is not None and not system:
        for obj in list(session.dirty) + list(session.deleted):
            if isinstance(obj, UserOwned) and obj.user_id != uid:
                raise TenantError(f"{type(obj).__name__} belongs to another user")


@event.listens_for(Session, "after_begin")
def _postgres_rls_context(session: Session, _transaction, connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    uid = current_user_id(session)
    connection.exec_driver_sql(
        "SELECT set_config('app.user_id', %s, true), set_config('app.system', %s, true)",
        ("" if uid is None else str(uid), "on" if is_system(session) else "off"))
