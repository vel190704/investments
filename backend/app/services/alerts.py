"""Evaluate and list in-app alerts (no email, no push)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calc.alerts import evaluate
from app.models import Alert, AlertState, NewsItem
from app.services import settings as st
from app.timeutil import as_utc, today_ist, utcnow

STATE_KEY = "alerts"


def evaluate_alerts(s: Session) -> dict:
    from app.services.disclosures import list_disclosures
    from app.services.health import health
    from app.services.journal import review_due

    rules = st.get(s, "alerts")
    since = utcnow() - timedelta(days=30)
    news = [{"id": n.id, "instrument_id": n.instrument_id, "company": n.company, "title": n.title,
             "category": n.category, "source": n.source}
            for n in s.scalars(select(NewsItem).where(NewsItem.published_at >= since))]
    dims = {d["key"]: d["level"] for d in health(s)["dimensions"] if d["key"] in ("company", "sector", "overlap")}
    stale = [d for d in list_disclosures(s) if d["in_use"] and d["stale"]]
    reviews = review_due(s)
    row = s.get(AlertState, STATE_KEY)
    new, state = evaluate(rules, news, dims, stale, reviews, row.value if row else None, today_ist().isoformat())
    existing = set(s.scalars(select(Alert.dedupe_key)))
    created = 0
    for a in new:
        if a["key"] in existing:
            continue
        s.add(Alert(rule=a["rule"], dedupe_key=a["key"], instrument_id=a["instrument_id"], title=a["title"],
                    detail=a["detail"]))
        existing.add(a["key"])
        created += 1
    if row is None:
        s.add(AlertState(key=STATE_KEY, value=state))
    else:
        row.value = state
    s.flush()
    return {"created": created}


def list_alerts(s: Session, unread_only: bool = False) -> dict:
    q = select(Alert).order_by(Alert.created_at.desc(), Alert.id.desc()).limit(200)
    if unread_only:
        q = q.where(Alert.read_at.is_(None))
    items = [{"id": a.id, "rule": a.rule, "title": a.title, "detail": a.detail, "instrument_id": a.instrument_id,
              "created_at": as_utc(a.created_at).isoformat(), "read": a.read_at is not None} for a in s.scalars(q)]
    return {"alerts": items, "unread": sum(1 for a in items if not a["read"]), "rules": st.get(s, "alerts")}


def mark_read(s: Session, alert_id: int) -> None:
    a = s.get(Alert, alert_id)
    if a is None:
        raise KeyError(alert_id)
    a.read_at = a.read_at or utcnow()
    s.flush()
