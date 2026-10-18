"""yfinance → normalised payload for app.calc.valuation (info subset + annual statement lines)."""

from __future__ import annotations

import math

INFO_KEYS = ["priceToSalesTrailing12Months", "trailingPE", "earningsGrowth", "revenueGrowth", "marketCap",
             "returnOnEquity", "debtToEquity", "beta", "mostRecentQuarter", "trailingEps", "currency", "totalRevenue"]
ROWS = {"income": ["Total Revenue", "Operating Revenue", "Net Income", "Net Income Common Stockholders", "EBIT",
                   "Interest Expense", "Diluted EPS"],
        "cashflow": ["Free Cash Flow"],
        "balance": ["Stockholders Equity", "Common Stock Equity", "Total Debt"]}
SOURCE = "Yahoo Finance via yfinance (annual statements + Ticker.info)"


def _frame(df, rows) -> dict:
    out = {}
    if df is None or getattr(df, "empty", True):
        return out
    for r in rows:
        if r in df.index:
            out[r] = {str(c.date()): (None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v))
                      for c, v in df.loc[r].items()}
    return out


def fetch_payload(symbol: str) -> dict:
    import yfinance as yf

    from app.net.outbound import outbound

    with outbound("yfinance statements", "finance.yahoo.com (yfinance)", private=(f"{symbol}.NS", symbol)) as rec:
        t = yf.Ticker(f"{symbol}.NS")
        info = t.info or {}
        out = {"info": {k: info.get(k) for k in INFO_KEYS},
               "income": _frame(t.income_stmt, ROWS["income"]),
               "cashflow": _frame(t.cashflow, ROWS["cashflow"]),
               "balance": _frame(t.balance_sheet, ROWS["balance"])}
        rec["income_lines"] = len(out["income"])
    return out
