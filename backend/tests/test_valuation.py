import json
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from app.calc import valuation as v
from app.calc.framework import FAILS, MEETS, NA, NOT_APPLICABLE, checks

FIX = Path(__file__).parent / "fixtures"
LT = json.loads((FIX / "yf_LT_statements.json").read_text())


def P(info=None, **stmts):
    return {"info": info or {}, **stmts}


# ---- recorded real response (LT.NS, 2026-10-17) ----
def test_recorded_fixture_metrics():
    r = v.compute_all(LT)
    assert r["ps"].value == D("1.680832")
    assert r["peg"].status == "OK" and r["peg"].value == D("30.08793") / D("14.00")
    assert r["peg"].inputs["pe"] == "30.08793" and r["peg"].inputs["earnings_growth"] == "0.14"
    assert r["fcf_latest"].value == D("119317800000.0") and r["fcf_latest"].as_of == "2026-03-31"
    assert len(r["fcf_latest"].inputs["trend"]) == 4  # the NaN year is dropped, never filled
    assert r["fcf_yield"].value == D("119317800000.0") / D("4990403870720")
    assert r["interest_coverage"].status in ("OK", "N/A")


# ---- PEG ----
@pytest.mark.parametrize("info,reason", [
    ({}, "P/E not available"),
    ({"trailingPE": 20}, "earnings growth not provided"),
    ({"trailingPE": 20, "earningsGrowth": 0}, "zero or negative"),
    ({"trailingPE": 20, "earningsGrowth": -0.2}, "zero or negative"),
    ({"trailingPE": 20, "earningsGrowth": 25}, "implausible earnings growth"),
    ({"trailingPE": 5000, "earningsGrowth": 0.1}, "implausible P/E"),
    ({"trailingPE": 900, "earningsGrowth": 0.05}, "implausible PEG"),
])
def test_peg_na_cases(info, reason):
    r = v.peg(P(info))
    assert r.status == "N/A" and reason in r.reason and r.formula == "PEG = P/E ÷ (earnings growth × 100)"


def test_peg_value():
    r = v.peg(P({"trailingPE": 30, "earningsGrowth": 0.15}))
    assert r.value == D(2) and r.inputs["growth_basis"].startswith("Yahoo earningsGrowth")


# ---- P/S ----
def test_ps_cases():
    assert v.ps(P({"priceToSalesTrailing12Months": 2.5})).value == D("2.5")
    assert "not provided" in v.ps(P()).reason
    assert "implausible" in v.ps(P({"priceToSalesTrailing12Months": 500})).reason
    assert "implausible" in v.ps(P({"priceToSalesTrailing12Months": -1})).reason


# ---- FCF ----
CF = {"Free Cash Flow": {"2024-03-31": 100.0, "2025-03-31": 80.0, "2026-03-31": None}}
INC = {"Total Revenue": {"2024-03-31": 1000.0, "2025-03-31": 1000.0}, "EBIT": {"2025-03-31": 300.0},
       "Interest Expense": {"2025-03-31": 50.0}}


def test_fcf_latest_margin_yield():
    p = P({"marketCap": 4000}, cashflow=CF, income=INC)
    assert v.fcf_latest(p).value == D("80.0") and v.fcf_latest(p).as_of == "2025-03-31"
    assert v.fcf_margin(p).value == D("0.08")
    assert v.fcf_yield(p).value == D("0.02")


def test_fcf_na_cases():
    assert "not reported" in v.fcf_latest(P()).reason
    assert "not both reported" in v.fcf_margin(P(cashflow=CF)).reason
    assert "market cap not provided" in v.fcf_yield(P(cashflow=CF)).reason
    neg_rev = P(cashflow=CF, income={"Total Revenue": {"2025-03-31": -5.0}})
    assert "revenue is zero or negative" in v.fcf_margin(neg_rev).reason


# ---- interest coverage ----
def test_interest_coverage():
    assert v.interest_coverage(P(income=INC)).value == D(6)
    assert "not both reported" in v.interest_coverage(P(income={"EBIT": {"2025-03-31": 1.0}})).reason
    zero = P(income={"EBIT": {"2025-03-31": 1.0}, "Interest Expense": {"2025-03-31": 0.0}})
    assert "zero or not positive" in v.interest_coverage(zero).reason


# ---- history and historical P/E ----
def test_history_pe_only_from_stored_prices():
    series = v.annual(P(cashflow=CF, income={**INC, "Net Income": {"2025-03-31": 120.0}, "Diluted EPS": {"2025-03-31": 10.0}},
                        balance={"Stockholders Equity": {"2025-03-31": 800.0}}))
    rows = {r["fiscal_year_end"]: r for r in v.history(series, {})}
    assert rows["2025-03-31"]["roe"] == "0.15" and rows["2025-03-31"]["net_margin"] == "0.12"
    assert rows["2025-03-31"]["pe"]["value"] is None and "never estimated" in rows["2025-03-31"]["pe"]["reason"]
    rows = {r["fiscal_year_end"]: r for r in v.history(series, {date(2025, 4, 3): D("250")})}
    assert rows["2025-03-31"]["pe"]["value"] == "25" and rows["2025-03-31"]["pe"]["price_date"] == "2025-04-03"
    far = {r["fiscal_year_end"]: r for r in v.history(series, {date(2025, 5, 30): D("250")})}
    assert far["2025-03-31"]["pe"]["value"] is None


def test_peer_median_needs_three():
    assert v.median_or_na([D(10), D(20)])[0] is None
    assert "only 2 peer(s)" in v.median_or_na([D(10), D(20), None])[1]
    assert v.median_or_na([D(10), D(20), D(40)])[0] == D(20)


# ---- framework check ----
M = {"pe": {"value": D("20"), "source": "yf"}, "peg": {"value": D("0.8"), "source": "computed"},
     "roe": {"value": D("0.18"), "source": "yf"}, "debt_to_equity": {"value": D("2.5"), "source": "yf"},
     "interest_coverage": {"value": D("4"), "source": "computed"}}


def by_key(out):
    return {c["key"]: c for c in out}


def test_framework_meets_and_fails_without_any_score():
    out = by_key(checks(M, D("25"), None, None, [("2025-03-31", D(100)), ("2026-03-31", D(80))], "Construction"))
    assert out["pe_vs_peers"]["status"] == MEETS and out["peg"]["status"] == MEETS and out["roe"]["status"] == MEETS
    assert out["debt_to_equity"]["status"] == FAILS
    assert out["pe_vs_history"]["status"] == NA and "historical P/E" in out["pe_vs_history"]["reason"]
    assert out["fcf_positive"]["status"] == MEETS and out["fcf_not_declining"]["status"] == FAILS
    assert all(set(c) == {"key", "title", "status", "value", "rule", "reason", "sources"} for c in out.values())


def test_sector_rules_make_bank_leverage_not_applicable():
    out = by_key(checks(M, None, "N/A: only 1 peer(s) have a value", None, [], "Financial Services"))
    assert out["debt_to_equity"]["status"] == NOT_APPLICABLE and "Financial Services" in out["debt_to_equity"]["reason"]
    assert out["interest_coverage"]["status"] == NOT_APPLICABLE
    assert out["pe_vs_peers"]["status"] == NA and "only 1 peer" in out["pe_vs_peers"]["reason"]
    assert out["fcf_positive"]["status"] == NA
    custom = by_key(checks(M, None, None, None, [], "Construction", sector_rules={"Construction": ["debt_to_equity"]}))
    assert custom["debt_to_equity"]["status"] == NOT_APPLICABLE


def test_rubric_thresholds_are_editable():
    out = by_key(checks(M, D("19"), None, None, [], "X", rubric={"pe_vs_peer_tolerance_pct": "10", "peg_max": "0.5",
                                                                  "roe_min_pct": "20", "de_max": "3"}))
    assert out["pe_vs_peers"]["status"] == MEETS  # 20 <= 19 × 1.1
    assert out["peg"]["status"] == FAILS and out["roe"]["status"] == FAILS and out["debt_to_equity"]["status"] == MEETS
