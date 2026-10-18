"""Operations kill switches (Admin page) and the admin audit log.

Switches live in the database (platform_settings key "ops") and are read on every request, so they take effect at
once on every instance, without a redeploy:
- new_signins_off: nobody can sign in for the first time (no new accounts, no first sign-in of an invited email);
  people who already signed in keep working. Admins (ADMIN_EMAILS) are never locked out.
- members_paused: every non-admin request is refused (an incident: e.g. suspected cross-user exposure).
- ai_off: no AI call for anyone, whatever the per-user setting, key or cap.
Per user: users.disabled_at (set = all of that person's requests refused; data kept).

Every change is written to admin_audit (numeric ids, flags; never emails or figures) and logged as an event.
"""

from __future__ import annotations

import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.logging_config import event
from app.models import AdminAudit, PlatformSetting, User
from app.timeutil import as_utc, utcnow

log = logging.getLogger("app.ops")
KEY = "ops"
SWITCHES = ("new_signins_off", "members_paused", "ai_off")
DEFAULTS = {k: False for k in SWITCHES}
MESSAGES = {
    "new_signins_off": "New sign-ins are paused by the admin. Please try again later.",
    "members_paused": "The app is paused by the admin for maintenance. Please try again later.",
    "ai_off": "AI analysis is switched off for everyone by the admin.",
    "disabled": "Your account has been disabled by the admin.",
}


class OpsError(ValueError):
    pass


def switches(s: Session) -> dict:
    row = s.get(PlatformSetting, KEY)
    value = row.value if row is not None and isinstance(row.value, dict) else {}
    return {k: bool(value.get(k, False)) for k in SWITCHES}


def current() -> dict:
    """The switches, read in their own short system session (for code paths without one)."""
    from app.db import session_scope

    with session_scope(system=True) as s:
        return switches(s)


def ai_disabled() -> bool:
    return current()["ai_off"]


def audit(s: Session, admin_user_id: int | None, action: str, target_user_id: int | None = None,
          **details) -> None:
    s.add(AdminAudit(at=utcnow(), admin_user_id=admin_user_id, action=action, target_user_id=target_user_id,
                     details=details))
    s.flush()
    event(log, "admin_action", by_user_id=admin_user_id, action=action, target_user_id=target_user_id, **details)


def email_ref(email: str) -> str:
    """Short hash of an email for the audit log (it never stores the address)."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()[:12]


def set_switches(s: Session, changes: dict, by_user_id: int) -> dict:
    unknown = set(changes) - set(SWITCHES)
    if unknown:
        raise OpsError(f"unknown switch: {', '.join(sorted(unknown))}")
    now = switches(s)
    new = {**now, **{k: bool(v) for k, v in changes.items() if v is not None}}
    row = s.get(PlatformSetting, KEY)
    if row is None:
        s.add(PlatformSetting(key=KEY, value=new))
    else:
        row.value = new
    s.flush()
    for k in SWITCHES:
        if new[k] != now[k]:
            audit(s, by_user_id, f"{k}_{'on' if new[k] else 'off'}")
    return new


def set_disabled(s: Session, user_id: int, disabled: bool, by_user_id: int) -> dict:
    u = s.get(User, user_id)
    if u is None:
        raise OpsError("no such user")
    if u.id == by_user_id:
        raise OpsError("you cannot disable your own account")
    was = u.disabled_at is not None
    u.disabled_at = (u.disabled_at or utcnow()) if disabled else None
    if was != disabled:
        audit(s, by_user_id, "user_disabled" if disabled else "user_enabled", target_user_id=u.id)
    return {"id": u.id, "disabled_at": as_utc(u.disabled_at).isoformat() if u.disabled_at else None}


def recent_audit(s: Session, limit: int = 100) -> list[dict]:
    return [{"id": a.id, "at": as_utc(a.at).isoformat(), "admin_user_id": a.admin_user_id, "action": a.action,
             "target_user_id": a.target_user_id, "details": a.details or {}}
            for a in s.scalars(select(AdminAudit).order_by(AdminAudit.id.desc()).limit(limit))]
