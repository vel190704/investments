from datetime import date
from decimal import Decimal as D

from app.calc.lookthrough import (
    DirectHolding, FundLook, FundRow, company_exposure, is_equity_isin, is_stale, months_between, pairwise_overlap,
    sector_lookthrough,
)

LT, RIL, HDFCB, INFY = "INE018A01030", "INE002A01018", "INE040A01034", "INE009A01021"
TBILL = "IN002024Z123"  # government security: not an equity ISIN


def R(isin, name, w, industry=None, equity=True):
    return FundRow(isin, name, industry, D(w), equity)


# Portfolio: ₹10,000 total
#   LT direct ₹1,000; Fund A (₹4,000) holds LT 10%, RIL 50%; Fund B (₹5,000) holds LT 4%, HDFCB 20%, T-bill 10%
DIRECT = [DirectHolding(1, "LT", LT, 100_000, "STOCK", "Construction")]
FUNDS = [
    FundLook(10, "Fund A", 400_000, [R(LT, "Larsen & Toubro Ltd", "0.10"), R(RIL, "Reliance", "0.50")], "A", date(2026, 9, 30)),
    FundLook(11, "Fund B", 500_000, [R(LT, "Larsen & Toubro Ltd", "0.04"), R(HDFCB, "HDFC Bank", "0.20"),
                                     R(TBILL, "91D T-Bill", "0.10", equity=False)], "B", date(2026, 9, 30)),
]


def test_equity_isin_rule():
    assert is_equity_isin(LT) and is_equity_isin(INFY)
    assert not is_equity_isin("INE002A08534")  # debenture of the same issuer
    assert not is_equity_isin(TBILL) and not is_equity_isin(None)


def test_company_held_directly_and_in_two_funds():
    out = company_exposure(DIRECT, FUNDS, 1_000_000)
    lt = next(c for c in out["companies"] if c["isin"] == LT)
    # direct 1,000 + 4,000×10% + 5,000×4% = 1,000 + 400 + 200 = 1,600 -> 16%
    assert lt["direct_paise"] == 100_000 and lt["indirect_paise"] == 60_000 and lt["total_paise"] == 160_000
    assert D(lt["total_pct"]) == D("0.16") and D(lt["direct_pct"]) == D("0.1") and D(lt["indirect_pct"]) == D("0.06")
    assert [(v["fund"], v["paise"]) for v in lt["via"]] == [("Fund A", 40_000), ("Fund B", 20_000)]
    assert lt["level"] == "HIGH" and lt["name"] == "LT"
    assert lt["reason"] == ("LT is 16.0% of the portfolio including indirect exposure "
                            "(10.0% held directly; 4.0% through Fund A; 2.0% through Fund B).")
    ril = next(c for c in out["companies"] if c["isin"] == RIL)
    assert ril["total_paise"] == 200_000 and ril["direct_paise"] == 0 and ril["level"] == "HIGH"
    assert all(c["isin"] != TBILL for c in out["companies"])  # debt rows are not companies


def test_matching_is_by_isin_never_by_name():
    direct = [DirectHolding(1, "Larsen & Toubro Ltd", None, 100_000, "STOCK", "Construction")]  # no ISIN
    out = company_exposure(direct, FUNDS, 1_000_000)
    lt = next(c for c in out["companies"] if c["isin"] == LT)
    assert lt["direct_paise"] == 0  # same name, but not combined
    assert out["unmatched_direct"][0]["name"] == "Larsen & Toubro Ltd"


def test_funds_without_disclosure_are_listed_not_guessed():
    funds = FUNDS + [FundLook(12, "Fund C", 300_000, None)]
    out = company_exposure(DIRECT, funds, 1_300_000)
    assert out["not_looked_through"] == [{"instrument_id": 12, "name": "Fund C", "value_paise": 300_000}]


def test_thresholds_low_moderate():
    out = company_exposure([], [FundLook(10, "F", 1_000_000, [R(INFY, "Infosys", "0.06"), R(RIL, "RIL", "0.049")])],
                           1_000_000)
    lv = {c["name"]: c["level"] for c in out["companies"]}
    assert lv == {"Infosys": "MODERATE", "RIL": "LOW"}


def test_pairwise_overlap_sum_of_min_weights():
    ov = pairwise_overlap(FUNDS)
    assert len(ov) == 1 and D(ov[0]["overlap"]) == D("0.04")  # only LT common: min(10%, 4%)
    assert ov[0]["common"][0]["isin"] == LT
    a = FundLook(1, "N50", 1, [R(LT, "LT", "0.05"), R(RIL, "RIL", "0.10"), R(HDFCB, "HDFCB", "0.12")])
    b = FundLook(2, "Alt", 1, [R(LT, "LT", "0.03"), R(RIL, "RIL", "0.20"), R(INFY, "INFY", "0.30")])
    assert D(pairwise_overlap([a, b])[0]["overlap"]) == D("0.13")  # 3% + 10%


def test_sector_lookthrough_uses_nse_by_isin_and_reports_non_equity():
    rows = sector_lookthrough(DIRECT, FUNDS, {LT: "Construction", RIL: "Oil, Gas & Consumable Fuels"}, 1_000_000)
    by = {r["sector"]: r for r in rows}
    assert by["Construction"]["value_paise"] == 160_000  # direct LT + LT via both funds
    assert by["Oil, Gas & Consumable Fuels"]["value_paise"] == 200_000
    assert "Unclassified (AMC gave no industry)" in by  # HDFC Bank: no NSE map, no AMC label in fixture
    # Fund A: 40% undisclosed; Fund B: 10% T-bill + 66% undisclosed -> 1,600 + 500 + 3,300 = 5,400
    assert by["Debt, cash & other inside funds"]["value_paise"] == 540_000
    assert sum(r["value_paise"] for r in rows) == 1_000_000


def test_staleness():
    assert months_between(date(2026, 7, 31), date(2026, 10, 3)) == 2
    assert not is_stale(date(2026, 8, 31), date(2026, 10, 3))
    assert not is_stale(date(2026, 7, 31), date(2026, 10, 3))
    assert is_stale(date(2026, 7, 31), date(2026, 11, 1))
    assert is_stale(date(2026, 6, 30), date(2026, 10, 3))
