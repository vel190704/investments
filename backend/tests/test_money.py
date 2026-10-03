from decimal import Decimal

import pytest

from app.money import format_inr, format_pct, rupees_to_paise, to_decimal, value_paise


@pytest.mark.parametrize("paise,expected", [
    (0, "₹0.00"), (5, "₹0.05"), (100, "₹1.00"), (12345600, "₹1,23,456.00"), (99999, "₹999.99"),
    (100000, "₹1,000.00"), (10000000, "₹1,00,000.00"), (1234567890, "₹1,23,45,678.90"),
    (-24230, "-₹242.30"), (123456789012345, "₹12,34,56,78,90,123.45"),
])
def test_format_inr_indian_grouping(paise, expected):
    assert format_inr(paise) == expected


def test_format_inr_variants():
    assert format_inr(12345650, symbol=False) == "1,23,456.50"
    assert format_inr(12345650, decimals=False) == "₹1,23,457"


def test_float_inputs_have_no_binary_artefacts():
    assert to_decimal(1193.8) == Decimal("1193.8")
    assert rupees_to_paise(1193.8) == 119380
    assert rupees_to_paise(0.1 + 0.2) == 30
    assert rupees_to_paise("1,23,456.789") == 12345679  # half-up


def test_value_paise_rounds_half_up():
    assert value_paise(Decimal("10.945"), Decimal("219.441")) == 240178  # 2401.78 (2401.7817…)
    assert value_paise(Decimal("1"), Decimal("0.005")) == 1


def test_format_pct():
    assert format_pct(Decimal("0.37995")) == "38.0%"
    assert format_pct(None) == "N/A"
