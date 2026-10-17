"""Broker status + reconciliation. Never writes to the database (the user confirms any transaction in the UI)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.brokers.base import BrokerAdapter, BrokerError
from app.calc.reconcile import DbPosition, reconcile
from app.config import get_settings

_groww = None  # in-memory adapter (holds today's token only in memory)


def groww_adapter():
    global _groww
    st = get_settings()
    if not st.groww_enabled:
        raise BrokerError("Groww integration is off (set GROWW_ENABLED=true in .env to use it)")
    if _groww is None:
        from app.brokers.groww import GrowwAdapter

        _groww = GrowwAdapter(st.groww_api_key, st.groww_totp_secret or None)
    return _groww


def status() -> dict:
    st = get_settings()
    out = {"groww_enabled": st.groww_enabled, "api_key_set": bool(st.groww_api_key),
           "totp_secret_set": bool(st.groww_totp_secret), "token_valid": False,
           "kite_mf": "Not built (documented stub)", "read_only": True}
    if st.groww_enabled and st.groww_api_key:
        try:
            out["token_valid"] = groww_adapter().token_valid
        except BrokerError:
            pass
    return out


def db_positions(s: Session, platform: str = "Groww") -> tuple[list[DbPosition], list[str]]:
    from app.services.portfolio import load_rows

    rows, _ = load_rows(s)
    out, no_isin = [], []
    for r in rows:
        if r.inst.asset_type == "MF" or (r.inst.platform and r.inst.platform != platform):
            continue
        if not r.inst.isin:
            no_isin.append(r.inst.symbol or r.inst.name)
            continue
        out.append(DbPosition(r.inst.id, r.inst.isin, r.inst.symbol or r.inst.name, r.pos.quantity, r.pos.avg_cost))
    return out, no_isin


def reconcile_with(s: Session, adapter: BrokerAdapter) -> dict:
    db, no_isin = db_positions(s)
    try:
        broker = adapter.holdings()
    except BrokerError as e:
        return {"ok": False, "error": str(e), "differences": [], "not_compared": no_isin}
    diffs = reconcile(db, broker)
    return {"ok": True, "broker": adapter.name, "compared": len(db), "broker_holdings": len(broker),
            "differences": diffs, "not_compared": no_isin,
            "note": "Differences only. Nothing is changed automatically: 'Add as transaction' opens a pre-filled "
                    "in-app entry that you review and confirm."}
