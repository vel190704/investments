"""Accounts: the admin page (users, invites, AI per user, delete a user's data) and self-service account deletion.

Admin functions take a system session (cross-user reads are the point of the admin page). Emails are shown to the
admin but never logged; logs carry the numeric user id.
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db import Base
from app.logging_config import event
from app.models import AllowedEmail, LlmCall, User, UserOwned
from app.timeutil import as_utc

log = logging.getLogger("app.accounts")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
COUNTED = ("transactions", "instruments", "portfolio_snapshots", "thesis_entries", "qualitative_entries",
           "fund_disclosures", "llm_analyses")


class AccountError(ValueError):
    pass


def _user_tables():
    """Per-user tables, children first (safe delete order)."""
    return [t for t in reversed(Base.metadata.sorted_tables) if "user_id" in t.c and t.name != "users"]


def row_counts(s: Session, user_id: int) -> dict[str, int]:
    tables = {t.name: t for t in _user_tables()}
    return {name: s.scalar(select(func.count()).select_from(tables[name]).where(tables[name].c.user_id == user_id)) or 0
            for name in COUNTED}


def list_users(s: Session) -> list[dict]:
    from app.services.analysis import month_start_utc

    invited = {a.email for a in s.scalars(select(AllowedEmail))}
    calls = dict(s.execute(select(LlmCall.user_id, func.count()).where(LlmCall.created_at >= month_start_utc())
                           .group_by(LlmCall.user_id)).all())
    tokens = {uid: (tin or 0, tout or 0) for uid, tin, tout in s.execute(
        select(LlmCall.user_id, func.sum(LlmCall.input_tokens), func.sum(LlmCall.output_tokens))
        .where(LlmCall.created_at >= month_start_utc()).group_by(LlmCall.user_id)).all()}
    out = []
    for u in s.scalars(select(User).order_by(User.id)):
        out.append({"id": u.id, "email": u.email, "role": u.role, "invited": u.email in invited,
                    "signed_in": u.auth_subject is not None,
                    "created_at": as_utc(u.created_at).isoformat(),
                    "last_active_at": as_utc(u.last_active_at).isoformat() if u.last_active_at else None,
                    "ai_enabled": u.ai_enabled or u.role == "admin", "ai_monthly_cap": u.ai_monthly_cap,
                    "ai_calls_this_month": calls.get(u.id, 0),
                    "ai_tokens_this_month": {"input": tokens.get(u.id, (0, 0))[0], "output": tokens.get(u.id, (0, 0))[1]},
                    "own_key": bool(u.own_key_encrypted), "rows": row_counts(s, u.id),
                    "disabled": u.disabled_at is not None})
    pending = sorted(invited - {u["email"] for u in out})
    return out + [{"id": None, "email": e, "role": "user", "invited": True, "signed_in": False, "created_at": None,
                   "last_active_at": None, "ai_enabled": False, "ai_monthly_cap": None, "ai_calls_this_month": 0,
                   "ai_tokens_this_month": {"input": 0, "output": 0}, "own_key": False, "rows": {},
                   "disabled": False} for e in pending]


def invite(s: Session, email: str, by_user_id: int, send_email: bool = True) -> dict:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise AccountError("not a valid email address")
    if s.get(AllowedEmail, email) is None:
        s.add(AllowedEmail(email=email, invited_by=by_user_id))
        s.flush()
    sent = None
    if send_email:
        from app.services import supabase_admin

        sent = supabase_admin.send_invite(email)
    event(log, "user_invited", by_user_id=by_user_id, email_sent=sent)
    return {"email": email, "invited": True, "invite_email_sent": sent}


def uninvite(s: Session, email: str, by_user_id: int) -> None:
    """Removes the invitation: the person can no longer sign in. Their data stays until deleted."""
    s.execute(delete(AllowedEmail).where(AllowedEmail.email == email.strip().lower()))
    event(log, "user_uninvited", by_user_id=by_user_id)


def set_ai(s: Session, user_id: int, enabled: bool, cap: int | None) -> dict:
    u = s.get(User, user_id)
    if u is None:
        raise AccountError("no such user")
    u.ai_enabled = bool(enabled)
    if cap is not None:
        if not 0 <= cap <= 10000:
            raise AccountError("monthly cap must be 0 to 10,000")
        u.ai_monthly_cap = cap
    event(log, "user_ai_changed", target_user_id=user_id, enabled=u.ai_enabled, cap=u.ai_monthly_cap)
    return {"id": u.id, "ai_enabled": u.ai_enabled, "ai_monthly_cap": u.ai_monthly_cap}


def delete_user_data(s: Session, user_id: int, remove_account: bool = True) -> dict:
    """Delete every per-user row of a user (children first); optionally the account and invitation too.
    Shared market data is untouched. Returns the number of rows deleted per table."""
    u = s.get(User, user_id)
    if u is None:
        raise AccountError("no such user")
    counts = {}
    for t in _user_tables():
        n = s.execute(delete(t).where(t.c.user_id == user_id)).rowcount or 0
        if n:
            counts[t.name] = n
    subject = u.auth_subject
    if remove_account:
        s.execute(delete(AllowedEmail).where(AllowedEmail.email == u.email))
        s.execute(delete(User.__table__).where(User.__table__.c.id == user_id))
    s.flush()
    if remove_account and subject:
        from app.services import supabase_admin

        supabase_admin.delete_auth_user(subject)
    event(log, "user_data_deleted", target_user_id=user_id, account_removed=remove_account,
          rows=sum(counts.values()))
    return {"deleted_rows": counts, "account_removed": remove_account}


def set_own_key(s: Session, user_id: int, key: str | None) -> dict:
    """Store (encrypted) or clear the user's own Anthropic key. The key is never returned or logged."""
    from app.crypto import encrypt

    u = s.get(User, user_id)
    if key:
        key = key.strip()
        if not re.fullmatch(r"sk-ant-[A-Za-z0-9_\-]{20,200}", key):
            raise AccountError("that does not look like an Anthropic API key")
        u.own_key_encrypted = encrypt(key)
    else:
        u.own_key_encrypted = None
    event(log, "own_key_changed", user_id=user_id, stored=bool(key))
    return {"own_key": bool(u.own_key_encrypted)}


def assert_user_owned_complete() -> None:  # used by tests: every table with user_id is a UserOwned model
    owned = {m.__tablename__ for m in Base.__subclasses__() if issubclass(m, UserOwned)}
    with_col = {t.name for t in _user_tables()}
    assert with_col == owned, (with_col ^ owned)
