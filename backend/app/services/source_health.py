"""Record per-source success/failure events and summarise them (last success/failure, 30-day strip)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import SourceEvent
from app.timeutil import IST, as_utc, today_ist, utcnow

SOURCES = ["yfinance prices", "AMFI NAVAll", "NSE securities lists", "NSE index lists", "yfinance fundamentals",
           "yfinance peers", "yfinance macro", "NSE announcements", "LLM provider"]  # + "News feed: <name>" rows
RETENTION_DAYS = 90


def record(s: Session, source: str, ok: bool, message: str = "") -> None:
    """Never raises: health bookkeeping must not break the caller."""
    try:
        s.add(SourceEvent(source=source, ok=ok, message=(message or ("ok" if ok else "failed"))[:2000]))
        s.flush()
    except Exception:  # pragma: no cover
        pass


def summary(s: Session, days: int = 30) -> list[dict]:
    s.execute(delete(SourceEvent).where(SourceEvent.at < utcnow() - timedelta(days=RETENTION_DAYS))
              .execution_options(synchronize_session="fetch"))
    today = today_ist()
    start = today - timedelta(days=days - 1)
    events = list(s.scalars(select(SourceEvent).order_by(SourceEvent.at)))
    names = list(dict.fromkeys(SOURCES + [e.source for e in events]))
    out = []
    for name in names:
        ev = [e for e in events if e.source == name]
        ok = [e for e in ev if e.ok]
        bad = [e for e in ev if not e.ok]
        strip = []
        for i in range(days):
            d = start + timedelta(days=i)
            day = [e for e in ev if as_utc(e.at).astimezone(IST).date() == d]
            st = "none" if not day else "ok" if all(e.ok for e in day) else "failed" if not any(e.ok for e in day) else "mixed"
            strip.append({"date": d.isoformat(), "status": st, "events": len(day)})
        out.append({"source": name,
                    "last_success": as_utc(ok[-1].at).isoformat() if ok else None,
                    "last_failure": as_utc(bad[-1].at).isoformat() if bad else None,
                    "last_error": bad[-1].message if bad else None,
                    "last_message": ev[-1].message if ev else None,
                    "history": strip})
    return out
