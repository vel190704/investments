"""NSE cash-market hours in Asia/Kolkata. Pure functions (no DB, no network).

Session: 09:15:00 (inclusive) to 15:30:00 (exclusive), Monday-Friday, excluding the holidays the user keeps in
Settings › market holidays (entered by hand and verified against the NSE holiday list; never scraped).
Special sessions (e.g. Muhurat trading) are not modelled: such a day stays a holiday unless removed from the table.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from app.timeutil import IST

OPEN = time(9, 15)
CLOSE = time(15, 30)
POLL_MIN, POLL_MAX, POLL_DEFAULT = 30, 300, 60


@dataclass(frozen=True)
class MarketStatus:
    open: bool
    reason: str  # "open" | "weekend" | "holiday: <name>" | "before open" | "after close"
    session_date: date  # today's date in IST
    next_open: datetime  # next 09:15 IST on a trading day (today's if before open)
    closes_at: datetime | None  # today's 15:30 IST when open

    @property
    def label(self) -> str:
        return "Market open" if self.open else "Market closed"


def is_trading_day(d: date, holidays: dict[date, str]) -> bool:
    return d.weekday() < 5 and d not in holidays


def _next_open(d: date, holidays: dict[date, str]) -> datetime:
    for _ in range(30):
        if is_trading_day(d, holidays):
            return datetime.combine(d, OPEN, IST)
        d += timedelta(days=1)
    return datetime.combine(d, OPEN, IST)  # pragma: no cover - 30 consecutive closed days


def market_status(now: datetime, holidays: dict[date, str]) -> MarketStatus:
    n = now.astimezone(IST)
    d, t = n.date(), n.time()
    if d.weekday() >= 5:
        return MarketStatus(False, "weekend", d, _next_open(d + timedelta(days=1), holidays), None)
    if d in holidays:
        return MarketStatus(False, f"holiday: {holidays[d]}", d, _next_open(d + timedelta(days=1), holidays), None)
    if t < OPEN:
        return MarketStatus(False, "before open", d, datetime.combine(d, OPEN, IST), None)
    if t >= CLOSE:
        return MarketStatus(False, "after close", d, _next_open(d + timedelta(days=1), holidays), None)
    return MarketStatus(True, "open", d, _next_open(d + timedelta(days=1), holidays), datetime.combine(d, CLOSE, IST))


def holidays_from_setting(value: dict | None) -> dict[date, str]:
    return {date.fromisoformat(h["date"]): h["name"] for h in (value or {}).get("holidays", [])}
