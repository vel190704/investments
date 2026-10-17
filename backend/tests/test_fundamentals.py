from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.calc.fundamentals import ManualEntryError, check_auto, check_manual, portfolio_median
from app.importer.run import import_workbook
from app.models import Instrument, InstrumentFact
from app.services import fundamentals as fs

TODAY = date(2026, 10, 3)


def test_check_auto_ok_missing_rejected():
    assert check_auto("pe", 30.676079) == ("OK", D("30.676079"), None)
    assert check_auto("debt_to_equity", 97.64)[1] == D("0.9764")  # Yahoo % -> ratio
    assert check_auto("roe", None)[0] == "MISSING"
    assert check_auto("roe", float("nan"))[0] == "MISSING"
    st, v, note = check_auto("pe", 25000)
    assert st == "REJECTED" and v is None and "implausible" in note
    assert check_auto("beta", "abc")[0] == "REJECTED"
    assert check_auto("market_cap", -5)[0] == "REJECTED"


def test_manual_entry_requires_source_and_date():
    assert check_manual("roce", "18.5", "Annual report FY26 p.112", date(2026, 6, 30), TODAY) == (D("0.185"), None)
    with pytest.raises(ManualEntryError, match="source note"):
        check_manual("roce", "18.5", "  ", date(2026, 6, 30), TODAY)
    with pytest.raises(ManualEntryError, match="future"):
        check_manual("roce", "18.5", "AR", date(2026, 12, 1), TODAY)
    with pytest.raises(ManualEntryError, match="between"):
        check_manual("promoter_holding", "120", "BSE shareholding pattern", date(2026, 6, 30), TODAY)
    with pytest.raises(ManualEntryError, match="cannot be entered manually"):
        check_manual("pe", "20", "x", date(2026, 6, 30), TODAY)  # auto-only metric
    assert check_manual("exit_load", "1% if redeemed within 1 year", "SID", date(2026, 9, 1), TODAY)[1].startswith("1%")


def test_portfolio_median_needs_three_others():
    vals = {1: ("Banks", D(10)), 2: ("Banks", D(12)), 3: ("Banks", D(14)), 4: ("Banks", None), 5: ("IT", D(30))}
    assert portfolio_median(4, "Banks", "pe", vals) == D(12)
    assert portfolio_median(1, "Banks", "pe", vals) is None  # only 2 others with a value
    assert portfolio_median(5, "IT", "pe", vals) is None
    assert portfolio_median(9, "Unclassified", "pe", {9: ("Unclassified", D(1)), **{i: ("Unclassified", D(i)) for i in range(3)}}) is None


def fake_info(symbol):
    if symbol == "LT":
        return {"marketCap": 5081623691264, "trailingPE": 30.68, "returnOnEquity": None, "debtToEquity": 97.64,
                "revenueGrowth": 0.081, "earningsGrowth": 0.14, "beta": 0.507, "mostRecentQuarter": 1782777600}
    if symbol == "SBIN":
        return {"trailingPE": 99999.0, "beta": 0.386}  # implausible P/E
    if symbol == "ITC":
        raise ConnectionError("timeout")
    return {}


def test_no_fabricated_values(session, workbook):
    import_workbook(session, workbook)
    rep = fs.refresh_fundamentals(session, fetch=fake_info, statements=False)
    assert any("ITC" in e for e in rep["errors"])
    out = fs.report(session)
    by = {r["symbol"]: {c["metric"]: c for c in r["metrics"]} for r in out["stocks"]}
    lt = by["LT"]
    assert lt["pe"]["value"] == "30.68" and lt["pe"]["source"].endswith("trailingPE")
    assert lt["roe"]["value"] is None and lt["roe"]["display_na"] == "N/A (not provided by source)"
    assert lt["debt_to_equity"]["value"] == "0.9764" and lt["debt_to_equity"]["as_of"] == "2026-06-30"
    assert lt["roce"]["display_na"] == "N/A (no reliable source)"
    assert by["SBIN"]["pe"]["value"] is None and "implausible" in by["SBIN"]["pe"]["display_na"]
    assert by["ITC"]["pe"]["display_na"] == "N/A (not fetched yet)"
    assert by["MOSCHIP"]["market_cap"]["display_na"] == "N/A (not provided by source)"
    # rejected / missing values are stored without a value — nothing invented
    bad = session.scalars(select(InstrumentFact).where(InstrumentFact.status != "OK")).all()
    assert bad and all(f.value is None for f in bad)


def test_manual_values_are_tagged_and_win(session, workbook):
    import_workbook(session, workbook)
    fs.refresh_fundamentals(session, fetch=fake_info, statements=False)
    lt = session.scalar(select(Instrument).where(Instrument.symbol == "LT"))
    fs.set_manual(session, lt.id, "roce", "15.2", "Annual report FY2026, p.212", date(2026, 3, 31))
    c = next(c for r in fs.report(session)["stocks"] if r["symbol"] == "LT" for c in r["metrics"] if c["metric"] == "roce")
    assert c["value"] == "0.152" and c["manual"] and c["source"] == "manual: Annual report FY2026, p.212"
    assert c["as_of"] == "2026-03-31"
    fs.delete_manual(session, lt.id, "roce")
    c = next(c for r in fs.report(session)["stocks"] if r["symbol"] == "LT" for c in r["metrics"] if c["metric"] == "roce")
    assert c["display_na"] == "N/A (no reliable source)"
    with pytest.raises(ManualEntryError):
        fs.set_manual(session, lt.id, "expense_ratio", "0.2", "x", date(2026, 3, 31))  # fund-only metric


def test_fund_facts_tracking_only_for_index_funds(session, workbook):
    import_workbook(session, workbook)
    out = {f["name"].split(" ")[0]: {c["metric"]: c for c in f["metrics"]} for f in fs.report(session)["funds"]}
    assert out["HDFC"]["tracking_error"]["display_na"] == "Not applicable (not an index fund)"
    assert out["ICICI"]["tracking_error"]["display_na"] == "N/A (no reliable source)"
    assert out["ICICI"]["category"]["display_na"] == "N/A (not fetched yet)"
    kotak = session.scalar(select(Instrument).where(Instrument.name.like("Kotak%")))
    fs.set_manual(session, kotak.id, "expense_ratio", "0.15", "Kotak factsheet Sep 2026", date(2026, 9, 30))
    out = {f["name"].split(" ")[0]: {c["metric"]: c for c in f["metrics"]} for f in fs.report(session)["funds"]}
    assert out["Kotak"]["expense_ratio"]["value"] == "0.0015" and out["Kotak"]["expense_ratio"]["manual"]
