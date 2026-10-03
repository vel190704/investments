from decimal import Decimal as D

import pytest

from app.calc.projection import closed_form_no_step_up, monthly_rate, project, sentence


def test_monthly_rate_is_effective_annual():
    r = monthly_rate(D(12))
    assert (1 + r) ** 12 == pytest.approx(D("1.12"), abs=D("1e-20"))


def test_lump_sum_compounds_annually_to_exact_rate():
    p = project(10_000_000, 0, D(10), 2)  # ₹1,00,000 at 10% for 2 years -> ₹1,21,000
    assert p["ending_value_paise"] == 12_100_000 and p["total_contributions_paise"] == 0
    assert p["growth_paise"] == 2_100_000


def test_zero_rate_is_sum_of_contributions():
    p = project(100_000, 1_000_000, D(0), 5)
    assert p["ending_value_paise"] == 100_000 + 1_000_000 * 60 and p["growth_paise"] == 0


@pytest.mark.parametrize("rate,years", [(D(6), 5), (D(9), 10), (D(12), 10), (D("-3"), 3)])
def test_loop_matches_closed_form_without_step_up(rate, years):
    p = project(1_816_425, 1_000_000, rate, years)
    assert abs(p["ending_value_paise"] - closed_form_no_step_up(1_816_425, 1_000_000, rate, years)) <= 1


def test_step_up_contributions_and_value():
    p = project(0, 1_000_000, D(0), 3, D(10))  # ₹10,000/m, +10% per year, no growth
    # 12×10,000 + 12×11,000 + 12×12,100 = 3,97,200
    assert p["total_contributions_paise"] == 39_720_000 == p["ending_value_paise"]
    assert [y["contributions_paise"] for y in p["yearly"]] == [12_000_000, 25_200_000, 39_720_000]


def test_step_up_with_growth_hand_computed():
    # 2 years, ₹100/m, step-up 100% (to ₹200/m in year 2), 12% effective annual
    p = project(0, 10_000, D(12), 2, D(100))
    r = monthly_rate(D(12))
    expected = sum(D(10_000) * (1 + r) ** (24 - k) for k in range(1, 13)) + \
        sum(D(20_000) * (1 + r) ** (24 - k) for k in range(13, 25))
    assert abs(p["ending_value_paise"] - int(expected.to_integral_value())) <= 1


def test_identity_end_equals_start_plus_contributions_plus_growth():
    p = project(1_816_425, 1_000_000, D(9), 10, D(5))
    assert p["ending_value_paise"] == p["start_paise"] + p["total_contributions_paise"] + p["growth_paise"]
    assert len(p["yearly"]) == 10


def test_wording_is_a_conditional_scenario():
    s = sentence(project(0, 1_000_000, D(9), 10))
    assert s.startswith("If the portfolio averaged 9% annually and contributions were ₹10,000 a month")
    assert "mathematical future value would be approximately ₹" in s
    assert "you will" not in s.lower()


def test_invalid_inputs():
    with pytest.raises(ValueError):
        project(0, 0, D(5), 0)
    with pytest.raises(ValueError):
        project(-1, 0, D(5), 5)
