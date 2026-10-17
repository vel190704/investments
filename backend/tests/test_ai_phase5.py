import json
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.importer.run import import_workbook
from app.llm.inputs import build_fund_input, build_input, build_portfolio_input
from app.llm.validate import input_numbers, numbers_in, validate
from app.models import Instrument, ThesisEntry, ThesisOptIn
from app.services import analysis as an
from app.services import qualitative as ql
from app.services import valuation as val
from tests.disclosure_fixtures import icici
from tests.test_llm import FakeProvider, enable, setup_book
from tests.test_peers import LT, payload

TODAY = date(2026, 10, 17)


def book(session, workbook):
    lt = setup_book(session, workbook)
    from app.services.disclosures import upload
    for i in session.scalars(select(Instrument).where(Instrument.asset_type == "MF")):
        i.scheme_code = "1"
        from app.market.base import Quote
        from app.market.service import store_quote
        store_quote(session, i.id, Quote(D("100"), date(2026, 10, 16), "t", "1"))
    icici_id = session.scalar(select(Instrument).where(Instrument.name.like("ICICI%"))).id
    upload(session, icici(), "icici.xlsx", icici_id, "AMC_DISCLOSURE")
    val.set_peers(session, lt.id, ["AAA", "BBB", "CCC"], "large engineering peers")
    data = {"AAA": payload(20), "BBB": payload(30), "CCC": payload(40)}
    val.refresh(session, fetch=lambda s: data.get(s, LT), sleep=lambda x: None)
    session.flush()
    return lt, icici_id


def all_strings(o):
    if isinstance(o, dict):
        for k, v in o.items():
            if k != "id":
                yield from all_strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from all_strings(v)
    elif isinstance(o, str):
        yield o


def test_stock_input_has_framework_peers_history_with_ids(session, workbook):
    lt, _ = book(session, workbook)
    inp = build_input(session, lt.id, TODAY)
    ids = {c["id"] for c in inp["framework_check"]["checks"]}
    assert {"fc:pe_vs_peers", "fc:peg", "fc:roe", "fc:fcf_positive"} <= ids
    pe = next(m for m in inp["peer_comparison"]["metrics"] if m["metric"] == "pe")
    assert pe["peer_median"] == "30" and pe["peer_values"] == {"AAA": "20", "BBB": "30", "CCC": "40"}
    assert inp["peer_comparison"]["label"] == "peers chosen by the investor"
    assert inp["own_history"] and inp["own_history"][0]["id"].startswith("hist:")
    assert any(f["id"] == "f:peg" for f in inp["fundamentals"])
    assert "₹" not in json.dumps(inp, ensure_ascii=False)


def test_every_new_input_number_is_covered_by_the_validator(session, workbook):
    lt, icici_id = book(session, workbook)
    for inp in (build_input(session, lt.id, TODAY), build_fund_input(session, icici_id, TODAY),
                build_portfolio_input(session, TODAY)):
        allowed = input_numbers(inp)
        for text in all_strings(inp):
            assert numbers_in(text) <= allowed, text  # every number shown to the model may be quoted back
        assert "999.123" not in allowed  # and anything else is rejected


def test_qualitative_versioning_and_opt_in_only(session, workbook):
    lt, _ = book(session, workbook)
    v1 = ql.add(session, lt.id, "regulatory or licence", "Defence approvals", "Steady dividends", "AR FY26 p.40",
                date(2026, 6, 30))
    v2 = ql.add(session, lt.id, "cost advantage", "Scale in EPC", "Buybacks 2023", "AR FY26 p.41", date(2026, 6, 30))
    assert (v1["version"], v2["version"]) == (1, 2) and [h["version"] for h in ql.history(session, lt.id)] == [2, 1]
    assert ql.history(session, lt.id)[1]["moat_type"] == "regulatory or licence"  # v1 unchanged
    with pytest.raises(ql.QualitativeError, match="moat type"):
        ql.add(session, lt.id, "vibes", "x", "y", "z", date(2026, 6, 30))
    with pytest.raises(ql.QualitativeError, match="source note"):
        ql.add(session, lt.id, "brand", "x", "y", " ", date(2026, 6, 30))
    t = ThesisEntry(instrument_id=lt.id + 1, version=1, why="w", change_view="c", horizon="h")
    session.add(t)
    session.flush()
    with pytest.raises(ql.QualitativeError, match="does not belong"):
        ql.add(session, lt.id, "brand", "x", "y", "z", date(2026, 6, 30), thesis_entry_id=t.id)
    inp = build_input(session, lt.id, TODAY)
    assert "my_qualitative_notes" not in inp and "my_thesis" not in inp  # not opted in
    session.add(ThesisOptIn(instrument_id=lt.id, send_to_llm=True))
    session.flush()
    inp = build_input(session, lt.id, TODAY)
    assert inp["my_qualitative_notes"]["moat_type"] == "cost advantage" and inp["my_qualitative_notes"]["id"] == "q:latest"


def test_fund_input_index_focus_and_overlap(session, workbook):
    lt, icici_id = book(session, workbook)
    inp = build_fund_input(session, icici_id, TODAY)
    assert inp["fund"]["fund_type"] == "index" and inp["focus"][0] == "tracking difference"
    assert inp["holdings"]["as_of"] == "2026-09-30" and inp["holdings"]["top_holdings"][0]["company"] == "HDFC Bank Ltd."
    assert inp["holdings"]["overlap_with_my_direct_stocks"]["companies"] == ["Larsen & Toubro Ltd."]  # LT has ISIN
    assert inp["costs"]["expense_ratio"]["value"].startswith("N/A")
    assert inp["portfolio"]["share_of_my_portfolio"].endswith("%")
    kotak = session.scalar(select(Instrument).where(Instrument.name.like("Kotak%")))
    assert "no portfolio disclosure" in build_fund_input(session, kotak.id, TODAY)["holdings"]["status"]
    blob = json.dumps(inp, ensure_ascii=False)
    assert "₹" not in blob and "quantity" not in blob.lower()


FUND_GOOD = {"cost_and_tracking": [{"text": "Expense ratio is not entered.", "citations": ["ff:expense_ratio"]}],
             "concentration": [{"text": "The top holding is HDFC Bank Ltd.", "citations": ["th:INE040A01034"]}],
             "sector_tilts": [], "overlap": [{"text": "It overlaps with a directly held stock.", "citations": ["od:direct"]}],
             "key_risks": [], "what_would_change_this_view": [], "data_gaps": []}


@pytest.mark.parametrize("text,label", [
    ("This is a good fund for the core.", "good/bad judgement"),
    ("Consider switching to a cheaper index fund.", "switch"),
    ("Returns will likely improve.", "return prediction"),
    ("Expected returns are modest.", "return prediction"),
    ("A reasonable fund to hold.", "hold"),
])
def test_fund_card_banned_wording(text, label, session, workbook):
    lt, icici_id = book(session, workbook)
    inp = build_fund_input(session, icici_id, TODAY)
    assert validate(json.dumps(FUND_GOOD), inp, "fund")[1] == []
    bad = {**FUND_GOOD, "key_risks": [{"text": text, "citations": ["fund:name"]}]}
    data, errors = validate(json.dumps(bad), inp, "fund")
    assert data is None and any(label in e for e in errors)


def test_fund_and_portfolio_cards_run_cached_and_flag(session, workbook, monkeypatch):
    lt, icici_id = book(session, workbook)
    enable(session, monkeypatch)
    fake = FakeProvider([json.dumps(FUND_GOOD)])
    c = an.analyze_fund(session, icici_id, provider=fake, today=TODAY)["card"]
    assert c["status"] == "OK" and c["kind"] == "fund" and c["analysis"]["concentration"]
    assert an.analyze_fund(session, icici_id, provider=fake, today=TODAY)["cached"]
    pin = build_portfolio_input(session, TODAY)
    assert "₹" not in json.dumps(pin, ensure_ascii=False) and not any(h["id"] == "hd:emergency" for h in pin["health"])
    hid = pin["health"][0]["id"]
    good_p = {"summary": [{"text": "Company concentration is flagged.", "citations": [hid]}], "data_gaps": []}
    bad_p = {"summary": [{"text": "This portfolio is a great investment and returns will rise.", "citations": [hid]}],
             "data_gaps": []}
    fake2 = FakeProvider([json.dumps(bad_p), json.dumps(bad_p)])
    r = an.analyze_portfolio(session, provider=fake2, today=TODAY)["card"]
    assert r["status"] == "FAILED" and "analysis" not in r
    fake3 = FakeProvider([json.dumps(good_p)])
    r = an.analyze_portfolio(session, refresh=True, provider=fake3, today=TODAY)["card"]
    assert r["status"] == "OK" and r["kind"] == "portfolio" and r["analysis"]["summary"]
    cards = an.cards(session)
    assert cards["portfolio"]["card"]["status"] == "OK" and any(f["card"] for f in cards["funds"])
