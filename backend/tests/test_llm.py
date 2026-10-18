import json
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.importer.run import import_workbook
from app.llm.inputs import build_input, input_hash
from app.llm.prompts import PROMPT_VERSION, render_scenario
from app.llm.provider import Completion, LLMUnavailable
from app.llm.validate import validate
from app.models import Instrument, LlmAnalysis, LlmCall, NewsItem, ThesisEntry, ThesisOptIn
from app.services import analysis as an
from app.services import settings as st
from tests.test_api import PRICES  # reuse realistic prices

TODAY = date(2026, 10, 17)
INPUT = {
    "holding": {"id": "h:company", "company": "Larsen & Toubro", "sector": {"id": "h:sector", "value": "Construction"}},
    "portfolio": {"weight": {"id": "p:weight", "value": "20.3%"}},
    "fundamentals": [{"id": "f:pe", "metric": "P/E", "value": "30.68", "as_of": "2026-10-03"},
                     {"id": "f:roe", "metric": "ROE", "value": "N/A (not provided by source)"}],
    "news": [{"id": "n:7", "title": "L&T bags Rs 2,000 crore order", "date": "2026-10-16"}],
}


def good(**over):
    out = {
        "valuation_context": [{"text": "The trailing P/E is 30.68; no portfolio median is available.", "citations": ["f:pe"]}],
        "business_quality": [{"text": "A recent order announcement points to an active order book.", "citations": ["n:7"]}],
        "key_risks": [{"text": "Construction is cyclical and sensitive to project delays.", "citations": ["h:sector"]}],
        "macro_sensitivity": [{"text": "Funding costs matter for project-heavy businesses.", "citations": ["h:sector"]}],
        "scenarios": [{"scenario": "rate_cut", "direction": "upward pressure",
                       "because": "lower borrowing costs tend to support project activity", "citations": ["h:sector"]}],
        "what_would_change_this_view": [{"text": "Evidence of a slowing order inflow.", "citations": ["n:7"]}],
        "data_gaps": [{"text": "ROE is not available from the source.", "citations": ["f:roe"]}],
    }
    out.update(over)
    return json.dumps(out)


def test_validator_accepts_grounded_output():
    data, errors = validate(good(), INPUT)
    assert errors == [] and data is not None
    assert render_scenario(data["scenarios"][0]) == ("If a rate cut happens, the likely direction of pressure on this "
                                                     "holding is upward pressure, because lower borrowing costs tend to "
                                                     "support project activity.")


def test_validator_rejects_invented_numbers():
    bad = good(valuation_context=[{"text": "The P/E of 30.68 is below 35, implying 15% upside room.", "citations": ["f:pe"]}])
    data, errors = validate(bad, INPUT)
    assert data is None and any("(a)" in e and "35" in e and "15" in e for e in errors)
    ok = good(business_quality=[{"text": "The Rs 2,000 crore order was reported.", "citations": ["n:7"]}])
    assert validate(ok, INPUT)[1] == []  # copied from input (comma-normalised)


@pytest.mark.parametrize("text,label", [
    ("Investors may want to buy on dips.", "buy"),
    ("This is a hold.", "hold"),
    ("A good time to accumulate.", "accumulate"),
    ("Our target price reflects this.", "target price"),
    ("The stock will rise after results.", "will rise/fall"),
    ("Shares are likely to fall on this.", "price prediction"),
    ("Consider exit the position.", "exit position"),
    ("Returns are guaranteed.", "guarantee"),
])
def test_validator_rejects_banned_wording(text, label):
    data, errors = validate(good(key_risks=[{"text": text, "citations": ["h:sector"]}]), INPUT)
    assert data is None and any(f"banned wording: {label}" in e for e in errors)


def test_validator_does_not_flag_ordinary_words():
    text = "The company sells to government buyers; this holding's shareholders include institutions."
    assert validate(good(key_risks=[{"text": text, "citations": ["h:sector"]}]), INPUT)[1] == []


def test_validator_requires_known_citations():
    _, errors = validate(good(key_risks=[{"text": "Unsupported claim.", "citations": []}]), INPUT)
    assert any("(c)" in e and "no citation" in e for e in errors)
    _, errors = validate(good(key_risks=[{"text": "Claim.", "citations": ["n:999"]}]), INPUT)
    assert any("(c)" in e and "n:999" in e for e in errors)


def test_validator_rejects_bad_schema():
    assert any("(d)" in e for e in validate("not json", INPUT)[1])
    d = json.loads(good())
    d["recommendation"] = "x"
    assert any("unexpected keys" in e for e in validate(json.dumps(d), INPUT)[1])
    bad = good(scenarios=[{"scenario": "election", "direction": "upward pressure", "because": "x", "citations": ["h:sector"]}])
    assert any("not allowed" in e for e in validate(bad, INPUT)[1])
    del d["recommendation"], d["data_gaps"]
    assert any("missing keys" in e for e in validate(json.dumps(d), INPUT)[1])


# ---------- integration with the DB ----------
def setup_book(session, workbook):
    from app.market.base import Quote
    from app.market.service import store_quote

    import_workbook(session, workbook)
    for i in session.scalars(select(Instrument)):
        if i.symbol:
            store_quote(session, i.id, Quote(__import__("decimal").Decimal(PRICES[i.symbol]), date(2026, 10, 16), "t", i.symbol))
    lt = session.scalar(select(Instrument).where(Instrument.symbol == "LT"))
    lt.isin = "INE018A01030"
    session.flush()
    return lt


class FakeProvider:
    name = "fake"

    def __init__(self, outputs, model="claude-opus-5-5"):
        self.outputs, self.model, self.calls = list(outputs), model, []

    def complete_json(self, system, messages, schema, max_tokens=16000):
        self.calls.append(messages)
        return Completion(self.outputs.pop(0), self.model, 1000, 300)


def enable(session, monkeypatch, cap=30):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-test")
    st.put(session, "llm", {**st.get(session, "llm"), "outbound_enabled": True, "monthly_call_cap": cap,
                            "model": "claude-opus-5-5"})
    st.put(session, "llm_platform", {"global_monthly_cap": 200, "price_in_per_mtok": "4", "price_out_per_mtok": "20"})


def good_for(inp):
    return good(valuation_context=[{"text": "Valuation data is listed in the input.", "citations": ["f:pe"]}],
                business_quality=[{"text": "No recent company news is in the input.", "citations": ["h:company"]}],
                what_would_change_this_view=[{"text": "New filings.", "citations": ["h:company"]}],
                data_gaps=[{"text": "ROE is not available.", "citations": ["f:roe"]}])


def test_input_has_no_amounts_or_identifiers(session, workbook):
    lt = setup_book(session, workbook)
    t = session.add(ThesisEntry(instrument_id=lt.id, version=1, why="Infra capex cycle", change_view="Order slowdown",
                                horizon="5 years"))
    session.flush()
    inp = build_input(session, lt.id, TODAY)
    blob = json.dumps(inp, ensure_ascii=False)
    assert "₹" not in blob and "paise" not in blob and "quantity" not in blob.lower()
    for word in ("invested", "Groww", "Zerodha", "RELIANCE", "SBIN", "HDFC Bank", "3693", "369340", "1865702"):
        assert word not in blob, word
    assert inp["portfolio"]["weight"]["value"].endswith("%")
    assert "my_thesis" not in inp  # not opted in
    session.add(ThesisOptIn(instrument_id=lt.id, send_to_llm=True))
    session.flush()
    assert build_input(session, lt.id, TODAY)["my_thesis"]["why_i_hold_it"] == "Infra capex cycle"
    from app.llm.validate import collect_ids
    assert {"h:company", "h:sector", "p:weight", "f:pe", "m:usd_inr", "s:tags"} <= collect_ids(inp)


def test_privacy_toggle_blocks_all_calls(session, workbook, monkeypatch):
    lt = setup_book(session, workbook)
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-test")
    fake = FakeProvider([good()])
    with pytest.raises(LLMUnavailable, match="Privacy toggle is off"):
        an.analyze(session, lt.id, provider=fake)
    session.add(NewsItem(isin="INE018A01030", company="LT", title="Markets update", source="x", source_kind="NEWS",
                         url="https://x/1", published_at=datetime(2026, 10, 16, tzinfo=UTC), category="other",
                         category_origin="RULE", dedupe_key="k"))
    session.flush()
    with pytest.raises(LLMUnavailable):
        an.suggest_categories(session, provider=fake)
    assert fake.calls == [] and session.scalars(select(LlmCall)).all() == []


def test_no_key_disables_feature(session, workbook):
    lt = setup_book(session, workbook)
    st.put(session, "llm", {**st.get(session, "llm"), "outbound_enabled": True})
    assert "No AI key configured on the server" in an.gate(session)
    assert an.cards(session)["gate"].startswith("No AI key configured")  # page still works


def test_cache_by_input_hash(session, workbook, monkeypatch):
    lt = setup_book(session, workbook)
    enable(session, monkeypatch)
    inp = build_input(session, lt.id, TODAY)
    fake = FakeProvider([good_for(inp), good_for(inp), good_for(inp)])
    r1 = an.analyze(session, lt.id, provider=fake, today=TODAY)
    assert not r1["cached"] and r1["card"]["status"] == "OK" and len(fake.calls) == 1
    r2 = an.analyze(session, lt.id, provider=fake, today=TODAY)
    assert r2["cached"] and len(fake.calls) == 1  # same inputs: no call
    an.analyze(session, lt.id, refresh=True, provider=fake, today=TODAY)
    assert len(fake.calls) == 2  # Refresh forces a call
    session.add(NewsItem(isin="INE018A01030", company="LT", title="L&T board meeting on results", source="x",
                         source_kind="EXCHANGE", url="https://x/2", published_at=datetime(2026, 10, 16, tzinfo=UTC),
                         category="board meeting", category_origin="RULE", dedupe_key="k2"))
    session.flush()
    r4 = an.analyze(session, lt.id, provider=fake, today=TODAY)
    assert not r4["cached"] and len(fake.calls) == 3  # inputs changed
    assert r4["card"]["data_as_of"] and r4["card"]["model"] == "claude-opus-5-5"
    assert input_hash(inp, "claude-opus-5-5", PROMPT_VERSION) != input_hash(inp, "claude-sonnet-5-5", PROMPT_VERSION)


def test_invalid_output_retried_then_flagged_not_shown(session, workbook, monkeypatch):
    lt = setup_book(session, workbook)
    enable(session, monkeypatch)
    bad = good(key_risks=[{"text": "The stock will rise 25%.", "citations": ["h:sector"]}])
    fake = FakeProvider([bad, bad])
    r = an.analyze(session, lt.id, provider=fake, today=TODAY)
    c = r["card"]
    assert c["status"] == "FAILED" and "analysis" not in c and c["attempts"] == 2
    assert any("banned wording" in e for e in c["errors"]) and any("(a)" in e for e in c["errors"])
    assert "failed validation" in fake.calls[1][-1]["content"]  # retry carried the reasons
    inp = build_input(session, lt.id, TODAY)
    fake2 = FakeProvider([bad, good_for(inp)])
    r2 = an.analyze(session, lt.id, refresh=True, provider=fake2, today=TODAY)
    assert r2["card"]["status"] == "OK" and r2["card"]["attempts"] == 2


def test_monthly_cap_blocks_calls(session, workbook, monkeypatch):
    lt = setup_book(session, workbook)
    enable(session, monkeypatch, cap=1)
    inp = build_input(session, lt.id, TODAY)
    fake = FakeProvider([good_for(inp), good_for(inp)])
    an.analyze(session, lt.id, provider=fake, today=TODAY)
    with pytest.raises(LLMUnavailable, match="Monthly call cap"):
        an.analyze(session, lt.id, refresh=True, provider=fake, today=TODAY)
    u = an.usage(session)
    assert u["calls_this_month"] == 1 and u["estimated_cost_usd"] == "0.0100"  # 1000×$4/M + 300×$20/M


def test_category_suggestions_only_for_other_and_only_headlines(session, workbook, monkeypatch):
    setup_book(session, workbook)
    enable(session, monkeypatch)
    for i, (title, cat) in enumerate([("L&T inks pact with state utility", "other"), ("Q2 results", "results")]):
        session.add(NewsItem(isin="INE018A01030", company="LT", title=title, source="x", source_kind="NEWS",
                             url=f"https://x/{i}", published_at=datetime(2026, 10, 16, tzinfo=UTC), category=cat,
                             category_origin="RULE", dedupe_key=str(i)))
    session.flush()
    other = session.scalar(select(NewsItem).where(NewsItem.category == "other"))
    fake = FakeProvider([json.dumps({"suggestions": [{"id": str(other.id), "category": "order win / contract"}]})])
    assert an.suggest_categories(session, provider=fake)["suggested"] == 1
    sent = json.loads(fake.calls[0][0]["content"])
    assert [h["headline"] for h in sent["headlines"]] == ["L&T inks pact with state utility"]  # rule-categorised item not sent
    assert other.category == "order win / contract" and other.category_origin == "MODEL"



def test_prices_not_hardcoded_and_model_from_env(session, monkeypatch):
    from app.config import get_settings

    u = an.usage(session)
    assert u["estimated_cost_usd"] is None and "Token prices are not set" in u["pricing_note"]
    assert "Verify against the provider's pricing page" in u["pricing_note"]
    monkeypatch.setattr(get_settings(), "claude_model", "claude-sonnet-5")
    assert st.llm_model(session) == "claude-sonnet-5"
    st.put(session, "llm", {**st.get(session, "llm"), "model": "claude-opus-5-5"})
    assert st.llm_model(session) == "claude-opus-5-5"
    import pytest as _p
    with _p.raises(st.SettingsError):
        st.put(session, "llm", {**st.get(session, "llm"), "model": "Claude Opus!"})
    assert st.get(session, "llm")["refusal_fallback"] is False


def test_card_shows_model_that_answered(session, workbook, monkeypatch):
    lt = setup_book(session, workbook)
    enable(session, monkeypatch)
    inp = build_input(session, lt.id, TODAY)
    fake = FakeProvider([good_for(inp)], model="claude-opus-5-5")
    fake.complete_json = (lambda orig: lambda *a, **k: Completion(orig(*a, **k).text, "claude-opus-4-8", 10, 5))(fake.complete_json)
    c = an.analyze(session, lt.id, provider=fake, today=TODAY)["card"]
    assert c["model"] == "claude-opus-4-8" and c["requested_model"] == "claude-opus-5-5" and c["fallback_used"]


def test_provider_fallback_param_only_when_enabled(monkeypatch):
    import types
    from app.llm import provider as pv

    calls = {}

    class Msgs:
        def __init__(self, tag):
            self.tag = tag

        def create(self, **kw):
            calls[self.tag] = kw
            return types.SimpleNamespace(stop_reason="end_turn", model=kw["model"],
                                         content=[types.SimpleNamespace(type="text", text="{}")],
                                         usage=types.SimpleNamespace(input_tokens=1, output_tokens=1))

    class Client:
        def __init__(self, **kw):
            self.messages = Msgs("plain")
            self.beta = types.SimpleNamespace(messages=Msgs("beta"))

    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", Client)
    pv.AnthropicProvider(api_key="k").complete_json("s", [], {})
    assert "plain" in calls and "fallbacks" not in calls["plain"]
    pv.AnthropicProvider(api_key="k", refusal_fallback=True).complete_json("s", [], {})
    assert calls["beta"]["fallbacks"] == "default" and calls["beta"]["betas"] == ["server-side-fallback-2026-07-01"]
