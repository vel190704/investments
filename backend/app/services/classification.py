"""Sector, ETF and fund-category classification from official lists, plus manual overrides.

Effective sector: MANUAL (app) > EXCEL (holdings_fallback.sector) > NSE (index constituent lists).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import repository as repo
from app.calc.allocation import OVERRIDABLE_CLASSES, region_for_global_index
from app.models import InstrumentFact, Instrument, SectorAssignment
from app.timeutil import today_ist, utcnow

ORIGIN_PRIORITY = ("MANUAL", "EXCEL", "NSE")
UNCLASSIFIED = "Unclassified"


@dataclass(frozen=True)
class EffectiveSector:
    sector: str
    origin: str | None  # None = unclassified
    source: str | None
    as_of: date | None
    manual: bool


def effective_sector(assignments: list[SectorAssignment]) -> EffectiveSector:
    by = {a.origin: a for a in assignments}
    for origin in ORIGIN_PRIORITY:
        a = by.get(origin)
        if a is not None:
            return EffectiveSector(a.sector, origin, a.source, a.as_of, origin != "NSE")
    return EffectiveSector(UNCLASSIFIED, None, None, None, False)


def sectors_by_instrument(s: Session) -> dict[int, EffectiveSector]:
    grouped: dict[int, list[SectorAssignment]] = {}
    for a in s.scalars(select(SectorAssignment)):
        grouped.setdefault(a.instrument_id, []).append(a)
    return {i.id: effective_sector(grouped.get(i.id, [])) for i in repo.all_instruments(s)}


def upsert_assignment(s: Session, instrument_id: int, origin: str, sector: str, source: str, as_of: date,
                      note: str | None = None) -> SectorAssignment:
    a = s.scalar(select(SectorAssignment).where(SectorAssignment.instrument_id == instrument_id,
                                                SectorAssignment.origin == origin))
    if a is None:
        a = SectorAssignment(instrument_id=instrument_id, origin=origin)
        s.add(a)
    a.sector, a.source, a.as_of, a.note = sector.strip(), source, as_of, note
    s.flush()
    return a


def etf_sector_label(inst: Instrument) -> str | None:
    """What an ETF holds, as a sector-table label (classification by holdings, not by name)."""
    u = (inst.etf_underlying or "").upper()
    if u == "GLOBAL INDICES":
        return f"International equity — {inst.region or 'region not classified'}"
    if u == "COMMODITY":
        return "Gold" if (inst.etf_underlying_key or "").upper() == "GOLD" else "Other commodities"
    if u == "DEBT":
        return "Debt"
    if u == "EQUITY":
        return f"Indian equity index — {inst.etf_underlying_key or 'unspecified'}"
    return None


def refresh_classification(s: Session) -> dict:
    """Fetch NSE index lists + ETF list + AMFI file and (re)write AUTO classifications."""
    from app.resolve.sources import amfi_schemes, nse_industries, nse_securities

    report = {"stocks_classified": [], "stocks_unclassified": [], "etfs": [], "funds": [], "errors": []}
    instruments = repo.all_instruments(s)
    stocks = [i for i in instruments if i.asset_type == "STOCK"]
    etfs = [i for i in instruments if i.asset_type == "ETF"]
    funds = [i for i in instruments if i.asset_type == "MF"]

    if stocks:
        try:
            by_isin, by_symbol, fetched = nse_industries()
            for i in stocks:
                hit = by_isin.get(i.isin or "") or by_symbol.get((i.symbol or "").upper())
                if hit is None:
                    s.execute(delete(SectorAssignment).where(SectorAssignment.instrument_id == i.id,
                                                             SectorAssignment.origin == "NSE"))
                    report["stocks_unclassified"].append(i.symbol)
                    continue
                how = "ISIN" if i.isin and hit.isin == i.isin else "NSE symbol"
                upsert_assignment(s, i.id, "NSE", hit.industry, f"NSE {hit.list_name} constituent list (Industry)",
                                  fetched.date(), f"matched by {how}")
                report["stocks_classified"].append(f"{i.symbol}: {hit.industry}")
        except Exception as e:
            report["errors"].append(f"NSE index lists unavailable: {e}")

    if etfs:
        try:
            nse, fetched = nse_securities()
            for i in etfs:
                sec = nse.get((i.symbol or "").upper())
                if sec is None or sec.kind != "ETF":
                    report["errors"].append(f"{i.symbol}: not in NSE ETF list")
                    continue
                i.etf_underlying = sec.etf_underlying
                i.etf_underlying_key = sec.underlying
                i.region = (region_for_global_index(sec.underlying_asset)
                            if (sec.etf_underlying or "").upper() == "GLOBAL INDICES" else "India")
                if (sec.etf_underlying or "").upper() == "GLOBAL INDICES":
                    i.exposure = "INTERNATIONAL"
                label = etf_sector_label(i)
                upsert_assignment(s, i.id, "NSE", label, "NSE ETF list (ETF Underlying / Underlying Asset)",
                                  fetched.date(), f"underlying: {sec.underlying_asset}")
                report["etfs"].append(f"{i.symbol}: {label}")
        except Exception as e:
            report["errors"].append(f"NSE ETF list unavailable: {e}")

    if funds:
        try:
            schemes, fetched = amfi_schemes()
            for i in funds:
                sch = schemes.get(i.scheme_code or "")
                if sch is None or not sch.category:
                    report["errors"].append(f"{i.name}: category needs a confirmed AMFI scheme code")
                    continue
                f = s.scalar(select(InstrumentFact).where(InstrumentFact.instrument_id == i.id,
                                                          InstrumentFact.metric == "category",
                                                          InstrumentFact.origin == "AUTO"))
                if f is None:
                    f = InstrumentFact(instrument_id=i.id, metric="category", origin="AUTO")
                    s.add(f)
                f.status, f.value, f.value_text = "OK", None, sch.category
                f.source, f.as_of, f.fetched_at = "AMFI NAVAll.txt section header", fetched.date(), utcnow()
                report["funds"].append(f"{i.name}: {sch.category}")
        except Exception as e:
            report["errors"].append(f"AMFI NAVAll.txt unavailable: {e}")
    s.flush()
    report["summary"] = (f"{len(report['stocks_classified'])} stocks classified, "
                         f"{len(report['stocks_unclassified'])} not in NSE lists, {len(report['etfs'])} ETFs, "
                         f"{len(report['funds'])} fund categories" + (f"; {len(report['errors'])} problem(s)"
                                                                     if report["errors"] else ""))
    return report


class ClassificationError(ValueError):
    pass


def set_overrides(s: Session, instrument_id: int, *, sector: str | None = None, asset_class: str | None = None,
                  region: str | None = None, note: str | None = None) -> Instrument:
    inst = repo.get_instrument(s, instrument_id)
    if inst is None:
        raise KeyError(instrument_id)
    if asset_class is not None:
        if asset_class not in OVERRIDABLE_CLASSES:
            raise ClassificationError(f"asset class must be one of: {', '.join(OVERRIDABLE_CLASSES)}")
        inst.asset_class_override = asset_class
    if sector is not None:
        if not sector.strip():
            raise ClassificationError("sector must not be empty")
        upsert_assignment(s, inst.id, "MANUAL", sector, "manual (entered in the app)", today_ist(), note)
    if region is not None:
        if not region.strip():
            raise ClassificationError("region must not be empty")
        inst.region = region.strip()
        upsert_manual_region(s, inst.id, region.strip(), note)
    s.flush()
    return inst


def upsert_manual_region(s: Session, instrument_id: int, region: str, note: str | None) -> None:
    f = s.scalar(select(InstrumentFact).where(InstrumentFact.instrument_id == instrument_id,
                                              InstrumentFact.metric == "region", InstrumentFact.origin == "MANUAL"))
    if f is None:
        f = InstrumentFact(instrument_id=instrument_id, metric="region", origin="MANUAL")
        s.add(f)
    f.status, f.value_text, f.source, f.as_of, f.note = "OK", region, "manual (entered in the app)", today_ist(), note


def clear_override(s: Session, instrument_id: int, field: str) -> None:
    inst = repo.get_instrument(s, instrument_id)
    if inst is None:
        raise KeyError(instrument_id)
    if field == "asset_class":
        inst.asset_class_override = None
    elif field == "sector":
        s.execute(delete(SectorAssignment).where(SectorAssignment.instrument_id == instrument_id,
                                                 SectorAssignment.origin == "MANUAL"))
    elif field == "region":
        s.execute(delete(InstrumentFact).where(InstrumentFact.instrument_id == instrument_id,
                                               InstrumentFact.metric == "region", InstrumentFact.origin == "MANUAL"))
    else:
        raise ClassificationError("field must be asset_class, sector or region")
    s.flush()
