"""Stocks/ETFs via yfinance using NSE tickers (SYMBOL.NS)."""

from __future__ import annotations

import logging
from decimal import Decimal

from app.market.base import FetchError, InstrumentRef, Quote
from app.timeutil import utcnow

log = logging.getLogger(__name__)
SOURCE = "Yahoo Finance (yfinance)"


def _dec(v: float) -> Decimal:
    """NSE prices have 2 decimals; yfinance returns float32-ish values (3693.39990234375)."""
    return Decimal(repr(round(float(v), 2)))


def quote_from_history(df, ticker: str) -> Quote | FetchError:
    """Latest daily bar = price, prior bar = previous close. Zero-volume bars (holidays) are dropped."""
    if df is None or df.empty:
        return FetchError(f"{ticker}: no price history returned")
    df = df.dropna(subset=["Close"])
    if "Volume" in df.columns and len(df) > 1:
        traded = df[df["Volume"] > 0]
        if not traded.empty:
            df = traded
    if df.empty:
        return FetchError(f"{ticker}: no valid closes")
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else None
    return Quote(
        price=_dec(last["Close"]), price_date=df.index[-1].date(), source=SOURCE, source_ref=ticker,
        previous_close=_dec(prev["Close"]) if prev is not None else None,
        previous_date=df.index[-2].date() if prev is not None else None, fetched_at=utcnow(),
    )


class YFinanceProvider:
    name = SOURCE

    def supports(self, ref: InstrumentRef) -> bool:
        return ref.asset_type in ("STOCK", "ETF") and bool(ref.symbol)

    def fetch(self, refs: list[InstrumentRef]) -> dict[int, Quote | FetchError]:
        try:
            import yfinance as yf
        except Exception as e:  # pragma: no cover
            return {r.instrument_id: FetchError(f"yfinance not available: {e}") for r in refs}
        from app.net.outbound import outbound

        out: dict[int, Quote | FetchError] = {}
        for r in refs:
            ticker = f"{r.symbol}.NS"
            try:
                with outbound("yfinance prices", "finance.yahoo.com (yfinance)", ticker=ticker):
                    df = yf.Ticker(ticker).history(period="10d", interval="1d", auto_adjust=False)
                    out[r.instrument_id] = quote_from_history(df, ticker)
            except Exception as e:
                out[r.instrument_id] = FetchError(f"{ticker}: {type(e).__name__}: {e}")
        return out
