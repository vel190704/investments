import json
from decimal import Decimal as D
from pathlib import Path

import pytest
from sqlalchemy import select

from app.importer.run import import_workbook
from app.models import AnnualFinancial, Instrument, InstrumentFact, PeerMetric
from app.services import valuation as val

LT = json.loads((Path(__file__).parent / "fixtures" / "yf_LT_statements.json").read_text())


def payload(pe, growth=0.1, roe=0.15):
    return {"info": {"trailingPE": pe, "earningsGrowth": growth, "returnOnEquity": roe,
                     "priceToSalesTrailing12Months": 2.0, "marketCap": 1e12},
            "cashflow": {"Free Cash Flow": {"2025-03-31": 1e10, "2026-03-31": 2e10}},
            "income": {"Total Revenue": {"2025-03-31": 1e11, "2026-03-31": 1.2e11}}}


def lt(session):
    return session.scalar(select(Instrument).where(Instrument.symbol == "LT"))


def test_peer_list_rules(session, workbook):
    import_workbook(session, workbook)
    i = lt(session)
    row = val.set_peers(session, i.id, ["siemens", " ABB ", "SIEMENS", ""], "Capital goods majors")
    assert row.symbols == ["SIEMENS", "ABB"] and row.note == "Capital goods majors"
    with pytest.raises(val.PeerError, match="own peer"):
        val.set_peers(session, i.id, ["LT"], None)
    with pytest.raises(val.PeerError, match="At most 8"):
        val.set_peers(session, i.id, [f"P{n}" for n in range(9)], None)
    mf = session.scalar(select(Instrument).where(Instrument.asset_type == "MF"))
    with pytest.raises(val.PeerError, match="direct stocks"):
        val.set_peers(session, mf.id, ["X"], None)


def test_nothing_seeded_and_median_needs_three(session, workbook):
    import_workbook(session, workbook)
    i = lt(session)
    v0 = val.stock_view(session, i.id)
    assert v0["peers"]["symbols"] == [] and v0["peers"]["label"] == "peers chosen by me"
    val.set_peers(session, i.id, ["AAA", "BBB", "CCC"], "why")
    data = {"AAA": payload(20), "BBB": payload(30), "CCC": payload(None)}
    sleeps = []
    val.refresh(session, fetch=lambda s: data[s] if s in data else LT, sleep=sleeps.append)
    assert sleeps and all(x == 1.0 for x in sleeps)  # rate limited
    view = val.stock_view(session, i.id)
    pe = next(c for c in view["peers"]["comparisons"] if c["metric"] == "pe")
    assert pe["peer_median"] is None and "only 2 peer(s)" in pe["median_note"]  # CCC has no P/E
    assert [p["symbol"] for p in pe["peers"]] == ["AAA", "BBB", "CCC"] and pe["peers"][2]["status"] == "MISSING"
    ps = next(c for c in view["peers"]["comparisons"] if c["metric"] == "ps")
    assert D(ps["peer_median"]) == D("2")
    assert pe["mine"] == "30.08793"  # own value from the recorded LT payload
    # own computed metrics stored with derivation; annual lines stored
    peg = session.scalar(select(InstrumentFact).where(InstrumentFact.metric == "peg"))
    assert peg.status == "OK" and "PEG = P/E" in peg.note
    assert session.scalar(select(AnnualFinancial).where(AnnualFinancial.symbol == "LT", AnnualFinancial.metric == "fcf"))
    # peers are cached for a day: no new fetch
    calls = []
    val.refresh(session, fetch=lambda s: calls.append(s) or LT, sleep=lambda x: None, own=False)
    assert calls == []


def test_framework_in_view_without_score(session, workbook):
    import_workbook(session, workbook)
    i = lt(session)
    val.refresh(session, fetch=lambda s: LT, sleep=lambda x: None, peers=False)
    view = val.stock_view(session, i.id)
    keys = [c["key"] for c in view["framework"]]
    assert keys == ["pe_vs_peers", "pe_vs_history", "peg", "roe", "debt_to_equity", "interest_coverage",
                    "fcf_positive", "fcf_not_declining"]
    def keys_of(o):
        if isinstance(o, dict):
            return set(o) | set().union(*[keys_of(x) for x in o.values()]) if o else set()
        if isinstance(o, list):
            return set().union(*[keys_of(x) for x in o]) if o else set()
        return set()
    assert not {k for k in keys_of(view) if any(w in k.lower() for w in ("score", "verdict", "rank", "rating"))}
    fcf = {c["key"]: c for c in view["framework"]}
    assert fcf["fcf_positive"]["status"] == "MEETS" and fcf["fcf_not_declining"]["status"] == "MEETS"  # 1193.18 vs 473.25 crore
    assert fcf["pe_vs_peers"]["status"] == "N/A"


def test_fundamentals_table_shows_computed_reasons(session, workbook):
    from app.services import fundamentals as fs

    import_workbook(session, workbook)
    val.refresh(session, fetch=lambda s: payload(20, growth=-0.2), sleep=lambda x: None, peers=False)
    rows = {r["symbol"]: {c["metric"]: c for c in r["metrics"]} for r in fs.report(session)["stocks"]}
    assert "zero or negative" in rows["LT"]["peg"]["display_na"]
    assert D(rows["LT"]["ps"]["value"]) == D("2") and rows["LT"]["fcf_margin"]["value"]
    assert "not both reported" in rows["LT"]["interest_coverage"]["display_na"]
