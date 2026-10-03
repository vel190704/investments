from decimal import Decimal as D

import pytest

from app.calc.allocation import (
    asset_class_of, derive_category, round_weights_for_display, weights,
)
from app.calc.concentration import THRESHOLDS, company_concentration, level_for


def test_weights_sum_to_one_and_use_value_not_quantity():
    values = {"LT": 369340, "ITC": 26640, "MF": 799999, "ETF": 70331}
    w = weights(values)
    assert abs(sum(w.values()) - 1) < D("1e-25")
    assert w["LT"] > w["ITC"]  # 1 share each, but weights follow market value


@pytest.mark.parametrize("n", [3, 7, 19])
def test_display_rounding_sums_to_exactly_100(n):
    values = {i: 1000 + i * 37 for i in range(n)}
    disp = round_weights_for_display(weights(values), 1)
    assert sum(disp.values()) == D("100.0")


def test_weights_of_empty_portfolio():
    assert weights({"a": 0}) == {"a": D(0)}


def test_asset_classes():
    assert asset_class_of("MF", "DOMESTIC") == "Mutual funds"
    assert asset_class_of("STOCK", "DOMESTIC") == "Indian stocks"
    assert asset_class_of("ETF", "INTERNATIONAL") == "International ETFs"
    assert asset_class_of("ETF", "DOMESTIC") == "Indian ETFs"


def test_derived_categories():
    assert derive_category("MF", "Kotak Nifty Next 50 Index Fund - Direct - Growth", "DOMESTIC") == "Nifty Next 50 index fund"
    assert derive_category("MF", "ICICI Prudential Nifty 50 Index Fund - Direct - Growth", "DOMESTIC") == "Nifty 50 index fund"
    assert derive_category("MF", "HDFC Mid Cap Fund - Direct - Growth", "DOMESTIC") == "Mid-cap fund"


def test_threshold_boundaries():
    t = THRESHOLDS["largest_company_of_direct_equity"]
    assert level_for(D("0.1499"), t) == "LOW"
    assert level_for(D("0.15"), t) == "MODERATE"
    assert level_for(D("0.25"), t) == "HIGH"


def test_company_concentration_flags_have_reason_and_calculation():
    c = company_concentration([("LT", 380000), ("ITC", 310000), ("SBIN", 310000)], 2000000)
    flags = {f["key"]: f for f in c["flags"]}
    f = flags["largest_company_of_direct_equity"]
    assert f["level"] == "HIGH"
    assert f["reason"] == "LT is 38.0% of direct equity."
    assert f["calculation"].startswith("₹3,800.00 / ₹10,000.00 = 38.0%")
    assert flags["top3_of_direct_equity"]["level"] == "HIGH"  # 100%
    # HHI = 38² + 31² + 31² = 3366
    assert c["hhi"] == D(3366)
    assert flags["hhi_direct_equity"]["level"] == "HIGH"
    assert flags["largest_company_of_portfolio"]["value"] == "19.0%"


def test_company_concentration_well_diversified_is_low():
    c = company_concentration([(f"S{i}", 1000) for i in range(20)], 100000)
    levels = {f["key"]: f["level"] for f in c["flags"]}
    assert levels["largest_company_of_direct_equity"] == "LOW"
    assert levels["hhi_direct_equity"] == "LOW"


def test_concentration_without_stocks():
    c = company_concentration([], 1000)
    assert c["flags"] == [] and c["largest"] is None
