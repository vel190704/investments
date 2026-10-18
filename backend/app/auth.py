"""Authentication and the request-scoped user (Phase 6).

Default (fail closed): every request carries `Authorization: Bearer <Supabase access token>`. The token
is verified here (signature via the project's JWKS, or the legacy HS256 secret; `exp`, `aud`, `iss`), then the
email must be invited (`allowed_emails`) or listed in ADMIN_EMAILS. Unknown users get 403.

Development only (`DEV_AUTH=1` and `ENV=development|test`): a local fake user (DEV_USER_EMAIL), or
`X-Dev-User: <email>` for tests. Unset or unknown ENV means production; DEV_AUTH=1 there refuses to start.

Routes get a session bound to the user via `get_session`; app/tenancy.py does the per-user filtering.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache

from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.logging_config import USER_ID, event
from app.timeutil import as_utc, utcnow

log = logging.getLogger("app.auth")
ACTIVE_WRITE_EVERY = timedelta(minutes=5)


@dataclass(frozen=True)
class CurrentUser:
    id: int
    email: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class AuthError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


KNOWN_ENVS = ("development", "test", "preview", "production")
DEV_ENVS = ("development", "test")


def effective_env() -> str:
    """ENV as the app treats it: unset or unknown values mean production (fail closed)."""
    e = get_settings().env.strip().lower()
    return e if e in KNOWN_ENVS else "production"


def dev_auth_active() -> bool:
    """The local fake user is used only with an explicit DEV_AUTH=1 AND ENV=development|test."""
    return get_settings().dev_auth.strip() == "1" and effective_env() in DEV_ENVS


def check_startup_config() -> None:
    st = get_settings()
    if st.dev_auth.strip() == "1" and not dev_auth_active():
        raise RuntimeError(f"DEV_AUTH=1 is allowed only with ENV=development or ENV=test; ENV is "
                           f"{st.env.strip() or 'unset'}, which is treated as production. Remove DEV_AUTH.")
    if not dev_auth_active() and not st.supabase_url:
        raise RuntimeError("Authentication is required: set SUPABASE_URL (or, for local development only, "
                           "ENV=development and DEV_AUTH=1).")


def admin_emails() -> set[str]:
    return {e.strip().lower() for e in get_settings().admin_emails.split(",") if e.strip()}


@lru_cache
def _jwks_client(url: str):
    import jwt

    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)


def verify_token(token: str) -> dict:
    """Claims of a valid Supabase access token, or AuthError(401)."""
    import jwt

    st = get_settings()
    issuer = f"{st.supabase_url.rstrip('/')}/auth/v1"
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") == "HS256":
            if not st.supabase_jwt_secret:
                raise AuthError(401, "HS256 tokens are not accepted (no legacy secret configured)")
            key, algorithms = st.supabase_jwt_secret, ["HS256"]
        else:
            key = _jwks_client(f"{issuer}/.well-known/jwks.json").get_signing_key_from_jwt(token).key
            algorithms = ["ES256", "RS256"]
        return jwt.decode(token, key, algorithms=algorithms, audience=st.supabase_jwt_audience, issuer=issuer,
                          options={"require": ["exp", "sub", "aud", "iss"]})
    except AuthError:
        raise
    except jwt.ExpiredSignatureError:
        raise AuthError(401, "session expired: sign in again") from None
    except Exception as e:  # invalid signature, audience, issuer, malformed, JWKS unreachable
        raise AuthError(401, f"invalid session token ({type(e).__name__})") from None


def resolve_user(email: str, subject: str | None, dev: bool = False) -> CurrentUser:
    """Find or (if invited) create the account; 403 when the email is not invited."""
    from app.db import session_scope
    from app.models import AllowedEmail, User

    email = email.strip().lower()
    admins = admin_emails()
    with session_scope(system=True) as s:
        user = None
        if subject:
            user = s.scalar(select(User).where(User.auth_subject == subject))
        if user is None:
            user = s.scalar(select(User).where(func.lower(User.email) == email))
        from app.services import ops

        sw = ops.switches(s)
        if user is None:
            invited = s.get(AllowedEmail, email) is not None
            if not (dev or invited or email in admins):
                raise AuthError(403, "this email is not invited to the app")
            if sw["new_signins_off"] and email not in admins:
                raise AuthError(403, ops.MESSAGES["new_signins_off"])
            is_admin = email in admins or (dev and email == get_settings().dev_user_email.lower())
            from app import repository as repo

            # race-safe: two first requests of a new user may arrive together
            created = repo.insert_ignore(s, User, [{
                "email": email, "auth_subject": subject, "role": "admin" if is_admin else "user",
                "ai_enabled": is_admin, "ai_monthly_cap": 10, "created_at": utcnow()}], ["email"])
            user = s.scalar(select(User).where(func.lower(User.email) == email))
            if created:
                event(log, "user_created", user_id=user.id, role=user.role)
        else:
            if not dev and user.role != "admin" and email not in admins and s.get(AllowedEmail, email) is None:
                raise AuthError(403, "your invitation was removed")
            is_admin = user.role == "admin" or email in admins
            if not is_admin:
                if user.disabled_at is not None:
                    raise AuthError(403, ops.MESSAGES["disabled"])
                if sw["members_paused"]:
                    raise AuthError(503, ops.MESSAGES["members_paused"])
                if sw["new_signins_off"] and subject and not user.auth_subject:  # first sign-in of this account
                    raise AuthError(403, ops.MESSAGES["new_signins_off"])
            if subject and not user.auth_subject:
                user.auth_subject = subject
            if email in admins and user.role != "admin":
                user.role = "admin"
        now = utcnow()
        if user.last_active_at is None or now - as_utc(user.last_active_at) > ACTIVE_WRITE_EVERY:
            user.last_active_at = now
        return CurrentUser(user.id, user.email, user.role)


def authenticate(request: Request) -> CurrentUser:
    st = get_settings()
    if dev_auth_active():
        email = request.headers.get("x-dev-user") or st.dev_user_email
        return resolve_user(email, None, dev=True)
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise AuthError(401, "sign in required")
    claims = verify_token(auth.split(" ", 1)[1].strip())
    email = claims.get("email")
    if not email:
        raise AuthError(401, "token has no email")
    return resolve_user(email, claims["sub"])


async def current_user(request: Request) -> CurrentUser:
    from starlette.concurrency import run_in_threadpool

    try:
        user = await run_in_threadpool(authenticate, request)  # DB + JWKS work off the event loop
    except AuthError as e:
        raise HTTPException(e.status, e.message) from None
    request.state.user_id = user.id
    USER_ID.set(str(user.id))  # every log line of this request carries uid= (never the email)
    return user


def get_session(user: CurrentUser = Depends(current_user)) -> Iterator[Session]:
    """FastAPI dependency: a session bound to the signed-in user (all per-user data filtered to them)."""
    from app.db import session_scope

    with session_scope(user_id=user.id) as session:
        yield session


def require_admin(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(403, "admin only")
    return user


def get_admin_session(user: CurrentUser = Depends(require_admin)) -> Iterator[Session]:
    """System session for admin routes (cross-user reads such as the user list). Use sparingly."""
    from app.db import session_scope

    with session_scope(system=True) as session:
        session.info["admin_user_id"] = user.id
        yield session
