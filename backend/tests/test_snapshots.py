from datetime import date
from decimal import Decimal as D

from sqlalchemy import func, select

from app.calc.changes import HoldingView, PosState, compare, diff_allocation, diff_positions
from app.importer.run import import_workbook
from app.market.base import Quote
from app.market.service import store_quote
from app.models import ChangeLogEntry, Instrument, PortfolioSnapshot, SnapshotHolding
from app.services.snapshots import compare_states, series, take_snapshot
from app.services.transactions import add_ui_transaction
from tests.conftest import write_workbook

D1, D2 = date(2026, 10, 3), date(2026, 10, 4)


def price(s, symbol, p, on=date(2026, 10, 1)):
    i = s.scalar(select(Instrument).where(Instrument.symbol == symbol))
    store_quote(s, i.id, Quote(D(p), on, "test", symbol))
    s.flush()


def test_no_snapshot_without_data(session):
    assert take_snapshot(session) is None


def test_snapshot_upsert_one_per_day(session, workbook):
    import_workbook(session, workbook)
    price(session, "LT", "3700")
    r1 = take_snapshot(session, on_date=D1)
    assert r1["partial"] and len(r1["unpriced"]) == 18  # only LT priced, rest stated not guessed
    price(session, "ITC", "260")
    take_snapshot(session, on_date=D1)
    snaps = session.scalars(select(PortfolioSnapshot)).all()
    assert len(snaps) == 1
    assert snaps[0].total_value_paise == 370000 + 26000
    assert session.scalar(select(func.count()).select_from(SnapshotHolding)) == 19  # children rewritten, not doubled
    assert snaps[0].total_invested_paise == 1865702


def test_series_needs_two_snapshots(session, workbook):
    import_workbook(session, workbook)
    price(session, "LT", "3700")
    take_snapshot(session, on_date=D1)
    s1 = series(session)
    assert not s1["enough_history"] and "History builds from today" in s1["note"] and len(s1["points"]) == 1
    take_snapshot(session, on_date=D2)
    assert series(session)["enough_history"]


def test_allocation_change_logged_between_snapshots_and_upserted(session, workbook):
    import_workbook(session, workbook)
    price(session, "LT", "3700")
    price(session, "ITC", "260")
    take_snapshot(session, on_date=D1)
    price(session, "LT", "7400", on=date(2026, 10, 2))
    take_snapshot(session, on_date=D2)
    take_snapshot(session, on_date=D2)  # same day again: entries replaced, not duplicated
    entries = session.scalars(select(ChangeLogEntry).where(ChangeLogEntry.kind == "ALLOCATION_CHANGED")).all()
    assert len(entries) == 0  # both priced holdings are Indian stocks: class weights unchanged
    price(session, "MAFANG", "250", on=date(2026, 10, 2))
    take_snapshot(session, on_date=D2)
    entries = session.scalars(select(ChangeLogEntry).where(ChangeLogEntry.kind == "ALLOCATION_CHANGED")).all()
    assert {e.details["asset_class"] for e in entries} == {"Indian stocks", "International ETFs"}
    assert all(e.snapshot_date == D2 for e in entries)


def test_snapshots_survive_reimport(session, workbook):
    import_workbook(session, workbook)
    price(session, "LT", "3700")
    take_snapshot(session, on_date=D1)
    import_workbook(session, write_workbook(workbook.parent / "w2.xlsx"))
    assert session.scalar(select(func.count()).select_from(PortfolioSnapshot)) == 1


def test_compare_snapshot_vs_live(session, workbook):
    import_workbook(session, workbook)
    price(session, "LT", "3700")
    take_snapshot(session, on_date=D1)
    lt = session.scalar(select(Instrument).where(Instrument.symbol == "LT"))
    add_ui_transaction(session, {"instrument_id": lt.id, "date": "2026-10-03", "type": "BUY", "quantity": "1",
                                 "price": "3700", "amount": "3700"})
    c = compare_states(session, D1.isoformat(), "live")
    row = next(r for r in c["instruments"] if r["name"] == "LT")
    assert row["status"] == "changed" and row["quantity_a"] == "1" and row["quantity_b"] == "2"
    assert row["value_change_paise"] == 370000
    assert c["total_change_paise"] == 370000


# ---- pure diff functions
def test_diff_positions():
    before = {1: PosState("LT", D(1), D("3768")), 2: PosState("ITC", D(1), D("266.4"))}
    after = {1: PosState("LT", D(2), D("3684")), 3: PosState("INFY", D(2), D("1500"))}
    e = diff_positions(before, after)
    assert [(x["kind"], x["instrument_id"]) for x in e] == [
        ("QTY_CHANGED", 1), ("AVG_COST_CHANGED", 1), ("QTY_CHANGED", 2), ("QTY_CHANGED", 3)]
    assert e[2]["summary"] == "ITC: quantity 1 → 0"


def test_diff_allocation_threshold():
    e = diff_allocation({"A": D("0.5"), "B": D("0.5")}, {"A": D("0.5005"), "B": D("0.4995")})
    assert e == []  # 0.05 pp: below the 0.1 pp floor
    e = diff_allocation({"A": D("0.5"), "B": D("0.5")}, {"A": D("0.6"), "B": D("0.4")})
    assert [x["summary"] for x in e] == ["A: 50.0% → 60.0% of portfolio", "B: 50.0% → 40.0% of portfolio"]


def test_compare_added_removed_and_classes():
    a = [HoldingView(1, "LT", "Indian stocks", D(1), D(100), 10000, 10000),
         HoldingView(2, "ITC", "Indian stocks", D(1), D(50), 5000, 5000)]
    b = [HoldingView(1, "LT", "Indian stocks", D(1), D(100), 10000, 12000),
         HoldingView(3, "MF", "Mutual funds", D(10), D(10), 10000, 10000)]
    c = compare(a, b)
    st = {r["name"]: r["status"] for r in c["instruments"]}
    assert st == {"ITC": "removed", "LT": "unchanged", "MF": "added"}
    cls = {x["asset_class"]: x for x in c["asset_classes"]}
    assert cls["Indian stocks"]["value_change_paise"] == -3000 and cls["Mutual funds"]["value_b_paise"] == 10000
    assert c["total_change_paise"] == 7000
