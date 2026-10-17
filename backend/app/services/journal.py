"""Thesis journal (append-only versions) and the factual 'stated strategy vs what happened' view."""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import repository as repo
from app.models import ChangeLogEntry, PortfolioSnapshot, ThesisEntry, ThesisOptIn, Transaction
from app.services import changelog
from app.timeutil import IST, as_utc, today_ist


class JournalError(ValueError):
    pass


def _entry(t: ThesisEntry, today: date) -> dict:
    return {"id": t.id, "instrument_id": t.instrument_id, "version": t.version, "why": t.why,
            "change_view": t.change_view, "horizon": t.horizon,
            "review_date": t.review_date.isoformat() if t.review_date else None,
            "review_due": bool(t.review_date and t.review_date <= today),
            "created_at": as_utc(t.created_at).isoformat(), "linked_txn_ids": t.linked_txn_ids,
            "linked_change_ids": t.linked_change_ids}


def add_entry(s: Session, iid: int, why: str, change_view: str, horizon: str, review_date: date | None,
              linked_txn_ids: list[int] | None = None, linked_change_ids: list[int] | None = None) -> dict:
    inst = repo.get_instrument(s, iid)
    if inst is None:
        raise JournalError("instrument not found")
    if not why.strip() or not change_view.strip() or not horizon.strip():
        raise JournalError("Why I hold it, what would change my view, and horizon are all required")
    txns = set(s.scalars(select(Transaction.id).where(Transaction.instrument_id == iid)))
    bad = [t for t in (linked_txn_ids or []) if t not in txns]
    if bad:
        raise JournalError(f"transactions {bad} do not belong to this holding")
    changes = set(s.scalars(select(ChangeLogEntry.id)))
    badc = [c for c in (linked_change_ids or []) if c not in changes]
    if badc:
        raise JournalError(f"change-log entries {badc} do not exist")
    version = (s.scalar(select(func.max(ThesisEntry.version)).where(ThesisEntry.instrument_id == iid)) or 0) + 1
    t = ThesisEntry(instrument_id=iid, version=version, why=why.strip(), change_view=change_view.strip(),
                    horizon=horizon.strip(), review_date=review_date, linked_txn_ids=sorted(linked_txn_ids or []),
                    linked_change_ids=sorted(linked_change_ids or []))
    s.add(t)
    s.flush()
    changelog.add(s, "THESIS_UPDATED", "journal", f"{inst.symbol or inst.name}: thesis version {version} recorded",
                  iid, {"thesis_id": t.id, "version": version, "review_date": t.review_date.isoformat() if review_date else None})
    s.flush()
    return _entry(t, today_ist())


def history(s: Session, iid: int) -> list[dict]:
    today = today_ist()
    return [_entry(t, today) for t in s.scalars(select(ThesisEntry).where(ThesisEntry.instrument_id == iid)
                                                .order_by(ThesisEntry.version.desc()))]


def latest_by_instrument(s: Session) -> dict[int, ThesisEntry]:
    out: dict[int, ThesisEntry] = {}
    for t in s.scalars(select(ThesisEntry).order_by(ThesisEntry.version)):
        out[t.instrument_id] = t
    return out


def review_due(s: Session, today: date | None = None) -> list[dict]:
    today = today or today_ist()
    names = {i.id: i.symbol or i.name for i in repo.all_instruments(s)}
    return [{**_entry(t, today), "name": names.get(t.instrument_id)} for t in latest_by_instrument(s).values()
            if t.review_date and t.review_date <= today]


def set_optin(s: Session, iid: int, send: bool) -> None:
    row = s.get(ThesisOptIn, iid)
    if row is None:
        row = ThesisOptIn(instrument_id=iid)
        s.add(row)
    row.send_to_llm = send
    s.flush()


def journal(s: Session) -> dict:
    from app.services.portfolio import load_rows

    rows, _ = load_rows(s)
    latest = latest_by_instrument(s)
    opts = {o.instrument_id: o.send_to_llm for o in s.scalars(select(ThesisOptIn))}
    today = today_ist()
    txns: dict[int, list[dict]] = {}
    for t in repo.all_transactions(s):
        txns.setdefault(t.instrument_id, []).append({"id": t.id, "date": t.date.isoformat(), "type": t.type,
                                                     "source": t.source})
    return {"holdings": [{"instrument_id": r.inst.id, "name": r.inst.name, "symbol": r.inst.symbol,
                          "asset_type": r.inst.asset_type, "latest": _entry(latest[r.inst.id], today) if r.inst.id in latest else None,
                          "versions": s.scalar(select(func.count()).select_from(ThesisEntry)
                                               .where(ThesisEntry.instrument_id == r.inst.id)) or 0,
                          "send_to_llm": opts.get(r.inst.id, False), "transactions": txns.get(r.inst.id, [])}
                         for r in rows],
            "review_due": review_due(s, today),
            "note": "Entries are append-only: saving creates a new version; earlier versions are kept unchanged. Journal "
                    "text stays on this machine unless you tick 'include in AI analysis' for that holding."}


def strategy(s: Session, since: date) -> dict:
    """Purely factual: stated targets/notes vs what changed since `since`."""
    from app.services.portfolio import drift_block, load_rows
    from app.services.snapshots import compare_states

    rows, _ = load_rows(s)
    total = sum(r.value_paise for r in rows if r.value_paise is not None)
    snap = s.scalar(select(PortfolioSnapshot).where(PortfolioSnapshot.snapshot_date >= since)
                    .order_by(PortfolioSnapshot.snapshot_date).limit(1))
    compare = compare_states(s, snap.snapshot_date.isoformat(), "live") if snap else None
    start = datetime.combine(since, time.min, IST)
    names = {i.id: i.symbol or i.name for i in repo.all_instruments(s)}
    txns = [{"id": t.id, "date": t.date.isoformat(), "type": t.type, "name": names.get(t.instrument_id),
             "amount_paise": t.amount_paise, "source": t.source}
            for t in repo.all_transactions(s) if t.date >= since]
    changes = [{"id": c.id, "occurred_at": as_utc(c.occurred_at).isoformat(), "kind": c.kind, "summary": c.summary}
               for c in s.scalars(select(ChangeLogEntry).where(ChangeLogEntry.occurred_at >= start)
                                  .order_by(ChangeLogEntry.occurred_at))]
    latest = latest_by_instrument(s)
    return {
        "since": since.isoformat(),
        "stated": {"drift": drift_block(s, rows, total),
                   "theses": [{"name": names.get(iid), "version": t.version, "why": t.why, "change_view": t.change_view,
                               "horizon": t.horizon, "created_at": as_utc(t.created_at).isoformat()}
                              for iid, t in latest.items()]},
        "actual": {"comparison_from_snapshot": snap.snapshot_date.isoformat() if snap else None, "compare": compare,
                   "transactions": txns, "changes": changes},
        "note": None if snap else "No snapshot on or after this date, so the before/after comparison is unavailable; "
                                  "transactions and the change log are still listed.",
    }
