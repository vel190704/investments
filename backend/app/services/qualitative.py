"""Structured qualitative notes per holding: append-only versions (like the thesis journal)."""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import repository as repo
from app.models import QualitativeEntry, ThesisEntry
from app.services import changelog
from app.timeutil import as_utc, today_ist

MOAT_TYPES = ["brand", "switching costs", "cost advantage", "network effects", "regulatory or licence", "none or unclear"]


class QualitativeError(ValueError):
    pass


def _d(q: QualitativeEntry) -> dict:
    return {"id": q.id, "instrument_id": q.instrument_id, "version": q.version, "moat_type": q.moat_type,
            "moat_note": q.moat_note, "capital_allocation_note": q.capital_allocation_note,
            "source_note": q.source_note, "as_of": q.as_of.isoformat(), "thesis_entry_id": q.thesis_entry_id,
            "created_at": as_utc(q.created_at).isoformat()}


def add(s: Session, iid: int, moat_type: str, moat_note: str, capital_allocation_note: str, source_note: str,
        as_of: date | None, thesis_entry_id: int | None = None) -> dict:
    inst = repo.get_instrument(s, iid)
    if inst is None:
        raise QualitativeError("instrument not found")
    if moat_type not in MOAT_TYPES:
        raise QualitativeError(f"moat type must be one of: {', '.join(MOAT_TYPES)}")
    if not moat_note.strip() or not capital_allocation_note.strip():
        raise QualitativeError("Moat note and capital-allocation note are required")
    if not source_note or not source_note.strip():
        raise QualitativeError("A source note is required")
    if as_of is None or as_of > today_ist():
        raise QualitativeError("An as-of date is required and cannot be in the future")
    if thesis_entry_id is not None:
        t = s.get(ThesisEntry, thesis_entry_id)
        if t is None or t.instrument_id != iid:
            raise QualitativeError("The linked thesis entry does not belong to this holding")
    version = (s.scalar(select(func.max(QualitativeEntry.version)).where(QualitativeEntry.instrument_id == iid)) or 0) + 1
    q = QualitativeEntry(instrument_id=iid, version=version, moat_type=moat_type, moat_note=moat_note.strip(),
                         capital_allocation_note=capital_allocation_note.strip(), source_note=source_note.strip(),
                         as_of=as_of, thesis_entry_id=thesis_entry_id)
    s.add(q)
    s.flush()
    changelog.add(s, "QUALITATIVE_UPDATED", "journal", f"{inst.symbol or inst.name}: qualitative notes version {version}",
                  iid, {"qualitative_id": q.id, "version": version})
    s.flush()
    return _d(q)


def history(s: Session, iid: int) -> list[dict]:
    return [_d(q) for q in s.scalars(select(QualitativeEntry).where(QualitativeEntry.instrument_id == iid)
                                     .order_by(QualitativeEntry.version.desc()))]


def latest(s: Session, iid: int) -> QualitativeEntry | None:
    return s.scalar(select(QualitativeEntry).where(QualitativeEntry.instrument_id == iid)
                    .order_by(QualitativeEntry.version.desc()).limit(1))
