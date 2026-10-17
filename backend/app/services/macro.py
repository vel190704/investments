"""Macro snapshot (automated where reliable, manual otherwise) and sector sensitivity tags."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.calc import scenarios as sc
from app.models import MacroValue, SectorSensitivity
from app.timeutil import as_utc, today_ist, utcnow

AUTO = {  # key: (label, yfinance ticker, unit)
    "usd_inr": ("USD/INR", "INR=X", "INR per USD"),
    "brent_usd": ("Brent crude", "BZ=F", "US$ per barrel"),
    "nifty50": ("Nifty 50", "^NSEI", "index points"),
}
MANUAL_DEFAULTS = {"repo_rate": ("RBI repo rate", "% p.a."), "cpi_inflation": ("CPI inflation (YoY)", "%")}


class MacroError(ValueError):
    pass


def yf_last_close(ticker: str) -> tuple[Decimal, date]:
    import yfinance as yf

    h = yf.Ticker(ticker).history(period="10d", interval="1d", auto_adjust=False).dropna(subset=["Close"])
    if h.empty:
        raise ValueError("no data returned")
    return Decimal(repr(round(float(h["Close"].iloc[-1]), 4))), h.index[-1].date()


def refresh_macro(s: Session, fetch=None) -> dict:
    fetch = fetch or yf_last_close  # resolved at call time (tests patch the module attribute)
    report = {}
    for key, (label, ticker, unit) in AUTO.items():
        row = s.scalar(select(MacroValue).where(MacroValue.key == key, MacroValue.origin == "AUTO"))
        if row is None:
            row = MacroValue(key=key, origin="AUTO", label=label, unit=unit, source="")
            s.add(row)
        row.source, row.fetched_at = f"Yahoo Finance via yfinance ({ticker})", utcnow()
        try:
            value, as_of = fetch(ticker)
            if value <= 0:
                raise ValueError(f"implausible value {value}")
            row.value, row.as_of, row.status, row.note = value, as_of, "OK", None
            report[key] = "ok"
        except Exception as e:  # keep the last good value? No: mark unavailable, never show stale as current
            row.value, row.as_of, row.status, row.note = None, None, "UNAVAILABLE", f"{type(e).__name__}: {e}"
            report[key] = f"unavailable: {e}"
    from app.services.source_health import record

    bad = [k for k, v in report.items() if v != "ok"]
    record(s, "yfinance macro", len(bad) < len(report), "all ok" if not bad else f"unavailable: {', '.join(bad)}")
    s.flush()
    return report


def set_manual(s: Session, key: str, label: str | None, value: str, unit: str | None, source_note: str,
               as_of: date) -> MacroValue:
    if key in AUTO:
        raise MacroError(f"{key} is automated; manual entry is for indicators without a reliable feed")
    if not source_note or not source_note.strip():
        raise MacroError("A source note is required")
    if as_of is None or as_of > today_ist():
        raise MacroError("An as-of date is required and cannot be in the future")
    try:
        v = Decimal(str(value).strip())
    except Exception:
        raise MacroError("Value must be a number") from None
    if not v.is_finite() or abs(v) > Decimal(1_000_000):
        raise MacroError("Value is not plausible")
    default_label, default_unit = MANUAL_DEFAULTS.get(key, (key.replace("_", " ").capitalize(), ""))
    row = s.scalar(select(MacroValue).where(MacroValue.key == key, MacroValue.origin == "MANUAL"))
    if row is None:
        row = MacroValue(key=key, origin="MANUAL", label=label or default_label, unit=unit or default_unit, source="")
        s.add(row)
    row.label, row.unit = (label or row.label or default_label), (unit if unit is not None else row.unit)
    row.value, row.as_of, row.status = v, as_of, "OK"
    row.source, row.fetched_at, row.note = f"manual: {source_note.strip()}", utcnow(), None
    s.flush()
    return row


def delete_manual(s: Session, key: str) -> None:
    s.execute(delete(MacroValue).where(MacroValue.key == key, MacroValue.origin == "MANUAL"))
    s.flush()


def snapshot(s: Session) -> list[dict]:
    """Every indicator with value or N/A; manual keys appear even when empty (N/A)."""
    rows = {(r.key, r.origin): r for r in s.scalars(select(MacroValue))}
    out = []
    keys = list(AUTO) + list(MANUAL_DEFAULTS) + sorted({k for k, o in rows if o == "MANUAL" and k not in MANUAL_DEFAULTS})
    for key in keys:
        r = rows.get((key, "AUTO")) if key in AUTO else rows.get((key, "MANUAL"))
        label, unit = (AUTO[key][0], AUTO[key][2]) if key in AUTO else MANUAL_DEFAULTS.get(key, (key, ""))
        ok = r is not None and r.status == "OK" and r.value is not None
        out.append({
            "key": key, "label": r.label if r else label, "unit": r.unit if r else unit,
            "origin": "AUTO" if key in AUTO else "MANUAL", "value": str(r.value) if ok else None,
            "display": f"{r.value.normalize():f}" if ok else
            ("N/A (source unavailable)" if r is not None and key in AUTO else
             "N/A (not fetched yet)" if key in AUTO else "N/A (enter it manually with a source)"),
            "source": r.source if r else None, "as_of": r.as_of.isoformat() if ok and r.as_of else None,
            "fetched_at": as_utc(r.fetched_at).isoformat() if r else None, "note": r.note if r else None,
            "manual": key not in AUTO,
        })
    return out


def ensure_starter(s: Session, held_sectors: list[str]) -> None:
    """Seed STARTER tags for held sectors that have no row yet (never overwrites USER edits)."""
    existing = {r.sector for r in s.scalars(select(SectorSensitivity))}
    for sector in held_sectors:
        if sector in sc.STARTER and sector not in existing:
            s.add(SectorSensitivity(sector=sector, tags=list(sc.STARTER[sector]), origin="STARTER", note=sc.STARTER_LABEL))
    s.flush()


def set_tags(s: Session, sector: str, tags: list[str], note: str | None = None) -> SectorSensitivity:
    bad = [t for t in tags if t not in sc.TAGS]
    if bad:
        raise MacroError(f"unknown tag(s): {', '.join(bad)}; allowed: {', '.join(sc.TAGS)}")
    row = s.get(SectorSensitivity, sector)
    if row is None:
        row = SectorSensitivity(sector=sector)
        s.add(row)
    row.tags, row.origin, row.note = sorted(set(tags)), "USER", note
    s.flush()
    return row


def sensitivities(s: Session) -> dict[str, list[str]]:
    return {r.sector: list(r.tags) for r in s.scalars(select(SectorSensitivity))}


def sensitivity_page(s: Session) -> dict:
    from app.services.lookthrough import sectors_page

    from app.calc.sectors import is_equity_sector

    sp = sectors_page(s)
    # only real sectors are taggable (not "Not looked through — fund", debt/cash buckets or "Unclassified")
    held = [r["sector"] for r in sp["sectors"]
            if is_equity_sector(r["sector"]) and not r["sector"].startswith("Unclassified")]
    ensure_starter(s, held)
    rows = {r.sector: r for r in s.scalars(select(SectorSensitivity))}
    table = [{"sector": sec, "tags": rows[sec].tags if sec in rows else [], "origin": rows[sec].origin if sec in rows else None,
              "note": rows[sec].note if sec in rows else None, "held_pct": next(r["pct"] for r in sp["sectors"] if r["sector"] == sec)}
             for sec in held]
    direct = [(d["name"], d["sector"]) for d in sp["direct"]]
    return {
        "tags": sc.TAGS, "table": table, "starter_label": sc.STARTER_LABEL,
        "scenarios": sc.exposure_by_tag(sp["sectors"], sensitivities(s), direct),
        "basis": "Exposure by sensitivity tag: the combined share of your portfolio (including fund look-through) in "
                 "sectors carrying each tag. Not a forecast of what would happen.",
    }
