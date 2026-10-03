"""Writes change-log entries. Pure diffs live in app.calc.changes."""

from __future__ import annotations

from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.calc.changes import PosState, diff_positions
from app.calc.positions import OversellError, TxnInput, replay
from app.models import ChangeLogEntry, FallbackHolding, Instrument, Transaction


def position_states(s: Session) -> dict[int, PosState]:
    """Current quantity + average cost per instrument (all sources, incl. used fallbacks)."""
    names = {i.id: i.symbol or i.name for i in s.scalars(select(Instrument))}
    txns: dict[int, list[TxnInput]] = {}
    for t in s.scalars(select(Transaction)):
        txns.setdefault(t.instrument_id, []).append(
            TxnInput(t.date, t.type, t.quantity, t.amount_paise, t.charges_paise, t.source_row or t.id))
    for f in s.scalars(select(FallbackHolding).where(FallbackHolding.used.is_(True))):
        txns.setdefault(f.instrument_id, []).append(TxnInput(f.as_of_date, "OPENING", f.quantity, f.invested_paise))
    out = {}
    for iid, items in txns.items():
        try:
            p = replay(items)
        except OversellError:
            continue
        if p.quantity > 0:
            out[iid] = PosState(names[iid], p.quantity, p.avg_cost)
    return out


def add(s: Session, kind: str, cause: str, summary: str, instrument_id: int | None = None,
        details: dict | None = None, snapshot_date: date | None = None) -> None:
    s.add(ChangeLogEntry(kind=kind, cause=cause, summary=summary, instrument_id=instrument_id,
                         details=details or {}, snapshot_date=snapshot_date))


def txn_summary(t: Transaction, inst_name: str) -> str:
    from app.money import format_inr

    qty = f"{t.quantity.normalize():f} × " if t.quantity is not None else ""
    return f"{t.type} {inst_name}: {qty}{format_inr(t.amount_paise)} on {t.date.isoformat()} ({t.source})"


def record_txn(s: Session, kind: str, cause: str, t: Transaction, inst_name: str) -> None:
    add(s, kind, cause, txn_summary(t, inst_name), t.instrument_id,
        {"date": t.date.isoformat(), "type": t.type, "quantity": str(t.quantity) if t.quantity is not None else None,
         "amount_paise": t.amount_paise, "source": t.source, "row_key": t.row_key})


def record_position_changes(s: Session, before: dict[int, PosState], cause: str) -> int:
    s.flush()
    entries = diff_positions(before, position_states(s))
    for e in entries:
        add(s, e["kind"], cause, e["summary"], e["instrument_id"], e["details"])
    return len(entries)


def replace_allocation_entries(s: Session, snapshot_date: date, entries: list[dict]) -> None:
    s.execute(delete(ChangeLogEntry).where(ChangeLogEntry.kind == "ALLOCATION_CHANGED",
                                           ChangeLogEntry.snapshot_date == snapshot_date))
    for e in entries:
        add(s, e["kind"], "snapshot", e["summary"], None, e["details"], snapshot_date)
