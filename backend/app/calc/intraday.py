"""Live (intraday) valuation from real quotes only. Pure functions; no simulation or interpolation.

- A quote is "stale" when it is older than two poll intervals.
- Totals include only instruments with a fresh quote; the rest are listed with the reason they were left out.
- The portfolio intraday series values each holding at its last traded price at or before each minute (the usual
  meaning of a quote); a minute before any included holding's first trade of the day is omitted, never filled in.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.money import value_paise


def is_stale(quote_ts: datetime | None, now: datetime, poll_seconds: int) -> bool:
    return quote_ts is None or now - quote_ts > timedelta(seconds=2 * poll_seconds)


@dataclass(frozen=True)
class LiveRow:
    instrument_id: int
    name: str
    quantity: Decimal
    price: Decimal | None  # latest real quote
    quote_ts: datetime | None
    prev_close: Decimal | None  # previous session's close (end-of-day data)
    error: str | None = None  # last poll failed for this instrument


def day_change(price: Decimal | None, prev_close: Decimal | None) -> tuple[Decimal | None, Decimal | None]:
    if price is None or prev_close is None or prev_close == 0:
        return None, None
    ch = price - prev_close
    return ch, ch / prev_close


def live_totals(rows: list[LiveRow], now: datetime, poll_seconds: int) -> dict:
    included, excluded = [], []
    for r in rows:
        if r.error and (r.price is None or is_stale(r.quote_ts, now, poll_seconds)):
            excluded.append({"instrument_id": r.instrument_id, "name": r.name, "reason": f"quote failed: {r.error}"})
        elif r.price is None:
            excluded.append({"instrument_id": r.instrument_id, "name": r.name, "reason": "no quote yet"})
        elif is_stale(r.quote_ts, now, poll_seconds):
            excluded.append({"instrument_id": r.instrument_id, "name": r.name,
                             "reason": f"stale quote (older than {2 * poll_seconds}s)"})
        else:
            included.append(r)
    value = sum(value_paise(r.quantity, r.price) for r in included)
    with_prev = [r for r in included if r.prev_close is not None]
    prev_value = sum(value_paise(r.quantity, r.prev_close) for r in with_prev)
    day_pnl = sum(value_paise(r.quantity, r.price) for r in with_prev) - prev_value if with_prev else None
    return {"value_paise": value, "day_pnl_paise": day_pnl,
            "day_pnl_pct": str(Decimal(day_pnl) / prev_value) if day_pnl is not None and prev_value else None,
            "included": [r.instrument_id for r in included], "excluded": excluded,
            "no_previous_close": [r.name for r in included if r.prev_close is None]}


def portfolio_series(ticks: dict[int, list[tuple[datetime, Decimal]]], quantities: dict[int, Decimal]) -> list[dict]:
    """ticks: {instrument_id: [(ts, price)] ascending}. Only instruments in `quantities` are valued."""
    ids = [i for i in quantities if ticks.get(i)]
    if not ids:
        return []
    timeline = sorted({ts for i in ids for ts, _ in ticks[i]})
    pos = {i: -1 for i in ids}
    out = []
    for t in timeline:
        total = 0
        complete = True
        for i in ids:
            series = ticks[i]
            while pos[i] + 1 < len(series) and series[pos[i] + 1][0] <= t:
                pos[i] += 1
            if pos[i] < 0:
                complete = False
                break
            total += value_paise(quantities[i], series[pos[i]][1])
        if complete:
            out.append({"ts": t.isoformat(), "value_paise": total})
    return out


BACKOFF_CAP_SECONDS = 600


def poll_interval(poll_seconds: int, consecutive_failures: int) -> int:
    """Seconds to wait before the next poll: the configured interval, doubled per consecutive failed cycle, capped."""
    return min(poll_seconds * (2 ** max(consecutive_failures, 0)), BACKOFF_CAP_SECONDS)
