"""Live intraday prices for direct stocks and ETFs (Phase 6).

- Polls only during NSE market hours (calc/market_hours), only when Settings › live is enabled and someone has
  looked at the live view recently; one batched request per cycle; backoff after failed cycles.
- Stores real 1-minute bars in intraday_ticks (14-day retention). Nothing here touches price_quotes, snapshots,
  XIRR or history: those stay end-of-day.
- No ticks are written outside market hours except by an explicit manual refresh.
- Mutual funds are never polled: an AMFI NAV is published once a day.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app import repository as repo
from app.calc.intraday import LiveRow, day_change, is_stale, live_totals, poll_interval, portfolio_series
from app.calc.market_hours import OPEN, POLL_MIN, holidays_from_setting, market_status
from app.logging_config import event
from app.market import intraday as provider
from app.money import value_paise
from app.services import settings as st
from app.timeutil import IST, as_utc, utcnow

log = logging.getLogger("app.live")
RETENTION_DAYS = 14
VIEWER_IDLE_SECONDS = 300  # stop polling when nobody has opened the live view for this long
SPARK_POINTS = 80
MF_NOTE = "Mutual funds are not polled: an AMFI NAV is published once a day (after market hours)."


@dataclass
class PollerState:
    last_poll_mono: float | None = None
    consecutive_failures: int = 0
    last_viewer_mono: float | None = None
    last_cycle: dict | None = None
    errors: dict[int, str] = field(default_factory=dict)  # security_id -> last poll error


STATE = PollerState()
_lock = threading.Lock()


def mark_viewer(mono: float | None = None) -> None:
    STATE.last_viewer_mono = time.monotonic() if mono is None else mono


def _holidays(s: Session):
    return holidays_from_setting(st.get(s, "market_holidays"))


def _poll_seconds(s: Session) -> int:
    return st.get(s, "live_platform")["poll_seconds"]


def _polled_securities(s: Session):
    """Stocks/ETFs held by the session's user, or by anyone in a system session (the shared poller)."""
    from sqlalchemy import select

    from app.models import Security
    from app.services.securities import held_security_ids

    ids = held_security_ids(s)
    return list(s.scalars(select(Security).where(Security.id.in_(ids), Security.kind.in_(("STOCK", "ETF")),
                                                 Security.symbol.is_not(None)))) if ids else []


def _stock_rows(s: Session):
    from app.services.portfolio import load_rows

    rows, _ = load_rows(s)
    return [r for r in rows if r.inst.asset_type in ("STOCK", "ETF") and r.inst.symbol]


def poll_cycle(s: Session, now: datetime | None = None, manual: bool = False, fetch=None) -> dict:
    """One poll: fetch every direct stock/ETF in one batched request and store the bars. Outside market hours this
    only runs when manual=True (an explicit refresh). Returns the cycle summary (also kept in STATE.last_cycle)."""
    now = now or utcnow()
    fetch = fetch or provider.fetch_intraday
    market = market_status(now, _holidays(s))
    if not manual and not market.open:
        return {"ran": False, "reason": f"market closed ({market.reason})"}
    with _lock:
        mono = time.monotonic()
        if manual and STATE.last_poll_mono is not None and mono - STATE.last_poll_mono < POLL_MIN:
            return {"ran": False, "reason": f"rate limited: at most one refresh every {POLL_MIN}s",
                    "last_cycle": STATE.last_cycle}
        secs = _polled_securities(s)
        if not secs:
            return {"ran": False, "reason": "no stocks or ETFs held"}
        by_symbol = {x.symbol: x.id for x in secs}
        t0 = time.perf_counter()
        STATE.last_poll_mono = mono
        try:
            data = fetch(list(by_symbol))
        except Exception as e:  # the whole request failed
            data = {sym: f"{type(e).__name__}: {e}"[:200] for sym in by_symbol}
        fetched_at = utcnow()
        ticks, ok, failed = [], [], {}
        for sym, res in data.items():
            sid = by_symbol[sym]
            if isinstance(res, str):
                failed[sid] = res
                continue
            ok.append(sid)
            ticks += [{"security_id": sid, "ts": ts, "price": price, "source": provider.SOURCE,
                       "fetched_at": fetched_at} for ts, price in res]
        added = repo.add_ticks(s, ticks)
        pruned = repo.prune_ticks(s, now - timedelta(days=RETENTION_DAYS))
        s.flush()
        STATE.errors = {**STATE.errors, **failed}
        for sid in ok:
            STATE.errors.pop(sid, None)
        STATE.consecutive_failures = 0 if ok else STATE.consecutive_failures + 1
        cycle = {"ran": True, "at": now.isoformat(), "manual": manual, "market_open": market.open,
                 "requested": len(by_symbol), "succeeded": len(ok), "failed": len(failed), "ticks_added": added,
                 "pruned": pruned, "duration_ms": round((time.perf_counter() - t0) * 1000),
                 "next_interval_s": poll_interval(_poll_seconds(s), STATE.consecutive_failures)}
        STATE.last_cycle = cycle
    from app.services.source_health import record

    record(s, "yfinance intraday", bool(ok), f"{len(ok)}/{len(by_symbol)} ok")  # shared: counts only
    event(log, "live_poll", logging.INFO if not failed else logging.WARNING, requested=cycle["requested"],
          succeeded=cycle["succeeded"], failed=cycle["failed"], duration_ms=cycle["duration_ms"], manual=manual,
          market=market.reason, ticks_added=added, backoff_s=cycle["next_interval_s"],
          failed_security_ids=sorted(failed)[:50])  # ids, never symbols
    return cycle


def scheduler_tick(s: Session, now: datetime | None = None, mono: float | None = None, fetch=None) -> dict:
    """Called every few seconds by the scheduler (system session); polls only when the market is open, a user with
    live prices on has looked recently, and a poll is due. One poll serves every user."""
    cfg = {"poll_seconds": _poll_seconds(s)}
    now = now or utcnow()
    market = market_status(now, _holidays(s))
    if not market.open:
        return {"ran": False, "reason": f"market closed ({market.reason})"}
    mono = time.monotonic() if mono is None else mono
    if STATE.last_viewer_mono is None or mono - STATE.last_viewer_mono > max(VIEWER_IDLE_SECONDS, 3 * cfg["poll_seconds"]):
        return {"ran": False, "reason": "nobody is viewing live prices"}
    wait = poll_interval(cfg["poll_seconds"], STATE.consecutive_failures)
    if STATE.last_poll_mono is not None and mono - STATE.last_poll_mono < wait:
        return {"ran": False, "reason": f"next poll in {round(wait - (mono - STATE.last_poll_mono))}s"}
    return poll_cycle(s, now, fetch=fetch)


def _downsample(points: list, n: int) -> list:
    """Pick at most n real points (always keeping the last); never creates values."""
    if len(points) <= n:
        return points
    step = len(points) / n
    picked = [points[int(i * step)] for i in range(n - 1)]
    return picked + [points[-1]]


def live_view(s: Session, now: datetime | None = None) -> dict:
    now = now or utcnow()
    cfg = {**st.get(s, "live"), "poll_seconds": _poll_seconds(s)}
    holidays = _holidays(s)
    market = market_status(now, holidays)
    session_start = datetime.combine(market.session_date, OPEN, IST)
    rows = [r for r in _stock_rows(s) if r.inst.security_id]
    sids = sorted({r.inst.security_id for r in rows})
    by_sec: dict[int, list] = {}
    for t in repo.ticks_since(s, session_start, sids):
        by_sec.setdefault(t.security_id, []).append((as_utc(t.ts), t.price))
    today = {r.inst.id: by_sec[r.inst.security_id] for r in rows if r.inst.security_id in by_sec}
    latest_sec = repo.latest_tick_per_security(s, sids) if sids else {}
    latest = {r.inst.id: latest_sec[r.inst.security_id] for r in rows if r.inst.security_id in latest_sec}
    out_rows, live_rows = [], []
    for r in rows:
        iid = r.inst.id
        tick = latest.get(iid)
        price, ts = (tick.price, as_utc(tick.ts)) if tick else (None, None)
        prev = repo.close_before(s, r.inst.security_id, market.session_date)
        prev_close = prev.price if prev else None
        err = STATE.errors.get(r.inst.security_id)
        stale = is_stale(ts, now, cfg["poll_seconds"])
        ch, pct = day_change(price, prev_close) if ts and ts >= session_start else (None, None)
        eod = r.quote
        out_rows.append({
            "instrument_id": iid, "symbol": r.inst.symbol, "name": r.inst.name, "asset_type": r.inst.asset_type,
            "quantity": str(r.pos.quantity), "price": str(price) if price is not None else None,
            "quote_ts": ts.isoformat() if ts else None, "source": tick.source if tick else None,
            "stale": stale, "error": err,
            "prev_close": str(prev_close) if prev_close is not None else None,
            "prev_close_date": prev.price_date.isoformat() if prev else None,
            "day_change": str(ch) if ch is not None else None, "day_change_pct": str(pct) if pct is not None else None,
            "value_paise": value_paise(r.pos.quantity, price) if price is not None else None,
            "last_close": str(eod.price) if eod else None, "last_close_date": eod.price_date.isoformat() if eod else None,
            "last_close_source": eod.source if eod else None,
            "spark": [{"ts": t.isoformat(), "price": str(p)} for t, p in _downsample(today.get(iid, []), SPARK_POINTS)],
        })
        live_rows.append(LiveRow(iid, r.inst.symbol or r.inst.name, r.pos.quantity,
                                 price if ts and ts >= session_start else None,
                                 ts, prev_close, err))
    totals = live_totals(live_rows, now, cfg["poll_seconds"]) if market.open else None
    series = []
    if today:
        qty = {r.inst.id: r.pos.quantity for r in rows
               if totals is None or r.inst.id in totals["included"]}
        series = portfolio_series(today, qty)
    from app.services.portfolio import load_rows

    funds = [r for r in load_rows(s)[0] if r.inst.asset_type == "MF"]
    hol = st.get(s, "market_holidays")["holidays"]
    return {
        "enabled": cfg["enabled"], "poll_seconds": cfg["poll_seconds"],
        "market": {"open": market.open, "label": market.label, "reason": market.reason,
                   "session_date": market.session_date.isoformat(), "next_open": market.next_open.isoformat(),
                   "closes_at": market.closes_at.isoformat() if market.closes_at else None,
                   "hours": "09:15–15:30 IST, Monday–Friday, excluding holidays in Settings"},
        "holidays_entered": len(hol), "holiday_note": st.HOLIDAY_NOTE,
        "last_cycle": STATE.last_cycle, "stale_after_s": 2 * cfg["poll_seconds"],
        "rows": out_rows, "totals": totals,
        "series": series,
        "series_note": "Each point values the included holdings at their last traded price at or before that minute; "
                       "minutes before a holding's first trade today are omitted. Ticks never feed snapshots, XIRR "
                       "or history.",
        "funds": {"note": MF_NOTE, "count": len(funds),
                  "value_paise": sum(r.value_paise for r in funds if r.value_paise is not None)
                  if any(r.value_paise is not None for r in funds) else None,
                  "unpriced": [r.inst.name for r in funds if r.value_paise is None],
                  "nav_dates": sorted({r.quote.price_date.isoformat() for r in funds if r.quote})},
        "source": provider.SOURCE,
    }


def prune(s: Session, now: datetime | None = None) -> int:
    return repo.prune_ticks(s, (now or utcnow()) - timedelta(days=RETENTION_DAYS))
