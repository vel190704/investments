"""In-app (source='ui') transactions: add, delete. Validation = the Excel importer's rules."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import repository as repo
from app.calc.positions import OversellError, TxnInput, replay
from app.importer.validate import TXN_COLUMNS, instrument_key, parse_txn
from app.models import Instrument, Transaction
from app.services import changelog
from app.services.instruments import get_or_create

UI_TYPES = ("BUY", "SELL", "SIP", "DIVIDEND")  # OPENING balances stay in the workbook


class TxnValidationError(ValueError):
    def __init__(self, errors: list[dict]):
        super().__init__("; ".join(e["message"] for e in errors))
        self.errors = errors


def _err(field: str | None, message: str) -> TxnValidationError:
    return TxnValidationError([{"field": field, "message": message}])


def _replay_ok(s: Session, instrument_id: int, extra: Transaction | None = None,
               exclude_id: int | None = None) -> str | None:
    """Replay the instrument's full history; return an error message if a SELL would oversell."""
    items = [TxnInput(t.date, t.type, t.quantity, t.amount_paise, t.charges_paise, t.source_row or t.id)
             for t in s.scalars(select(Transaction).where(Transaction.instrument_id == instrument_id))
             if t.id != exclude_id]
    for f in repo.used_fallbacks(s):
        if f.instrument_id == instrument_id:
            items.append(TxnInput(f.as_of_date, "OPENING", f.quantity, f.invested_paise))
    if extra is not None:
        items.append(TxnInput(extra.date, extra.type, extra.quantity, extra.amount_paise, extra.charges_paise, 10**9))
    try:
        replay(items)
    except OversellError as e:
        return f"SELL of {e.txn.quantity} on {e.txn.date} would exceed the quantity held ({e.held})"
    return None


def add_ui_transaction(s: Session, data: dict) -> dict:
    """data: Excel-column fields; either instrument_id (existing) or asset_type/name/symbol (new)."""
    ttype = str(data.get("type") or "").upper()
    if ttype not in UI_TYPES:
        raise _err("type", f"type must be one of {', '.join(UI_TYPES)} (OPENING balances belong in the workbook)")
    row = {c: data.get(c) for c in TXN_COLUMNS}
    row["type"] = ttype
    inst: Instrument | None = None
    if data.get("instrument_id"):
        inst = repo.get_instrument(s, int(data["instrument_id"]))
        if inst is None:
            raise _err("instrument_id", "instrument not found")
        row.update(asset_type=inst.asset_type, name=inst.name, symbol=inst.symbol)
    t, skip, errs = parse_txn(0, row)
    if skip:
        raise _err("date", "date is required (YYYY-MM-DD)")
    if errs:
        raise TxnValidationError([{"field": e.field, "message": e.message} for e in errs])
    if inst is None:
        cache = repo.instruments_by_key(s)
        key = instrument_key(t.asset_type, t.symbol, t.name)
        inst, _ = get_or_create(s, cache, key, t.asset_type, t.name, t.symbol, t.platform)

    before = changelog.position_states(s)
    txn = Transaction(
        instrument_id=inst.id, date=t.date, type=t.type, quantity=t.quantity, price=t.price,
        amount_paise=t.amount_paise, charges_paise=t.charges_paise, platform=t.platform or inst.platform,
        notes=t.notes, source="ui", row_key=f"ui:{uuid.uuid4().hex}",
    )
    problem = _replay_ok(s, inst.id, extra=txn)
    if problem:
        raise _err("quantity", problem)
    if t.type == "DIVIDEND" and inst.id not in before:
        t.warnings.append("no units held on this date; the dividend is still recorded")
    s.add(txn)
    s.flush()
    changelog.record_txn(s, "TXN_ADDED", "ui", txn, inst.symbol or inst.name)
    changelog.record_position_changes(s, before, "ui")
    return {"id": txn.id, "instrument_id": inst.id, "warnings": t.warnings}


def delete_ui_transaction(s: Session, txn_id: int) -> None:
    txn = s.get(Transaction, txn_id)
    if txn is None:
        raise KeyError(txn_id)
    if txn.source != "ui":
        raise _err(None, "Only in-app entries can be deleted here; workbook rows are managed in the Excel file")
    problem = _replay_ok(s, txn.instrument_id, exclude_id=txn.id)
    if problem:
        raise _err(None, f"Deleting this entry would leave a later sale uncovered: {problem}")
    before = changelog.position_states(s)
    changelog.record_txn(s, "TXN_REMOVED", "ui", txn, txn.instrument.symbol or txn.instrument.name)
    s.delete(txn)
    changelog.record_position_changes(s, before, "ui")
