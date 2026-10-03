from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.config import REPO_ROOT
from app.importer.run import import_workbook
from app.importer.validate import parse_txn
from app.models import FallbackHolding, IdentifierCandidate, Instrument, MonthlyPlanItem, Transaction
from tests.conftest import TXN_HEADER, base_txn_rows, write_workbook


def count(s, model):
    return s.scalar(select(func.count()).select_from(model))


def test_loads_all_19_rows_with_zero_errors(session, workbook):
    r = import_workbook(session, workbook)
    tr = r["transactions"]
    assert r["ok"] and r["fatal"] == []
    assert tr["loaded"] == 19 and tr["errors"] == [] and tr["skipped"] == []
    assert tr["by_asset_type"] == {"ETF": 2, "MF": 3, "STOCK": 14}
    assert count(session, Transaction) == 19 and count(session, Instrument) == 19


def test_money_stored_as_paise_and_decimals_exact(session, workbook):
    import_workbook(session, workbook)
    rel = session.scalar(select(Transaction).join(Instrument).where(Instrument.symbol == "RELIANCE"))
    assert rel.amount_paise == 119380
    mf = session.scalar(select(Transaction).join(Instrument).where(Instrument.name.like("HDFC Mid%")))
    assert str(mf.quantity) == "10.945" and str(mf.price) == "228.4148" and mf.amount_paise == 250000


def test_reimport_is_idempotent(session, workbook):
    import_workbook(session, workbook)
    r2 = import_workbook(session, workbook)
    assert r2["transactions"]["inserted"] == 0 and r2["transactions"]["unchanged"] == 19
    assert count(session, Transaction) == 19 and count(session, Instrument) == 19
    assert count(session, MonthlyPlanItem) == 4


def test_identical_rows_are_both_kept_and_still_idempotent(session, tmp_path):
    row = ["2026-11-05", "SIP", "MF", "Kotak Nifty Next 50 Index Fund - Direct - Growth", None, None, None,
           48.1, 20.79, 1000, 0, "Zerodha Coin", "SIP"]
    wb = write_workbook(tmp_path / "b.xlsx", txn_rows=base_txn_rows() + [row, list(row)])
    import_workbook(session, wb)
    import_workbook(session, wb)
    assert count(session, Transaction) == 21


def test_notes_change_updates_in_place(session, tmp_path):
    import_workbook(session, write_workbook(tmp_path / "a.xlsx"))
    rows = base_txn_rows()
    rows[0][12] = "edited note"
    r = import_workbook(session, write_workbook(tmp_path / "b.xlsx", txn_rows=rows))
    assert r["transactions"]["inserted"] == 0 and r["transactions"]["updated_notes"] == 1
    assert count(session, Transaction) == 19


def test_removed_rows_are_pruned_only_when_file_is_clean(session, tmp_path):
    import_workbook(session, write_workbook(tmp_path / "a.xlsx"))
    rows = base_txn_rows()[:-1]
    r = import_workbook(session, write_workbook(tmp_path / "b.xlsx", txn_rows=rows))
    assert r["transactions"]["removed"] == 1 and count(session, Transaction) == 18
    bad = rows + [["2026-10-04", "BOGUS", "STOCK", "X", "X", None, None, 1, 1, 1, 0, "Groww", None]]
    import_workbook(session, write_workbook(tmp_path / "c.xlsx", txn_rows=bad[:-2] + bad[-1:]))
    assert count(session, Transaction) == 18  # nothing pruned because the file had an error


def test_bad_rows_are_reported_never_crash(session, tmp_path):
    rows = base_txn_rows() + [
        [None, "BUY", "STOCK", "Blank date", "ITC", None, None, 1, 1, 1, 0, "Groww", None],      # skipped
        ["03/10/2026", "BUY", "STOCK", "Bad date", "ITC", None, None, 1, 1, 1, 0, "Groww", None],  # error
        ["2026-10-04", "HOLD", "STOCK", "Bad type", "ITC", None, None, 1, 1, 1, 0, "Groww", None],
        ["2026-10-04", "BUY", "STOCK", "No symbol", None, None, None, 1, 1, 1, 0, "Groww", None],
        ["2026-10-04", "BUY", "STOCK", "Neg qty", "ITC", None, None, -1, 1, 1, 0, "Groww", None],
        ["2026-10-04", "BUY", "STOCK", "Text amt", "ITC", None, None, 1, 1, "abc", 0, "Groww", None],
        ["2026-10-04", "BUY", "CRYPTO", "Bad asset", "BTC", None, None, 1, 1, 1, 0, "Groww", None],
        ["2026-10-04", "SELL", "STOCK", "ITC", "ITC", None, None, 5, 300, 1500, 0, "Groww", None],  # oversell
    ]
    r = import_workbook(session, write_workbook(tmp_path / "b.xlsx", txn_rows=rows))
    tr = r["transactions"]
    assert not r["ok"]
    assert tr["loaded"] == 19
    assert [s["row"] for s in tr["skipped"]] == [21]
    assert sorted({e["row"] for e in tr["errors"]}) == [22, 23, 24, 25, 26, 27, 28]
    assert any("exceeds quantity held" in e["message"] for e in tr["errors"])


def test_missing_sheet_is_fatal_and_writes_nothing(session, tmp_path):
    wb = write_workbook(tmp_path / "b.xlsx", sheets=["monthly_plan"])
    r = import_workbook(session, wb)
    assert not r["ok"] and "Sheet 'transactions' not found" in r["fatal"][0]
    assert count(session, Transaction) == 0


def test_not_an_excel_file(session, tmp_path):
    p = tmp_path / "x.xlsx"
    p.write_text("hello")
    r = import_workbook(session, p)
    assert not r["ok"] and r["fatal"]


def test_dividend_and_sell_validation():
    base = dict(zip(TXN_HEADER, ["2026-10-04", "DIVIDEND", "STOCK", "ITC", "ITC", None, None, None, None, 12.5,
                                 None, "Groww", None]))
    t, skip, errs = parse_txn(2, base)
    assert t and t.amount_paise == 1250 and t.quantity is None and not errs
    t, _, errs = parse_txn(3, {**base, "amount": None})
    assert t is None and errs[0].field == "amount"


def test_price_amount_mismatch_is_warning_not_error():
    r = dict(zip(TXN_HEADER, ["2026-10-04", "BUY", "STOCK", "ITC", "ITC", None, None, 2, 100, 500, 0, "Groww", None]))
    t, _, errs = parse_txn(2, r)
    assert t and not errs and "amount is used" in t.warnings[0]


def test_excel_identifiers_are_confirmed(session, tmp_path):
    rows = base_txn_rows()
    rows[0][5] = "INE018A01030"
    import_workbook(session, write_workbook(tmp_path / "b.xlsx", txn_rows=rows))
    lt = session.scalar(select(Instrument).where(Instrument.symbol == "LT"))
    c = session.scalar(select(IdentifierCandidate).where(IdentifierCandidate.instrument_id == lt.id))
    assert lt.isin == "INE018A01030" and c.status == "CONFIRMED" and c.source == "Excel file"


def test_fallback_used_only_without_transactions(session, tmp_path):
    fb = [["2026-10-03", "Groww", "STOCK", "Larsen & Toubro", "LT", 1, 3768, None, None, None],
          ["2026-10-03", "Groww", "STOCK", "Infosys", "INFY", 2, 3000, None, "IT", None]]
    r = import_workbook(session, write_workbook(tmp_path / "b.xlsx", fallback_rows=fb))
    assert r["holdings_fallback"]["used"] == ["Infosys"] and r["holdings_fallback"]["ignored"] == 1
    used = session.scalars(select(FallbackHolding).where(FallbackHolding.used.is_(True))).all()
    assert len(used) == 1 and used[0].invested_paise == 300000


def test_monthly_plan_total_row_and_fraction_checks(session, workbook):
    r = import_workbook(session, workbook)
    mp = r["monthly_plan"]
    assert mp["rows"] == 4 and mp["total_paise"] == 1_000_000 and mp["total_row_paise"] == 1_000_000
    assert mp["fraction_sum"] == "1" and mp["warnings"] == []
    items = session.scalars(select(MonthlyPlanItem)).all()
    assert sum(1 for i in items if i.instrument_id) == 3 and sum(1 for i in items if i.is_bucket) == 1


def test_monthly_plan_percent_not_fraction_is_error(session, tmp_path):
    plan = [("Groww", "STOCK/ETF", "Direct stocks & ETFs", 6000, 60)]
    r = import_workbook(session, write_workbook(tmp_path / "b.xlsx", plan_rows=plan))
    assert "FRACTION" in r["monthly_plan"]["errors"][0]["message"]


def test_international_etfs_flagged(session, workbook):
    import_workbook(session, workbook)
    intl = session.scalars(select(Instrument.symbol).where(Instrument.exposure == "INTERNATIONAL")).all()
    assert sorted(intl) == ["HNGSNGBEES", "MAFANG"]


REAL = REPO_ROOT / "data" / "personal_investment_tracker_clean.xlsx"


@pytest.mark.skipif(not REAL.exists(), reason="user workbook not present (data/ is git-ignored)")
def test_real_workbook_imports_cleanly(session):
    r = import_workbook(session, Path(REAL))
    assert r["ok"] and r["transactions"]["loaded"] == 19 and not r["transactions"]["errors"]
    assert r["transactions"]["by_asset_type"] == {"ETF": 2, "MF": 3, "STOCK": 14}
