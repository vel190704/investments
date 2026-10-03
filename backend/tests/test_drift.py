from decimal import Decimal as D

import pytest

from app.calc.drift import drift, fold_classes, status_for

T = {"Mutual funds": D("0.5"), "Indian stocks": D("0.3"), "International ETFs": D("0.1"), "Gold": D("0.05"),
     "Debt/Cash": D("0.05")}


def test_status_band_edges():
    assert status_for(D("5"), D("5")) == "WITHIN BAND"
    assert status_for(D("5.01"), D("5")) == "OVERWEIGHT"
    assert status_for(D("-5"), D("5")) == "WITHIN BAND"
    assert status_for(D("-5.01"), D("5")) == "UNDERWEIGHT"


def test_drift_rows_reason_and_calculation():
    values = fold_classes({"Mutual funds": 4000, "Indian stocks": 5500, "International ETFs": 500}, list(T))
    rows = {r["asset_class"]: r for r in drift(values, 10000, T, D(5))}
    mf = rows["Mutual funds"]
    assert mf["status"] == "UNDERWEIGHT" and D(mf["deviation_pp"]) == D(-10)
    assert mf["reason"] == "Mutual funds is 40.0% vs target 50.0%: 10.0 pp below, outside the ±5 pp band."
    assert mf["calculation"] == "₹40.00 / ₹100.00 = 40.0%; 40.0% − 50.0% = -10.0 pp; UNDERWEIGHT because < −5 pp."
    assert mf["value_vs_target_paise"] == -1000
    assert rows["Indian stocks"]["status"] == "OVERWEIGHT"
    assert rows["International ETFs"]["status"] == "WITHIN BAND"
    assert rows["Gold"]["status"] == "WITHIN BAND" and not rows["Gold"]["held"]  # 0% vs 5%: -5 pp, at the edge
    assert sum(D(r["current"]) for r in rows.values()) == 1


def test_indian_etfs_fold_into_indian_stocks():
    assert fold_classes({"Indian ETFs": 100, "Indian stocks": 50}, list(T))["Indian stocks"] == 150


@pytest.mark.parametrize("tol,status", [(D(2), "OVERWEIGHT"), (D(30), "WITHIN BAND")])
def test_tolerance_is_configurable(tol, status):
    rows = drift({"Indian stocks": 10000}, 10000, {"Indian stocks": D("0.75"), "Gold": D("0.25")}, tol)
    assert rows[0]["status"] == status
