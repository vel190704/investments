import re
from decimal import Decimal as D

import pytest

from app.calc.simulator import (
    SimHolding, default_scenarios, instrument_scenario, run_scenario, simulate, snapshot,
)


def H(i, name, short, at, cls, cat, price, value):
    return SimHolding(i, name, short, at, cls, cat, D(price), value)


@pytest.fixture
def book():
    return [
        H(1, "Larsen & Toubro", "LT", "STOCK", "Indian stocks", "Indian stock", "3693.40", 369340),
        H(2, "ITC", "ITC", "STOCK", "Indian stocks", "Indian stock", "266.40", 26640),
        H(3, "Mirae FANG+", "MAFANG", "ETF", "International ETFs", "International ETF", "248.21", 24821),
        H(4, "ICICI Nifty 50", "ICICI Nifty 50", "MF", "Mutual funds", "Nifty 50 index fund", "237.33", 388270),
        H(5, "HDFC Mid Cap", "HDFC Mid Cap", "MF", "Mutual funds", "Mid-cap fund", "219.44", 240178),
        H(6, "Kotak Next 50", "Kotak Next 50", "MF", "Mutual funds", "Nifty Next 50 index fund", "20.24", 146524),
    ]


def total(ws):
    return sum(D(x["after"]) for x in ws)


def test_before_weights_sum_to_one(book):
    snap = snapshot(book)
    assert abs(sum(snap["asset_classes"].values()) - 1) < D("1e-25")
    assert abs(sum(snap["mf_split"].values()) - 1) < D("1e-25")


def test_add_to_fund_moves_weights_and_conserves_total(book):
    r = run_scenario(book, 100000, instrument_scenario(book[3]))
    assert r["invested_paise"] == 100000 and r["uninvested_paise"] == 0
    assert r["total_after_paise"] == r["total_before_paise"] + 100000
    assert abs(total(r["asset_classes"]) - 1) < D("1e-25")
    assert abs(total(r["mf_split"]) - 1) < D("1e-25")
    mf = next(x for x in r["asset_classes"] if x["name"] == "Mutual funds")
    assert D(mf["after"]) > D(mf["before"])
    lt = next(x for x in r["top_companies"] if x["name"] == "LT")
    assert D(lt["after"]) < D(lt["before"])  # dilution
    assert r["sentences"][0].startswith("Adding ₹1,000 here would raise your Nifty 50 index fund exposure from ")
    assert r["legs"][0]["units"] == "4.213"  # 1000 / 237.33, 3 dp, rounded down


def test_stock_whole_units_only(book):
    r = run_scenario(book, 100000, instrument_scenario(book[1]))  # ITC @ 266.40
    assert r["legs"][0]["units"] == "3"
    assert r["invested_paise"] == 79920 and r["uninvested_paise"] == 20080
    assert any("would remain uninvested" in s for s in r["sentences"])


def test_amount_below_one_share(book):
    r = run_scenario(book, 50000, instrument_scenario(book[0]))  # ₹500 < LT price
    assert r["invested_paise"] == 0
    assert "below the price of one unit" in r["sentences"][0]
    assert all(x["before"] == x["after"] for x in r["asset_classes"])


def test_plan_split_proportions(book):
    plan = {4: D("0.15"), 5: D("0.15"), 6: D("0.10")}
    sc = {s.key: s for s in default_scenarios(book, plan)}["mf_plan_split"]
    assert sc.allocations == {4: D("0.375"), 5: D("0.375"), 6: D("0.25")}
    r = run_scenario(book, 100000, sc)
    assert [l["amount_paise"] for l in r["legs"]] == [37500, 37500, 25000]
    assert r["invested_paise"] == 100000


def test_default_scenarios_one_per_fund_plus_split(book):
    keys = [s.key for s in default_scenarios(book, {4: D("0.15"), 5: D("0.15"), 6: D("0.1")})]
    assert keys == ["mf:4", "mf:5", "mf:6", "mf_plan_split"]


def test_language_is_neutral(book):
    res = simulate(book, 1000000, default_scenarios(book, {4: D("0.15"), 5: D("0.15"), 6: D("0.1")})
                   + [instrument_scenario(book[0])])
    text = " ".join(" ".join(s["sentences"]) for s in res["scenarios"]).lower()
    assert not re.search(r"\b(buy|sell|should|recommend|will rise|will fall)\b", text)
    assert res["assumptions"]


def test_invalid_amount(book):
    with pytest.raises(ValueError):
        simulate(book, 0, [])
