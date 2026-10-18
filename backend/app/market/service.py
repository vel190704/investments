"""Refresh prices from all providers into price_quotes. Failures are recorded, never raised."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app import repository as repo
from app.market.amfi_provider import AmfiNavProvider
from app.market.base import FetchError, InstrumentRef, PriceProvider, Quote
from app.market.yfinance_provider import YFinanceProvider
from app.models import PriceQuote, RefreshRun
from app.timeutil import as_utc, utcnow

log = logging.getLogger(__name__)


def default_providers() -> list[PriceProvider]:
    return [YFinanceProvider(), AmfiNavProvider()]


def store_security_quote(s: Session, security_id: int, q: Quote) -> PriceQuote:
    prev_close, prev_date = q.previous_close, q.previous_date
    if prev_close is None:  # e.g. AMFI: use the previous cached NAV, if any
        prior = repo.previous_quote(s, security_id, q.source, q.price_date)
        if prior is not None:
            prev_close, prev_date = prior.price, prior.price_date
    row = repo.quote_on(s, security_id, q.source, q.price_date)
    if row is None:
        row = PriceQuote(security_id=security_id, source=q.source, price_date=q.price_date)
        s.add(row)
    row.source_ref, row.price, row.currency = q.source_ref, q.price, q.currency
    row.previous_close, row.previous_date = prev_close, prev_date
    row.fetched_at = q.fetched_at or utcnow()
    return row


def store_quote(s: Session, instrument_id: int, q: Quote) -> PriceQuote:
    """Store a quote for one of the user's instruments (written to its shared security)."""
    from app.services.securities import link

    inst = repo.get_instrument(s, instrument_id)
    if inst is None:
        raise KeyError(instrument_id)
    sec = inst.security or link(s, inst)
    if sec is None:
        raise ValueError(f"{inst.name}: no security (NSE symbol or confirmed AMFI scheme code) to price")
    s.flush()
    return store_security_quote(s, sec.id, q)


def refresh_prices(s: Session, trigger: str = "manual", providers: list[PriceProvider] | None = None) -> dict:
    """Fetch prices for the securities held by the session's user (a user request) or by anyone (system job).
    Prices are shared: one fetch serves every holder. Results name securities only (symbol / scheme code)."""
    import time

    from sqlalchemy import select

    from app.logging_config import event
    from app.models import Security
    from app.services.securities import held_security_ids

    providers = providers or default_providers()
    t0 = time.perf_counter()
    run = RefreshRun(trigger=trigger, started_at=utcnow())
    s.add(run)
    ids = held_security_ids(s)
    secs = list(s.scalars(select(Security).where(Security.id.in_(ids)))) if ids else []
    refs = [InstrumentRef(x.id, x.kind, x.symbol, x.scheme_code, x.symbol or x.scheme_code or x.key) for x in secs]
    results = []
    for p in providers:
        mine = [r for r in refs if p.supports(r)]
        if not mine:
            continue
        try:
            fetched = p.fetch(mine)
        except Exception as e:  # provider-level failure
            fetched = {r.security_id: FetchError(f"{p.name}: {e}") for r in mine}
        for r in mine:
            res = fetched.get(r.security_id, FetchError("no result"))
            if isinstance(res, Quote):
                store_security_quote(s, r.security_id, res)
                results.append({"security_id": r.security_id, "name": r.name, "ok": True, "source": res.source,
                                "price": str(res.price), "price_date": res.price_date.isoformat()})
            else:
                results.append({"security_id": r.security_id, "name": r.name, "ok": False, "source": p.name,
                                "error": res.message})
    from app.services.source_health import record

    for p in providers:
        mine = [r for r in results if r["source"] == p.name]
        if mine:
            ok = [r for r in mine if r["ok"]]
            hard = [r for r in mine if not r["ok"] and "not confirmed" not in (r.get("error") or "")]
            label = "AMFI NAVAll" if "AMFI" in p.name else "yfinance prices"
            record(s, label, bool(ok) or not hard, f"{len(ok)} ok, {len(mine) - len(ok)} unavailable"
                   + (f"; e.g. {hard[0]['error'][:200]}" if hard else ""))
    run.results = results
    run.ok_count = sum(1 for r in results if r["ok"])
    run.error_count = len(results) - run.ok_count
    run.finished_at = utcnow()
    s.flush()
    event(log, "price_refresh", logging.INFO if not run.error_count else logging.WARNING, trigger=trigger,
          requested=len(results), ok=run.ok_count, failed=run.error_count,
          duration_ms=round((time.perf_counter() - t0) * 1000),
          failures=[f"{r['name']}: {r.get('error', '')[:120]}" for r in results if not r["ok"]][:10])
    snapshot = None
    try:
        from app.services.snapshots import take_snapshot

        if s.info.get("user_id") is not None:  # a system run snapshots each user separately (jobs.snapshot_all)
            snapshot = take_snapshot(s, trigger="scheduled" if trigger == "scheduled" else "refresh")
    except Exception:  # a snapshot problem must never fail the refresh itself
        event(log, "snapshot_after_refresh", logging.ERROR, exc_info=True, outcome="failed")
    return {"id": run.id, "snapshot": snapshot, "ok_count": run.ok_count, "error_count": run.error_count, "results": results,
            "finished_at": run.finished_at.isoformat()}


def refresh_if_stale(s: Session, max_age_hours: int) -> dict | None:
    if max_age_hours <= 0:
        return None
    newest = as_utc(repo.newest_fetch_time(s))
    if newest is not None and utcnow() - newest < timedelta(hours=max_age_hours):
        return None
    if not repo.all_instruments(s):
        return None
    return refresh_prices(s, trigger="startup")
