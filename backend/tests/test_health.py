from decimal import Decimal as D

from app.calc import health as h
from app.calc.concentration import Threshold
from app.calc.lookthrough import DirectHolding, FundLook, FundRow, company_exposure, pairwise_overlap
from tests.test_lookthrough import DIRECT, FUNDS, LT

T_CO = Threshold("c", "c", D("0.05"), D("0.10"), "fraction", "")
T_OV = Threshold("o", "o", D("0.30"), D("0.50"), "fraction", "")


def test_company_dimension_reason_includes_indirect_exposure():
    comp = company_exposure(DIRECT, FUNDS, 1_000_000)["companies"]
    d = h.company_dimension(comp, True, T_CO)
    assert d["level"] == "HIGH" and d["value"] == "20.0%"  # RIL 2,000 via Fund A is the largest
    assert d["reason"].startswith("Reliance is 20.0% of the portfolio including indirect exposure (20.0% through Fund A)")
    lt_only = [c for c in comp if c["isin"] == LT]
    d = h.company_dimension(lt_only, True, T_CO)
    assert d["reason"] == ("LT is 16.0% of the portfolio including indirect exposure (10.0% held directly; "
                           "4.0% through Fund A; 2.0% through Fund B).")
    assert "HIGH by the rule LOW < 5% ≤ MODERATE < 10% ≤ HIGH" in d["calculation"]


def test_company_dimension_direct_only_says_funds_missing():
    comp = company_exposure([DirectHolding(1, "LT", LT, 40_000, "STOCK", "x")], [FundLook(2, "F", 960_000, None)],
                            1_000_000)["companies"]
    d = h.company_dimension(comp, False, T_CO)
    assert d["level"] == "LOW" and "(direct holding)" in d["reason"] and "upload fund disclosures" in d["reason"]


def test_drift_dimension_levels():
    rows = [{"deviation_pp": "-6", "reason": "Gold is 0.0% vs target 6.0%…", "calculation": "c"},
            {"deviation_pp": "3", "reason": "r", "calculation": "c"}]
    assert h.drift_dimension(rows, D(5), D(2))["level"] == "MODERATE"
    assert h.drift_dimension(rows, D(10), D(2))["level"] == "LOW"
    assert h.drift_dimension(rows, D(2), D(2))["level"] == "HIGH"
    assert not h.drift_dimension(None, D(5), D(2))["available"]


def test_overlap_dimension():
    a = FundLook(1, "A", 1, [FundRow(LT, "LT", None, D("0.6"), True)])
    b = FundLook(2, "B", 1, [FundRow(LT, "LT", None, D("0.4"), True)])
    d = h.overlap_dimension(pairwise_overlap([a, b]), T_OV)
    assert d["level"] == "MODERATE" and d["value"] == "40.0%" and "A and B overlap by 40.0%" in d["reason"]
    assert not h.overlap_dimension([], T_OV)["available"]


def test_info_only_dimensions_have_no_level():
    geo = {"international_pct": "0.037", "international_paise": 70331,
           "regions": [{"region": "Hong Kong/China", "pct": "0.024"}]}
    d = h.international_dimension(geo)
    assert d["level"] is None and d["info_only"] and "no objective threshold" in d["reason"]
    d = h.liquidity_dimension(1_000, 3_000, 4_000)
    assert d["level"] is None and d["value"] == "25.0% direct / 75.0% funds"


def test_volatility_needs_stored_history():
    short = {"LT": (100, [D(100)] * 10)}
    d = h.volatility_dimension(short)
    assert not d["available"] and "at least 60" in d["reason"] and "never downloaded" in d["reason"]
    prices = [D(100) * (D("1.01") if i % 2 else D("0.99")) ** 0 * (D(1) + D(i % 3) / 100) for i in range(80)]
    d = h.volatility_dimension({"LT": (100, prices)})
    assert d["available"] and d["level"] is None and d["value"].endswith("% a year")


def test_volatility_formula():
    closes = [D(100), D(110), D(99), D(108.9)] * 20
    v = h.annualised_volatility(closes)
    rets = [float(closes[i] / closes[i - 1]) - 1 for i in range(1, len(closes))]
    m = sum(rets) / len(rets)
    expected = (sum((r - m) ** 2 for r in rets) / (len(rets) - 1)) ** 0.5 * 252 ** 0.5
    assert abs(v - expected) < 1e-12


def test_emergency_dimension():
    st = {"percent_complete": "0.2777", "target_months": 6, "balance_paise": 5_000_000, "target_paise": 18_000_000}
    d = h.emergency_dimension(st, D("0.5"), D("1.0"))
    assert d["level"] == "HIGH" and "27.8% of your 6-month target" in d["reason"]
    assert h.emergency_dimension({**st, "percent_complete": "0.75"}, D("0.5"), D("1.0"))["level"] == "MODERATE"
    assert h.emergency_dimension({**st, "percent_complete": "1.2"}, D("0.5"), D("1.0"))["level"] == "LOW"
    assert not h.emergency_dimension(None, D("0.5"), D("1.0"))["available"]


def test_sector_dimension():
    from app.calc.sectors import sector_metrics

    rows = [{"sector": "Construction", "value_paise": 500}, {"sector": "Banks", "value_paise": 300},
            {"sector": "IT", "value_paise": 200}, {"sector": "Debt, cash & other inside funds", "value_paise": 9000}]
    m = sector_metrics(rows)
    d = h.sector_dimension(m)
    assert d["level"] == "HIGH" and d["value"] == "50.0%"  # debt rows excluded from equity sectors
    assert "Sector HHI is 3,800 across 3 sectors (HIGH)" in d["reason"]
