"""Optional server-side calls to Supabase Auth's admin API (needs SUPABASE_SERVICE_ROLE_KEY, never sent to the
browser). Without the key, invite people from the Supabase dashboard instead (docs/DEPLOY.md). Never logs emails."""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings
from app.net.outbound import outbound

log = logging.getLogger("app.supabase_admin")


def _headers() -> dict[str, str] | None:
    key = get_settings().supabase_service_role_key
    return {"apikey": key, "Authorization": f"Bearer {key}"} if key else None


def send_invite(email: str) -> bool | None:
    """Ask Supabase to email an invite link. None = not configured; False = failed (see logs)."""
    st = get_settings()
    h = _headers()
    if h is None or not st.supabase_url:
        return None
    try:
        with outbound("Supabase Auth admin", st.supabase_url) as rec:
            r = httpx.post(f"{st.supabase_url.rstrip('/')}/auth/v1/invite", json={"email": email}, headers=h, timeout=20)
            rec["status"] = r.status_code
            r.raise_for_status()
        return True
    except Exception:
        return False


def delete_auth_user(subject: str) -> bool | None:
    st = get_settings()
    h = _headers()
    if h is None or not st.supabase_url:
        return None
    try:
        with outbound("Supabase Auth admin", st.supabase_url) as rec:
            r = httpx.delete(f"{st.supabase_url.rstrip('/')}/auth/v1/admin/users/{subject}", headers=h, timeout=20)
            rec["status"] = r.status_code
            r.raise_for_status()
        return True
    except Exception:
        return False
