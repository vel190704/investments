from decimal import Decimal as D

from app.calc.planner import PlanLine, plan_mode, split_paise, targets_mode
from app.calc.simulator import SimHolding

CLASSES = ["Mutual funds", "Indian stocks", "International ETFs", "Gold", "Debt/Cash"]


def H(i, short, at, cls, cat, price, value):
    return SimHolding(i, short, short, at, cls, cat, D(price), value)


BOOK = [
    H(1, "LT", "STOCK", "Indian stocks", "Indian stock", "3693.40", 369340),
    H(2, "ITC", "STOCK", "Indian stocks", "Indian stock", "255.90", 25590),
    H(3, "MAFANG", "ETF", "International ETFs", "International ETF", "248.21", 24821),
    H(4, "ICICI Nifty 50", "MF", "Mutual funds", "Nifty 50 index fund", "237.3337", 388254),
    H(5, "HDFC Mid Cap", "MF", "Mutual funds", "Mid-cap fund", "219.441", 240178),
    H(6, "Kotak Next 50", "MF", "Mutual funds", "Nifty Next 50 index fund", "20.2442", 146521),
]
PLAN = [PlanLine("Direct stocks & ETFs", True, D("0.6")), PlanLine("HDFC Mid Cap", False, D("0.15"), 5),
        PlanLine("ICICI Nifty 50", False, D("0.15"), 4), PlanLine("Kotak Next 50", False, D("0.1"), 6)]
TARGETS = {"Mutual funds": D("0.5"), "Indian stocks": D("0.3"), "International ETFs": D("0.1"), "Gold": D("0.05"),
           "Debt/Cash": D("0.05")}


def test_split_paise_exact():
    parts = split_paise(1_000_000, {"a": D("0.6"), "b": D("0.15"), "c": D("0.15"), "d": D("0.1")})
    assert parts == {"a": 600_000, "b": 150_000, "c": 150_000, "d": 100_000}
    assert sum(split_paise(1001, {"x": D(1), "y": D(1), "z": D(1)}).values()) == 1001


def test_plan_mode_without_picks_keeps_bucket_at_class_level():
    r = plan_mode(BOOK, 1_000_000, PLAN, [], CLASSES, None, D(5))
    mf_lines = {l["instrument_id"]: l["amount_paise"] for l in r["lines"] if l["instrument_id"]}
    assert mf_lines == {5: 150_000, 4: 150_000, 6: 100_000}
    cls_lines = {l["asset_class"]: l["amount_paise"] for l in r["lines"] if l["instrument_id"] is None}
    assert sum(cls_lines.values()) == 600_000 and set(cls_lines) == {"Indian stocks", "International ETFs"}
    assert r["invested_paise"] == 1_000_000 and r["total_after_paise"] == r["total_before_paise"] + 1_000_000
    assert sum(D(c["projected"]) for c in r["asset_classes"]) == 1


def test_plan_mode_with_picks_whole_units():
    r = plan_mode(BOOK, 1_000_000, PLAN, [2], CLASSES, None, D(5))  # ₹6,000 bucket to ITC @ 255.90
    itc = next(l for l in r["lines"] if l["instrument_id"] == 2)
    assert itc["units"] == "23" and itc["invested_paise"] == 588_570 and itc["uninvested_paise"] == 11_430
    assert r["uninvested_paise"] == 11_430


def test_targets_mode_requires_targets():
    r = targets_mode(BOOK, 1_000_000, PLAN, [], CLASSES, None, D(5))
    assert not r["available"] and "Set your targets" in r["reason"]


def test_targets_mode_fills_gaps_and_never_sells():
    # book: MF 64.9%, Indian stocks 33.1%, Intl 2.1% of ₹11,947; budget ₹1,000
    r = targets_mode(BOOK, 100_000, PLAN, [], CLASSES, TARGETS, D(5))
    add = {c["asset_class"]: c["add_paise"] for c in r["asset_classes"]}
    assert sum(add.values()) == 100_000 and all(v >= 0 for v in add.values())
    # Mutual funds are far above their 50% target: no new money goes there (nothing is sold either)
    assert add["Mutual funds"] == 0 and add["Indian stocks"] == 0
    # Gold and Debt/Cash are not held: amounts stay at class level
    gold = next(l for l in r["lines"] if l["asset_class"] == "Gold")
    assert gold["instrument_id"] is None and "no Gold instrument" in gold["note"]


def test_targets_mode_large_budget_fills_all_gaps_then_by_target():
    total = sum(h.value_paise for h in BOOK)
    budget = total * 10
    r = targets_mode(BOOK, budget, PLAN, [], CLASSES, TARGETS, D(5))
    proj = {c["asset_class"]: D(c["projected"]) for c in r["asset_classes"]}
    for c, t in TARGETS.items():
        if c != "Indian stocks":  # stocks start overweight and are never sold
            assert abs(proj[c] - t) < D("0.06")


def test_considerations_have_reasons_and_neutral_wording():
    r = targets_mode(BOOK, 100_000, PLAN, [], CLASSES, TARGETS, D(5))
    kinds = {c["kind"] for c in r["considerations"]}
    assert {"OVERWEIGHT", "CONCENTRATION", "INTERNATIONAL"} <= kinds
    for c in r["considerations"]:
        assert c["text"].startswith("Allocation consideration:") and c["calculation"]
    text = " ".join(c["text"] for c in r["considerations"]).lower()
    for word in (" buy", " sell ", "should", "recommend"):
        assert word not in text
    over = next(c for c in r["considerations"] if c["kind"] == "OVERWEIGHT")
    assert over["text"].startswith("Allocation consideration: after this contribution, Mutual funds would be ")
    intl = next(c for c in r["considerations"] if c["kind"] == "INTERNATIONAL")
    assert "NYSE FANG+" in intl["text"]
