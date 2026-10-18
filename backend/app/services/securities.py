"""Global securities: one row per NSE symbol or AMFI scheme code, shared by every user who holds it.

A user's instrument links to its security when its identifier is known:
- stocks/ETFs: the NSE symbol from the user's workbook;
- funds: only after the user confirms (or types) an AMFI scheme code. Proposals are never applied silently.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import repository as repo
from app.models import Instrument, Security


def security_key(asset_type: str, symbol: str | None, scheme_code: str | None) -> str | None:
    if asset_type in ("STOCK", "ETF") and symbol:
        return f"NSE:{symbol.strip().upper()}"
    if asset_type == "MF" and scheme_code:
        return f"AMFI:{scheme_code.strip()}"
    return None


def ensure_security(s: Session, asset_type: str, symbol: str | None = None, scheme_code: str | None = None,
                    name: str | None = None) -> Security | None:
    """Find or create (race-safe) the shared security for an identifier."""
    key = security_key(asset_type, symbol, scheme_code)
    if key is None:
        return None
    sec = s.scalar(select(Security).where(Security.key == key))
    if sec is None:
        repo.insert_ignore(s, Security, [{
            "key": key, "kind": asset_type,
            "symbol": symbol.strip().upper() if asset_type in ("STOCK", "ETF") and symbol else None,
            "scheme_code": scheme_code.strip() if asset_type == "MF" and scheme_code else None,
            "name": name}], ["key"])
        sec = s.scalar(select(Security).where(Security.key == key))
    return sec


def link(s: Session, inst: Instrument) -> Security | None:
    """(Re)link a user's instrument to its security from its current identifiers."""
    sec = ensure_security(s, inst.asset_type, inst.symbol, inst.scheme_code, inst.name)
    inst.security_id = sec.id if sec else None
    inst.security = sec
    return sec


def held_security_ids(s: Session) -> list[int]:
    """Securities held by at least one user (call in a system session for the global union)."""
    return sorted({sid for sid in s.scalars(select(Instrument.security_id).where(Instrument.security_id.is_not(None)))})
