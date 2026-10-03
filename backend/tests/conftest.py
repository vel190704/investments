import os
from datetime import date
from pathlib import Path

import openpyxl
import pytest

os.environ["SCHEDULER_ENABLED"] = "false"

from app import db  # noqa: E402

TXN_HEADER = ["date", "type", "asset_type", "name", "symbol", "isin", "scheme_code", "quantity", "price",
              "amount", "charges", "platform", "notes"]

# Mirrors the user's workbook (19 OPENING rows: 14 stocks, 2 ETFs, 3 funds).
STOCKS = [
    ("Larsen & Toubro", "LT", "STOCK", 3768), ("Reliance Industries", "RELIANCE", "STOCK", 1193.8),
    ("State Bank of India", "SBIN", "STOCK", 963.95), ("HDFC Bank", "HDFCBANK", "STOCK", 718.35),
    ("KPIT Technologies", "KPITTECH", "STOCK", 529.95), ("Nippon India ETF Hang Seng BeES", "HNGSNGBEES", "ETF", 459),
    ("Coal India", "COALINDIA", "STOCK", 428.25), ("Bharat Electronics", "BEL", "STOCK", 398.95),
    ("Biocon", "BIOCON", "STOCK", 392.45), ("Indus Towers", "INDUSTOWER", "STOCK", 383.8),
    ("Tata Power", "TATAPOWER", "STOCK", 368.8), ("ITC", "ITC", "STOCK", 266.4),
    ("Mirae Asset NYSE FANG+ ETF", "MAFANG", "ETF", 235.7), ("MosChip Technologies", "MOSCHIP", "STOCK", 204.07),
    ("Tata Steel", "TATASTEEL", "STOCK", 183.55), ("Ashok Leyland", "ASHOKLEY", "STOCK", 162),
]
FUNDS = [
    ("HDFC Mid Cap Fund - Direct - Growth", 10.945, 228.4148, 2500),
    ("ICICI Prudential Nifty 50 Index Fund - Direct - Growth", 16.359, 244.5137, 4000),
    ("Kotak Nifty Next 50 Index Fund - Direct - Growth", 72.377, 20.7248, 1500),
]
PLAN = [
    ("Groww", "STOCK/ETF", "Direct stocks & ETFs", 6000, 0.6),
    ("Zerodha Coin", "MF", "HDFC Mid Cap Fund - Direct - Growth", 1500, 0.15),
    ("Zerodha Coin", "MF", "ICICI Prudential Nifty 50 Index Fund - Direct - Growth", 1500, 0.15),
    ("Zerodha Coin", "MF", "Kotak Nifty Next 50 Index Fund - Direct - Growth", 1000, 0.1),
    ("TOTAL", "ALL", "Total monthly investment", 10000, 1),
]


def base_txn_rows():
    rows = [["2026-10-03", "OPENING", at, n, sym, None, None, 1, p, p, 0, "Groww", "Opening balance"]
            for n, sym, at, p in STOCKS]
    rows += [["2026-10-03", "OPENING", "MF", n, None, None, None, q, p, a, 0, "Zerodha Coin", "Opening balance"]
             for n, q, p, a in FUNDS]
    return rows


def write_workbook(path: Path, txn_rows=None, fallback_rows=None, plan_rows=None, sheets=None) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "README"
    ws.append(["ignored"])
    sheets = sheets or ["transactions", "holdings_fallback", "monthly_plan"]
    if "transactions" in sheets:
        t = wb.create_sheet("transactions")
        t.append(TXN_HEADER)
        for r in (base_txn_rows() if txn_rows is None else txn_rows):
            t.append(r)
    if "holdings_fallback" in sheets:
        f = wb.create_sheet("holdings_fallback")
        f.append(["as_of_date", "platform", "asset_type", "name", "symbol", "quantity", "invested_amount",
                  "monthly_plan", "sector", "notes"])
        for r in (fallback_rows or []):
            f.append(r)
    if "monthly_plan" in sheets:
        p = wb.create_sheet("monthly_plan")
        p.append(["platform", "asset_type", "name", "monthly_amount", "allocation_percent"])
        for r in (PLAN if plan_rows is None else plan_rows):
            p.append(list(r))
    wb.save(path)
    return path


@pytest.fixture
def session(tmp_path):
    db.configure(f"sqlite:///{tmp_path / 'test.db'}")
    db.init_db()
    with db.session_scope() as s:
        yield s


@pytest.fixture
def workbook(tmp_path):
    return write_workbook(tmp_path / "book.xlsx")


VALUATION_DATE = date(2026, 10, 3)
