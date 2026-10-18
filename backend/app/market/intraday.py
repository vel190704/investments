"""Intraday quotes for direct stocks/ETFs: one batched yfinance download of today's 1-minute bars.

Real data only: each bar's own timestamp and close. A ticker with no bars is reported as failed, never filled in.
Mutual funds are not polled (an AMFI NAV is published once a day).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from decimal import Decimal

from app.net.outbound import outbound

SOURCE = "Yahoo Finance via yfinance (1-minute bars; may be delayed)"
HOST = "finance.yahoo.com (yfinance)"

Bars = list[tuple[datetime, Decimal]]


def _dec(v) -> Decimal | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or f <= 0 else Decimal(repr(round(f, 4)))


def parse_download(df, tickers: list[str]) -> dict[str, Bars | str]:
    """{ticker: [(ts UTC, close)] ascending} or {ticker: "error text"}; minutes with no trade (NaN) are skipped."""
    out: dict[str, Bars | str] = {}
    cols = set(getattr(df, "columns", []))
    for t in tickers:
        key = (t, "Close")
        if df is None or getattr(df, "empty", True) or key not in cols:
            out[t] = "no intraday data returned"
            continue
        bars: Bars = []
        for ts, v in df[key].items():
            price = _dec(v)
            if price is not None:
                stamp = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
                bars.append((stamp.astimezone(UTC), price))
        out[t] = sorted(bars) if bars else "no trades in the returned bars"
    return out


def yf_download(tickers: list[str]):
    import yfinance as yf

    return yf.download(tickers=tickers, period="1d", interval="1m", group_by="ticker", auto_adjust=False,
                       progress=False, threads=False, prepost=False)


def fetch_intraday(symbols: list[str], download=None) -> dict[str, Bars | str]:
    """symbols: NSE symbols (without .NS). Returns {symbol: bars | error}. Raises when the whole request fails."""
    download = download or yf_download
    tickers = [f"{s}.NS" for s in symbols]
    with outbound("yfinance intraday", HOST, tickers=len(tickers)) as rec:
        df = download(tickers)
        parsed = parse_download(df, tickers)
        rec["with_data"] = sum(1 for v in parsed.values() if not isinstance(v, str))
    return {s: parsed[f"{s}.NS"] for s in symbols}
