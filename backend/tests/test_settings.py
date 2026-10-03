from decimal import Decimal as D

import pytest

from app.calc.concentration import THRESHOLDS
from app.services import settings as st

GOOD_TARGETS = {"Mutual funds": "50", "Indian stocks": "30", "International ETFs": "10", "Gold": "5",
                "Debt/Cash": "5"}


def test_targets_unset_by_default(session):
    assert st.targets(session) is None and not st.is_set(session, "targets")
    assert st.get(session, "emergency_fund") is None


def test_targets_must_total_100(session):
    st.put(session, "targets", GOOD_TARGETS)
    assert st.targets(session)["Mutual funds"] == D("0.5")
    with pytest.raises(st.SettingsError, match="total exactly 100"):
        st.put(session, "targets", {**GOOD_TARGETS, "Gold": "6"})
    with pytest.raises(st.SettingsError, match="exactly these classes"):
        st.put(session, "targets", {"Mutual funds": "100"})
    with pytest.raises(st.SettingsError):
        st.put(session, "targets", {**GOOD_TARGETS, "Gold": "-5", "Debt/Cash": "15"})
    assert st.put(session, "targets", {**GOOD_TARGETS, "Mutual funds": "49.5", "Gold": "5.5"})["Gold"] == "5.5"


def test_reset_returns_to_unset(session):
    st.put(session, "targets", GOOD_TARGETS)
    st.reset(session, "targets")
    assert st.targets(session) is None


def test_concentration_defaults_and_validation(session):
    th = st.concentration_thresholds(session)
    assert th["largest_company_of_direct_equity"].low == THRESHOLDS["largest_company_of_direct_equity"].low
    st.put(session, "concentration", {"largest_company_of_direct_equity": {"low": "0.2", "high": "0.3"}})
    th = st.concentration_thresholds(session)
    assert th["largest_company_of_direct_equity"].high == D("0.3")
    assert th["hhi_direct_equity"].low == D(1500)  # untouched keys keep defaults
    with pytest.raises(st.SettingsError, match="low must be below high"):
        st.put(session, "concentration", {"top3_of_direct_equity": {"low": "0.6", "high": "0.4"}})


def test_projection_placeholders_flagged(session):
    p = st.get(session, "projection")
    assert p["reviewed"] is False and (p["conservative"], p["base"], p["higher"]) == ("6", "9", "12")
    with pytest.raises(st.SettingsError, match="ordered"):
        st.put(session, "projection", {**p, "base": "20"})
    assert st.put(session, "projection", {**p, "reviewed": True})["reviewed"] is True


def test_emergency_fund_validation(session):
    ok = {"monthly_expenses_paise": 3000000, "balance_paise": 5000000, "target_months": 6}
    assert st.put(session, "emergency_fund", ok) == ok
    for bad in ({**ok, "target_months": 7}, {**ok, "target_months": 2}, {**ok, "balance_paise": -1},
                {**ok, "monthly_expenses_paise": 0}, {**ok, "balance_paise": 1.5}):
        with pytest.raises(st.SettingsError):
            st.put(session, "emergency_fund", bad)


def test_drift_tolerance_default(session):
    assert st.tolerance_pp(session) == D(5)
