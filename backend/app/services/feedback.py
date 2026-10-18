"""'Send feedback': short text from any page, read by the admin.

Privacy: the text is stored and shown on the admin page only. It never reaches logs or Sentry: log lines carry the
numeric user id, the page and the length; errors while storing are re-raised without the original exception (whose
message could hold the SQL parameters), so neither the traceback nor Sentry ever sees the text (tested).
Rate limit per user, counted in the database (survives restarts): RATE_PER_HOUR and RATE_PER_DAY.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.logging_config import event
from app.models import Feedback, User
from app.timeutil import IST, as_utc, utcnow

log = logging.getLogger("app.feedback")
MAX_CHARS = 2000
RATE_PER_HOUR, RATE_PER_DAY = 5, 20
_PAGE_OK = re.compile(r"^/[A-Za-z0-9/_\-.]{0,199}$")
NOTE = ("Please don't include account numbers, PAN, passwords or personal financial figures. Describe what you "
        "saw and on which page.")


class FeedbackError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class FeedbackStoreError(RuntimeError):
    """Storing failed. Deliberately carries no detail of the original error (it could contain the text)."""


def clean_page(page: str | None) -> str:
    """The page path only (no query string or fragment); anything odd becomes '/'."""
    p = (page or "/").split("?", 1)[0].split("#", 1)[0].strip()
    return p if _PAGE_OK.match(p) else "/"


def submit(s: Session, user_id: int, page: str | None, text: str, now: datetime | None = None) -> dict:
    now = now or utcnow()
    body = (text or "").strip()
    if not body:
        raise FeedbackError(422, "write something first")
    if len(body) > MAX_CHARS:
        raise FeedbackError(422, f"at most {MAX_CHARS:,} characters (this is {len(body):,})")
    hour = s.scalar(select(func.count()).select_from(Feedback).where(Feedback.created_at >= now - timedelta(hours=1)))
    day = s.scalar(select(func.count()).select_from(Feedback).where(Feedback.created_at >= now - timedelta(days=1)))
    if (hour or 0) >= RATE_PER_HOUR or (day or 0) >= RATE_PER_DAY:
        event(log, "feedback_rate_limited", logging.WARNING, user_id=user_id)
        raise FeedbackError(429, f"Thanks, that's plenty for now: at most {RATE_PER_HOUR} an hour and "
                                 f"{RATE_PER_DAY} a day. Please try again later.")
    page = clean_page(page)
    try:
        fb = Feedback(page=page, text=body, created_at=now)
        s.add(fb)
        s.flush()
    except Exception:
        event(log, "feedback_store_failed", logging.ERROR, user_id=user_id)
        raise FeedbackStoreError("could not store the feedback") from None  # never chain: the cause holds the text
    event(log, "feedback_received", user_id=user_id, feedback_id=fb.id, page=page, chars=len(body))
    return {"id": fb.id, "received": True}


def _day_start(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=IST)


def list_all(s: Session, page: str | None = None, since: date | None = None, until: date | None = None,
             status: str = "open") -> dict:
    """Admin list (system session), newest first. Dates are IST calendar days, both inclusive."""
    q = select(Feedback, User.email).join(User, User.id == Feedback.user_id).order_by(Feedback.created_at.desc())
    if page:
        q = q.where(Feedback.page == clean_page(page))
    if since:
        q = q.where(Feedback.created_at >= _day_start(since))
    if until:
        q = q.where(Feedback.created_at < _day_start(until + timedelta(days=1)))
    if status == "open":
        q = q.where(Feedback.done_at.is_(None))
    elif status == "done":
        q = q.where(Feedback.done_at.is_not(None))
    items = [{"id": f.id, "user_id": f.user_id, "email": email, "page": f.page, "text": f.text,
              "created_at": as_utc(f.created_at).isoformat(),
              "done_at": as_utc(f.done_at).isoformat() if f.done_at else None}
             for f, email in s.execute(q.limit(500)).all()]
    pages = sorted(set(s.scalars(select(Feedback.page).distinct())))
    return {"items": items, "pages": pages, "open": s.scalar(
        select(func.count()).select_from(Feedback).where(Feedback.done_at.is_(None))) or 0}


def set_done(s: Session, feedback_id: int, done: bool, by_user_id: int) -> dict:
    fb = s.get(Feedback, feedback_id)
    if fb is None:
        raise FeedbackError(404, "no such feedback")
    fb.done_at = utcnow() if done else None
    event(log, "feedback_marked", by_user_id=by_user_id, feedback_id=fb.id, done=done)
    return {"id": fb.id, "done_at": as_utc(fb.done_at).isoformat() if fb.done_at else None}
