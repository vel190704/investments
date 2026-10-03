"""Instrument lookup/creation shared by the Excel importer and in-app entry."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.calc.allocation import INTERNATIONAL_ETF_SYMBOLS, derive_category
from app.models import Instrument


def get_or_create(session: Session, cache: dict[str, Instrument], key: str, asset_type: str, name: str,
                  symbol: str | None, platform: str | None) -> tuple[Instrument, bool]:
    inst = cache.get(key)
    created = inst is None
    if created:
        exposure = "INTERNATIONAL" if asset_type == "ETF" and symbol in INTERNATIONAL_ETF_SYMBOLS else "DOMESTIC"
        inst = Instrument(instrument_key=key, asset_type=asset_type, name=name, symbol=symbol,
                          platform=platform, exposure=exposure)
        session.add(inst)
        session.flush()
        cache[key] = inst
    inst.name, inst.platform = name, platform or inst.platform
    inst.category = derive_category(asset_type, name, inst.exposure)
    return inst, created
