"""Fetch (yfinance) and serve fundamentals and fund facts with provenance; manual entries."""

from __future__ import annotations

import logging
from datetime import date, datetime, UTC

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import repository as repo
from app.calc.fundamentals import (
    INDEX_ONLY, METRICS, NO_RELIABLE_SOURCE, NOT_PROVIDED, check_auto, check_manual, portfolio_median,
)
from app.models import InstrumentFact
from app.services.classification import sectors_by_instrument
from app.timeutil import as_utc, today_ist, utcnow

log = logging.getLogger(__name__)
SOURCE = "Yahoo Finance via yfinance (Ticker.info)"


def yfinance_info(symbol: str) -> dict:
    import yfinance as yf

    return yf.Ticker(f"{symbol}.NS").info or {}


def _upsert(s: Session, iid: int, metric: str, origin: str) -> InstrumentFact:
    f = s.scalar(select(InstrumentFact).where(InstrumentFact.instrument_id == iid, InstrumentFact.metric == metric,
                                              InstrumentFact.origin == origin))
    if f is None:
        f = InstrumentFact(instrument_id=iid, metric=metric, origin=origin)
        s.add(f)
    return f


def refresh_fundamentals(s: Session, fetch=yfinance_info) -> dict:
    report = {"ok": [], "errors": []}
    for inst in repo.all_instruments(s):
        if inst.asset_type != "STOCK" or not inst.symbol:
            continue
        try:
            info = fetch(inst.symbol)
        except Exception as e:
            report["errors"].append(f"{inst.symbol}: {type(e).__name__}: {e}")
            continue
        mrq = info.get("mostRecentQuarter")
        quarter = datetime.fromtimestamp(mrq, UTC).date() if isinstance(mrq, (int, float)) else None
        for m in METRICS.values():
            if m.applies_to != "STOCK" or not m.auto_field:
                continue
            status, value, note = check_auto(m.key, info.get(m.auto_field))
            f = _upsert(s, inst.id, m.key, "AUTO")
            f.status, f.value, f.value_text, f.note = status, value, None, note
            f.source = f"{SOURCE}: {m.auto_field}"
            f.fetched_at = utcnow()
            financial = m.key in ("roe", "debt_to_equity", "revenue_growth", "profit_growth")
            f.as_of = quarter if (financial and quarter) else today_ist()
        report["ok"].append(inst.symbol)
    s.flush()
    report["summary"] = f"{len(report['ok'])} stocks refreshed" + (f", {len(report['errors'])} failed" if report["errors"] else "")
    return report


def set_manual(s: Session, iid: int, metric: str, value: str, source_note: str, as_of: date) -> InstrumentFact:
    inst = repo.get_instrument(s, iid)
    if inst is None:
        raise KeyError(iid)
    m = METRICS.get(metric)
    from app.calc.fundamentals import ManualEntryError

    if m is None or m.applies_to != inst.asset_type:
        raise ManualEntryError(f"{metric!r} does not apply to {inst.asset_type}")
    v, text = check_manual(metric, value, source_note, as_of, today_ist())
    f = _upsert(s, iid, metric, "MANUAL")
    f.status, f.value, f.value_text = "OK", v, text
    f.source, f.note, f.as_of, f.fetched_at = f"manual: {source_note.strip()}", None, as_of, utcnow()
    s.flush()
    return f


def delete_manual(s: Session, iid: int, metric: str) -> None:
    s.execute(delete(InstrumentFact).where(InstrumentFact.instrument_id == iid, InstrumentFact.metric == metric,
                                           InstrumentFact.origin == "MANUAL"))
    s.flush()


def _cell(m, auto: InstrumentFact | None, manual: InstrumentFact | None, not_applicable: str | None = None) -> dict:
    """One displayed value with provenance. Manual entries win; otherwise the source value or N/A + reason."""
    base = {"metric": m.key, "label": m.label, "unit": m.unit, "manual_allowed": m.manual}
    if not_applicable:
        return {**base, "value": None, "text": None, "display_na": not_applicable, "origin": None}
    f = manual or auto
    if f is None or f.status != "OK":
        if m.manual and manual is None:
            na = NO_RELIABLE_SOURCE
        elif f is None:
            na = "N/A (not fetched yet)"
        elif f.status == "REJECTED":
            na = f"N/A ({f.note})"
        else:
            na = NOT_PROVIDED
        return {**base, "value": None, "text": None, "display_na": na, "origin": None,
                "source": f.source if f else None, "fetched_at": as_utc(f.fetched_at).isoformat() if f else None}
    return {**base, "value": str(f.value) if f.value is not None else None, "text": f.value_text,
            "display_na": None, "origin": f.origin, "manual": f.origin == "MANUAL", "source": f.source,
            "as_of": f.as_of.isoformat() if f.as_of else None, "fetched_at": as_utc(f.fetched_at).isoformat(),
            "note": m.note or None}


def report(s: Session) -> dict:
    from app.services.portfolio import load_rows

    rows, _ = load_rows(s)
    facts: dict[tuple[int, str, str], InstrumentFact] = {
        (f.instrument_id, f.metric, f.origin): f for f in s.scalars(select(InstrumentFact))}
    secs = sectors_by_instrument(s)
    stocks = [r for r in rows if r.inst.asset_type == "STOCK"]
    funds = [r for r in rows if r.inst.asset_type == "MF"]
    stock_metrics = [m for m in METRICS.values() if m.applies_to == "STOCK"]

    table = []
    for r in stocks:
        cells = [_cell(m, facts.get((r.inst.id, m.key, "AUTO")), facts.get((r.inst.id, m.key, "MANUAL")))
                 for m in stock_metrics]
        table.append({"instrument_id": r.inst.id, "symbol": r.inst.symbol, "name": r.inst.name,
                      "sector": secs[r.inst.id].sector,
                      "price": str(r.quote.price) if r.quote else None,
                      "price_source": r.quote.source if r.quote else None,
                      "price_date": r.quote.price_date.isoformat() if r.quote else None,
                      "metrics": cells})
    # "within my portfolio" medians (>= 3 other holdings in the same sector with a value)
    for m in stock_metrics:
        vals = {}
        for row in table:
            c = next(c for c in row["metrics"] if c["metric"] == m.key)
            vals[row["instrument_id"]] = (row["sector"], _dec_or_none(c["value"]))
        for row in table:
            c = next(c for c in row["metrics"] if c["metric"] == m.key)
            med = portfolio_median(row["instrument_id"], row["sector"], m.key, vals)
            c["portfolio_sector_median"] = str(med) if med is not None else None

    fund_rows = []
    for r in funds:
        cat = facts.get((r.inst.id, "category", "AUTO"))
        is_index = bool(cat and cat.value_text and "Index" in cat.value_text) or "index" in r.inst.name.lower()
        cells = []
        for m in METRICS.values():
            if m.applies_to != "MF":
                continue
            na = "Not applicable (not an index fund)" if (m.key in INDEX_ONLY and not is_index) else None
            cells.append(_cell(m, facts.get((r.inst.id, m.key, "AUTO")), facts.get((r.inst.id, m.key, "MANUAL")), na))
        fund_rows.append({"instrument_id": r.inst.id, "name": r.inst.name, "scheme_code": r.inst.scheme_code,
                          "is_index_fund": is_index, "metrics": cells})
    return {
        "stocks": table, "funds": fund_rows,
        "metric_defs": [{"key": m.key, "label": m.label, "unit": m.unit, "applies_to": m.applies_to,
                         "manual": m.manual, "auto": bool(m.auto_field), "note": m.note,
                         "bounds": [str(m.lo) if m.lo is not None else None, str(m.hi) if m.hi is not None else None]}
                        for m in METRICS.values()],
        "notes": [
            "Values are shown only when the source provides them and they pass plausibility checks; otherwise N/A with the reason.",
            "“Within my portfolio” medians compare with at least 3 of your other holdings in the same sector. "
            "They are not industry figures.",
            "ROCE, promoter holding and alpha have no reliable free source: enter them manually with a source note and date.",
        ],
    }


def _dec_or_none(v):
    from decimal import Decimal

    return Decimal(v) if v is not None else None
