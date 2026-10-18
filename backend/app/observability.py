"""Optional error monitoring (Sentry). Off unless SENTRY_DSN is set.

Only exception events are sent, never log lines, breadcrumbs or performance traces. Every event passes `scrub_event`:
- request: method and route template only (no URL, query string, headers, cookies or body);
- user: the numeric id only (never email or IP);
- exception and message text: keys/tokens redacted, emails removed, numbers with 3+ digits masked (financial figures),
  quoted text masked (names and notes from workbooks); stack frames keep file, line and function only (no
  local variables, no source lines);
- extra data dropped.
"""

from __future__ import annotations

import os
import re

from app.logging_config import redact

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_QUOTED = re.compile(r"(['\"“‘])([^'\"”’]{1,500})(['\"”’])")
_NUMBER = re.compile(r"(?<![A-Za-z_])[-+]?(?:₹\s?)?\d[\d,]{2,}(?:\.\d+)?|\d+\.\d+")
_KEEP_CONTEXTS = ("runtime", "os", "trace")


def scrub_text(text: str) -> str:
    text = redact(text)
    text = _EMAIL.sub("<email>", text)
    text = _QUOTED.sub(lambda m: f"{m.group(1)}<text>{m.group(3)}", text)
    return _NUMBER.sub("<n>", text)


def scrub_event(event: dict, _hint=None) -> dict:
    req = event.get("request") or {}
    event["request"] = {"method": req.get("method")} if req else {}
    user = event.get("user") or {}
    event["user"] = {"id": user["id"]} if "id" in user else {}
    for ex in (event.get("exception") or {}).get("values") or []:
        if ex.get("value"):
            ex["value"] = scrub_text(str(ex["value"]))
        for frame in (ex.get("stacktrace") or {}).get("frames") or []:
            for k in ("vars", "context_line", "pre_context", "post_context"):  # file, line and function suffice
                frame.pop(k, None)
    if isinstance(event.get("logentry"), dict):
        event["logentry"] = {"message": scrub_text(str(event["logentry"].get("message", "")))}
    if event.get("message"):
        event["message"] = scrub_text(str(event["message"]))
    event.pop("extra", None)
    event.pop("breadcrumbs", None)
    event["contexts"] = {k: v for k, v in (event.get("contexts") or {}).items() if k in _KEEP_CONTEXTS}
    return event


def init_sentry(transport=None) -> bool:
    """Initialise Sentry when SENTRY_DSN is set. Returns True when enabled."""
    from app.auth import effective_env
    from app.config import get_settings

    dsn = get_settings().sentry_dsn
    if not dsn:
        return False
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=dsn, environment=effective_env(), release=os.environ.get("RENDER_GIT_COMMIT") or None,
        send_default_pii=False, include_local_variables=False, max_breadcrumbs=0, traces_sample_rate=0.0,
        auto_session_tracking=False,
        before_send=scrub_event, before_breadcrumb=lambda _crumb, _hint: None,
        integrations=[LoggingIntegration(level=None, event_level=None),  # logs never become events or crumbs
                      StarletteIntegration(transaction_style="url"), FastApiIntegration(transaction_style="url")],
        transport=transport,
    )
    return True


def capture(exc: BaseException, user_id: str | None = None) -> None:
    """Send one exception (scrubbed) if Sentry is enabled; never raises."""
    try:
        import sentry_sdk

        if not sentry_sdk.is_initialized():
            return
        with sentry_sdk.new_scope() as scope:
            if user_id and user_id != "-":
                scope.set_user({"id": user_id})
            sentry_sdk.capture_exception(exc)
    except Exception:  # monitoring must never break the app
        pass
