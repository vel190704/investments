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
from types import SimpleNamespace

from app.models import InstrumentFact, Instrument, SectorAssignment, Security, SecuritySector
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
    """The user's MANUAL/EXCEL assignments plus the shared NSE sector of each instrument's security."""
    grouped: dict[int, list] = {}
    for a in s.scalars(select(SectorAssignment)):
        grouped.setdefault(a.instrument_id, []).append(a)
    sec_map = repo.instrument_security_map(s)
    if sec_map:
        for ss in s.scalars(select(SecuritySector).where(SecuritySector.security_id.in_(sec_map))):
            for iid in sec_map[ss.security_id]:
                grouped.setdefault(iid, []).append(
                    SimpleNamespace(origin="NSE", sector=ss.sector, source=ss.source, as_of=ss.as_of))
    return {i.id: effective_sector(grouped.get(i.id, [])) for i in repo.all_instruments(s)}


def upsert_security_sector(s: Session, security_id: int, sector: str, source: str, as_of: date,
                           note: str | None = None) -> SecuritySector:
    row = s.get(SecuritySector, security_id)
    if row is None:
        row = SecuritySector(security_id=security_id)
        s.add(row)
    row.sector, row.source, row.as_of, row.note = sector.strip(), source, as_of, note
    s.flush()
    return row


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
    """Fetch NSE index lists + ETF list + AMFI file and (re)write the shared classifications of held securities.
    Run as a system job it covers every user's holdings once; per-user fields (ETF region/exposure) are updated on
    each linked instrument."""
    from app.resolve.sources import amfi_schemes, nse_industries, nse_securities
    from app.services.fundamentals import auto_fact
    from app.services.securities import held_security_ids

    report = {"stocks_classified": [], "stocks_unclassified": [], "etfs": [], "funds": [], "errors": []}
    ids = held_security_ids(s)
    secs = list(s.scalars(select(Security).where(Security.id.in_(ids)).order_by(Security.key))) if ids else []
    stocks = [x for x in secs if x.kind == "STOCK"]
    etfs = [x for x in secs if x.kind == "ETF"]
    funds = [x for x in secs if x.kind == "MF"]
    by_security: dict[int, list[Instrument]] = {}
    for inst in repo.all_instruments(s):
        if inst.security_id:
            by_security.setdefault(inst.security_id, []).append(inst)

    if stocks:
        try:
            by_isin, by_symbol, fetched = nse_industries()
            for x in stocks:
                hit = by_symbol.get((x.symbol or "").upper()) or by_isin.get(x.isin or "")
                if hit is None:
                    row = s.get(SecuritySector, x.id)
                    if row is not None:
                        s.delete(row)
                    report["stocks_unclassified"].append(x.symbol)
                    continue
                if hit.isin and not x.isin:
                    x.isin = hit.isin
                upsert_security_sector(s, x.id, hit.industry, f"NSE {hit.list_name} constituent list (Industry)",
                                       fetched.date(), "matched by NSE symbol")
                report["stocks_classified"].append(f"{x.symbol}: {hit.industry}")
        except Exception as e:
            report["errors"].append(f"NSE index lists unavailable: {e}")

    if etfs:
        try:
            nse, fetched = nse_securities()
            for x in etfs:
                sec = nse.get((x.symbol or "").upper())
                if sec is None or sec.kind != "ETF":
                    report["errors"].append(f"{x.symbol}: not in NSE ETF list")
                    continue
                x.etf_underlying, x.etf_underlying_key = sec.etf_underlying, sec.underlying
                x.isin = x.isin or sec.isin
                international = (sec.etf_underlying or "").upper() == "GLOBAL INDICES"
                region = region_for_global_index(sec.underlying_asset) if international else "India"
                for i in by_security.get(x.id, []):
                    i.region = region
                    if international:
                        i.exposure = "INTERNATIONAL"
                label = etf_sector_label(SimpleNamespace(etf_underlying=sec.etf_underlying,
                                                         etf_underlying_key=sec.underlying, region=region))
                upsert_security_sector(s, x.id, label, "NSE ETF list (ETF Underlying / Underlying Asset)",
                                       fetched.date(), f"underlying: {sec.underlying_asset}")
                report["etfs"].append(f"{x.symbol}: {label}")
        except Exception as e:
            report["errors"].append(f"NSE ETF list unavailable: {e}")

    if funds:
        try:
            schemes, fetched = amfi_schemes()
            for x in funds:
                sch = schemes.get(x.scheme_code or "")
                if sch is None or not sch.category:
                    report["errors"].append(f"scheme {x.scheme_code}: no category in NAVAll.txt")
                    continue
                f = auto_fact(s, x.id, "category")
                f.status, f.value, f.value_text = "OK", None, sch.category
                f.source, f.as_of, f.fetched_at = "AMFI NAVAll.txt section header", fetched.date(), utcnow()
                report["funds"].append(f"{sch.name}: {sch.category}")
        except Exception as e:
            report["errors"].append(f"AMFI NAVAll.txt unavailable: {e}")
    from app.services.source_health import record

    errs = " ".join(report["errors"])
    if stocks:
        record(s, "NSE index lists", "NSE index lists unavailable" not in errs, f"{len(report['stocks_classified'])} classified")
    if etfs:
        record(s, "NSE securities lists", "NSE ETF list unavailable" not in errs, f"{len(report['etfs'])} ETFs")
    if funds:
        record(s, "AMFI NAVAll", "AMFI NAVAll.txt unavailable" not in errs, f"{len(report['funds'])} categories")
    s.flush()
    report["summary"] = (f"{len(report['stocks_classified'])} stocks classified, "
                         f"{len(report['stocks_unclassified'])} not in NSE lists, {len(report['etfs'])} ETFs, "
                         f"{len(report['funds'])} fund categories" + (f"; {len(report['errors'])} problem(s)"
                                                                     if report["errors"] else ""))
    _seed_sensitivities(s)
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
    if sector is not None:
        _seed_sensitivities(s)
    return inst


def _seed_sensitivities(s: Session) -> None:
    """Held sectors may have changed: give new ones their STARTER sensitivity tags (idempotent)."""
    from app.services.macro import seed_starter_sensitivities

    seed_starter_sensitivities(s)


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
