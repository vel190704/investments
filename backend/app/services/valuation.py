"""Valuation framework, peers and own history for direct stocks (DB + network glue)."""

from __future__ import annotations

import time
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import repository as repo
from app.calc import framework as fw
from app.calc import valuation as v
from app.calc.fundamentals import check_auto
from app.market.statements import SOURCE, fetch_payload
from app.models import AnnualFinancial, PeerMetric, PeerSet, PriceQuote
from app.services import settings as st
from app.services.source_health import record
from app.timeutil import as_utc, today_ist, utcnow

COMPUTED = ["ps", "peg", "fcf_latest", "fcf_margin", "fcf_yield", "interest_coverage"]
PEER_METRICS = ["pe", "ps", "peg", "roe", "debt_to_equity", "revenue_growth", "profit_growth", "fcf_margin", "fcf_yield"]
INFO_AUTO = {"pe": "trailingPE", "roe": "returnOnEquity", "debt_to_equity": "debtToEquity",
             "revenue_growth": "revenueGrowth", "profit_growth": "earningsGrowth"}
MAX_PEERS = 8
PEER_REFRESH_HOURS = 24


class PeerError(ValueError):
    pass


def store_annual(s: Session, symbol: str, payload: dict) -> None:
    s.execute(delete(AnnualFinancial).where(AnnualFinancial.symbol == symbol))
    for metric, series in v.annual(payload).items():
        for fy, val in series.items():
            s.add(AnnualFinancial(symbol=symbol, fiscal_year_end=fy, metric=metric, value=val, source=SOURCE))
    s.flush()


def store_own(s: Session, iid: int, payload: dict) -> None:
    """For a user's instrument: written to its shared security."""
    inst = repo.get_instrument(s, iid)
    if inst is None or inst.security_id is None:
        raise KeyError(iid)
    store_security(s, inst.security_id, payload)


def store_security(s: Session, security_id: int, payload: dict) -> None:
    """Ticker.info metrics + computed metrics as shared AUTO facts (OK / MISSING with the reason)."""
    from app.services.fundamentals import apply_security_info, auto_fact

    apply_security_info(s, security_id, payload.get("info") or {})
    for key, res in v.compute_all(payload).items():
        f = auto_fact(s, security_id, key)
        f.status = "OK" if res.status == "OK" else "MISSING"
        f.value, f.value_text = res.value, None
        f.note = res.reason if res.status != "OK" else (
            f"{res.formula}; inputs: " + ", ".join(f"{k}={val}" for k, val in res.inputs.items() if k != "trend")
            if res.formula else None)
        f.source, f.fetched_at = SOURCE, utcnow()
        f.as_of = date.fromisoformat(res.as_of) if res.as_of else today_ist()
    s.flush()


def peer_metric_values(payload: dict) -> dict[str, tuple[str, Decimal | None, str | None]]:
    """(status, value, note) for each peer metric from one payload."""
    out = {}
    info = payload.get("info") or {}
    for key, field in INFO_AUTO.items():
        status, val, note = check_auto(key, info.get(field))
        out[key] = ("OK" if status == "OK" else "MISSING", val, note or (None if status == "OK" else "not provided"))
    for key, res in v.compute_all(payload).items():
        if key in PEER_METRICS:
            out[key] = ("OK" if res.status == "OK" else "MISSING", res.value, res.reason)
    return out


def set_peers(s: Session, iid: int, symbols: list[str], note: str | None) -> PeerSet:
    import re

    inst = repo.get_instrument(s, iid)
    if inst is None or inst.asset_type != "STOCK":
        raise PeerError("Peers can be set for direct stocks only")
    clean = []
    for sym in symbols:
        sym = sym.strip().upper()
        if not sym:
            continue
        if not re.fullmatch(r"[A-Z0-9&\-]{1,20}", sym):
            raise PeerError(f"{sym!r} is not an NSE symbol")
        if sym == (inst.symbol or "").upper():
            raise PeerError("A stock cannot be its own peer")
        if sym not in clean:
            clean.append(sym)
    if len(clean) > MAX_PEERS:
        raise PeerError(f"At most {MAX_PEERS} peers")
    row = s.get(PeerSet, iid) or PeerSet(instrument_id=iid)
    row.symbols, row.note = clean, (note or "").strip() or None
    s.add(row)
    s.flush()
    return row


def refresh(s: Session, fetch=fetch_payload, sleep=time.sleep, own: bool = True, peers: bool = True) -> dict:
    """Own stocks: computed metrics + annual lines. Peers: metrics cached for a day; 1 s between requests."""
    report = {"own": [], "peers": [], "errors": []}
    first = True

    def get(sym):
        nonlocal first
        if not first:
            sleep(1.0)
        first = False
        return fetch(sym)

    if own:
        from app.services.fundamentals import held_stock_securities

        for sec in held_stock_securities(s):  # one fetch per security, shared by every holder
            try:
                p = get(sec.symbol)
                store_annual(s, sec.symbol, p)
                store_security(s, sec.id, p)
                report["own"].append(sec.symbol)
            except Exception as e:
                report["errors"].append(f"{sec.symbol}: {type(e).__name__}: {e}")
        record(s, "yfinance fundamentals", not report["errors"] or bool(report["own"]),
               f"{len(report['own'])} stocks, {len(report['errors'])} failed")
    if peers:
        wanted = sorted({sym for ps in s.scalars(select(PeerSet)) for sym in ps.symbols})
        fresh = {pm.symbol for pm in s.scalars(select(PeerMetric))
                 if utcnow() - as_utc(pm.fetched_at) < timedelta(hours=PEER_REFRESH_HOURS)}
        perr = 0
        for sym in wanted:
            if sym in fresh:
                continue
            try:
                p = get(sym)
            except Exception as e:
                report["errors"].append(f"peer {sym}: {type(e).__name__}: {e}")
                perr += 1
                continue
            store_annual(s, sym, p)
            for key, (status, val, note) in peer_metric_values(p).items():
                row = s.scalar(select(PeerMetric).where(PeerMetric.symbol == sym, PeerMetric.metric == key)) \
                    or PeerMetric(symbol=sym, metric=key)
                row.status, row.value, row.note, row.source = status, val, note, SOURCE
                row.as_of, row.fetched_at = today_ist(), utcnow()
                s.add(row)
            report["peers"].append(sym)
        if wanted:
            record(s, "yfinance peers", perr == 0 or bool(report["peers"]), f"{len(report['peers'])} fetched, {perr} failed")
    s.flush()
    return report


def _my_values(s: Session, iid: int) -> dict[str, dict]:
    """Effective value per metric (manual wins) with source, for framework + peer comparison."""
    from app.services.fundamentals import facts_map

    facts: dict[str, dict] = {}
    for (fid, _metric, _origin), f in facts_map(s).items():
        if fid != iid:
            continue
        cur = facts.get(f.metric)
        if f.status != "OK":
            facts.setdefault(f.metric, {"value": None, "source": f.source, "as_of": None, "reason": f.note})
            continue
        if cur is None or cur["value"] is None or f.origin == "MANUAL":
            facts[f.metric] = {"value": f.value, "source": f.source + (" (manual)" if f.origin == "MANUAL" else ""),
                               "as_of": f.as_of.isoformat() if f.as_of else None, "reason": None, "note": f.note}
    return facts


def stock_view(s: Session, iid: int) -> dict:
    from app.services.classification import sectors_by_instrument

    inst = repo.get_instrument(s, iid)
    sector = sectors_by_instrument(s)[iid].sector
    mine = _my_values(s, iid)
    ps_row = s.get(PeerSet, iid)
    symbols = ps_row.symbols if ps_row else []
    pm = {(r.symbol, r.metric): r for r in s.scalars(select(PeerMetric).where(PeerMetric.symbol.in_(symbols or ["_"])))}
    comparisons = []
    for key in PEER_METRICS:
        vals = [(sym, pm.get((sym, key))) for sym in symbols]
        med, note = v.median_or_na([r.value for _, r in vals if r is not None and r.status == "OK"])
        comparisons.append({
            "metric": key, "mine": str(mine.get(key, {}).get("value")) if mine.get(key, {}).get("value") is not None else None,
            "peer_median": str(med) if med is not None else None, "median_note": note,
            "peers": [{"symbol": sym, "value": str(r.value) if r is not None and r.value is not None else None,
                       "status": r.status if r is not None else "NOT FETCHED",
                       "note": r.note if r is not None else "not fetched yet",
                       "as_of": r.as_of.isoformat() if r is not None and r.as_of else None} for sym, r in vals],
        })
    series = {}
    for a in s.scalars(select(AnnualFinancial).where(AnnualFinancial.symbol == (inst.symbol or ""))):
        series.setdefault(a.metric, {})[a.fiscal_year_end] = a.value
    prices = ({q.price_date: q.price for q in s.scalars(select(PriceQuote).where(PriceQuote.security_id == inst.security_id))}
              if inst.security_id else {})
    hist = v.history(series, prices)
    own_pe = v.hist_pe_median(hist)
    fcf_series = [(d.isoformat(), val) for d, val in sorted(series.get("fcf", {}).items())]
    pe_med = next(c for c in comparisons if c["metric"] == "pe")
    check_rows = fw.checks(
        {k: {"value": mine.get(k, {}).get("value"), "source": mine.get(k, {}).get("source")}
         for k in ("pe", "peg", "roe", "debt_to_equity", "interest_coverage")},
        Decimal(pe_med["peer_median"]) if pe_med["peer_median"] else None, pe_med["median_note"] if symbols else None,
        own_pe, fcf_series, sector, st.get(s, "rubric"), st.get(s, "sector_rules"))
    return {"instrument_id": iid, "symbol": inst.symbol, "name": inst.name, "sector": sector,
            "metrics": {k: {**val, "value": str(val["value"]) if val.get("value") is not None else None}
                        for k, val in mine.items()},
            "framework": check_rows, "peers": {"symbols": symbols, "note": ps_row.note if ps_row else None,
                                               "label": "peers chosen by me", "comparisons": comparisons},
            "history": hist, "own_hist_pe_median": str(own_pe) if own_pe is not None else None,
            "notes": ["No overall score, ranking or verdict: each check stands alone.",
                      "Historical P/E is shown only where a stored price exists near a fiscal year end; it is never "
                      "estimated."]}


def overview(s: Session) -> dict:
    stocks = [i for i in repo.all_instruments(s) if i.asset_type == "STOCK"]
    return {"stocks": [stock_view(s, i.id) for i in stocks], "rubric": st.get(s, "rubric"),
            "sector_rules": st.get(s, "sector_rules")}
