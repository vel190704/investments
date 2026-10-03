from datetime import date
from decimal import Decimal as D

import pytest

from app.disclosures.engine import DisclosureFormatError, parse_date_text, parse_disclosure
from tests import disclosure_fixtures as fx


def test_hdfc_layout_picks_scheme_sheet_and_stops_at_grand_total():
    p = parse_disclosure(fx.hdfc(), "hdfc.xlsx", "HDFC Mid Cap Fund - Direct - Growth")
    assert p.parser == "HDFC" and p.sheet == "MIDCAP" and p.as_of == date(2026, 9, 30)
    by = {r.name: r for r in p.rows}
    assert set(by) == {"Larsen and Toubro Ltd.", "Reliance Industries Ltd.", "Treasury Bill 91 Days",
                       "TREPS - Tri-party Repo"}  # headings, Sub Total and anything after Grand Total skipped
    assert by["Larsen and Toubro Ltd."].weight == D("0.065") and by["Larsen and Toubro Ltd."].is_equity
    assert not by["Treasury Bill 91 Days"].is_equity and by["TREPS - Tri-party Repo"].isin is None
    assert p.equity_weight == D("0.0975") and p.total_weight == D("1.0")
    assert p.warnings == []


def test_icici_layout_fraction_weights():
    p = parse_disclosure(fx.icici(), "icici.xlsx", "ICICI Prudential Nifty 50 Index Fund - Direct - Growth")
    assert p.parser == "ICICI" and p.as_of == date(2026, 9, 30)
    assert [r.weight for r in p.rows if r.is_equity] == [D("0.1250"), D("0.0900"), D("0.0400")]
    assert p.rows[-1].name == "Net Current Assets"


def test_kotak_layout_percent_strings():
    p = parse_disclosure(fx.kotak(), "kotak.xlsx", "Kotak Nifty Next 50 Index Fund - Direct - Growth")
    assert p.parser == "KOTAK" and p.as_of == date(2026, 9, 30)
    assert {r.name: r.weight for r in p.rows if r.is_equity} == {"Bharat Electronics Ltd.": D("0.041"),
                                                                  "Tata Power Co Ltd.": D("0.03")}


def test_generic_index_weights_csv_needs_entered_date():
    with pytest.raises(DisclosureFormatError, match="as-of date"):
        parse_disclosure(fx.index_weights_csv(), "n50.csv", "Nifty 50", generic=True)
    p = parse_disclosure(fx.index_weights_csv(), "n50.csv", "Nifty 50", generic=True, as_of=date(2026, 9, 30))
    assert p.parser == "GENERIC_CSV" and len(p.rows) == 4 and p.total_weight == D("1.0")


def test_unknown_layout_fails_visibly():
    with pytest.raises(DisclosureFormatError, match="Unrecognised layout: could not identify the AMC"):
        parse_disclosure(fx.unknown_layout(), "x.xlsx", "Some fund")
    with pytest.raises(DisclosureFormatError, match="no header row"):
        parse_disclosure(fx.unknown_layout(), "x.xlsx", "Some fund", amc="HDFC")
    with pytest.raises(DisclosureFormatError, match="Unsupported file type"):
        parse_disclosure(b"%PDF", "x.pdf", "Some fund")


def test_wrong_fund_for_multi_scheme_file():
    with pytest.raises(DisclosureFormatError, match="No sheet mentions"):
        parse_disclosure(fx.hdfc(), "hdfc.xlsx", "Kotak Small Cap Fund")


def test_weights_not_near_100_percent_warns():
    p = parse_disclosure(fx.hdfc(), "hdfc.xlsx", "HDFC Flexi Cap Fund")
    assert any("add up to 9.00%" in w for w in p.warnings)


@pytest.mark.parametrize("text,expected", [
    ("September 30, 2026", date(2026, 9, 30)), ("Sep 30,2026", date(2026, 9, 30)), ("30-Sep-2026", date(2026, 9, 30)),
    ("30/09/2026", date(2026, 9, 30)), ("30th September 2026", date(2026, 9, 30)), ("2026-09-30 (unaudited)", date(2026, 9, 30)),
])
def test_date_formats(text, expected):
    assert parse_date_text(text) == expected
