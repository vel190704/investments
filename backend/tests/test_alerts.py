from datetime import UTC, date, datetime

from sqlalchemy import select

from app.calc.alerts import evaluate
from app.importer.run import import_workbook
from app.models import Alert, Instrument, NewsItem
from app.services import alerts as al
from app.services import journal as jn
from app.services import settings as st

RULES = {"announcement": True, "announcement_categories": ["results", "dividend"], "concentration_change": True,
         "disclosure_stale": True, "review_due": True}
NEWS = [{"id": 1, "instrument_id": 5, "company": "LT", "title": "Q2 results", "category": "results", "source": "NSE"},
        {"id": 2, "instrument_id": 5, "company": "LT", "title": "Misc", "category": "other", "source": "NSE"},
        {"id": 3, "instrument_id": None, "company": "Infosys", "title": "Q2 results", "category": "results", "source": "ET"}]


def test_announcement_rule_filters_category_and_owned():
    out, _ = evaluate(RULES, NEWS, {}, [], [], None, "2026-10-17")
    assert [a["key"] for a in out] == ["news:1"]  # 'other' skipped; company not directly owned skipped
    out, _ = evaluate({**RULES, "announcement": False}, NEWS, {}, [], [], None, "2026-10-17")
    assert out == []


def test_level_change_needs_a_baseline():
    out, state = evaluate(RULES, [], {"company": "HIGH", "sector": "MODERATE"}, [], [], None, "2026-10-17")
    assert out == [] and state == {"levels": {"company": "HIGH", "sector": "MODERATE"}}
    out, state = evaluate(RULES, [], {"company": "MODERATE", "sector": "MODERATE"}, [], [], state, "2026-10-18")
    assert [a["title"] for a in out] == ["Company concentration: HIGH → MODERATE"]
    assert state["levels"]["company"] == "MODERATE"
    out, _ = evaluate({**RULES, "concentration_change": False}, [], {"company": "LOW"}, [], [], state, "2026-10-19")
    assert out == []


def test_stale_and_review_rules():
    out, _ = evaluate(RULES, [], {}, [{"id": 9, "fund": "HDFC Mid Cap", "as_of": "2026-06-30", "instrument_id": 3}],
                      [{"id": 4, "instrument_id": 5, "name": "LT", "version": 2, "review_date": "2026-10-01"}], None,
                      "2026-10-17")
    assert {a["key"] for a in out} == {"stale:9", "review:4"}


def test_service_creates_each_alert_once(session, workbook):
    import_workbook(session, workbook)
    lt = session.scalar(select(Instrument).where(Instrument.symbol == "LT"))
    session.add(NewsItem(isin="INE018A01030", instrument_id=lt.id, company="Larsen & Toubro", title="Q2 results",
                         source="NSE", source_kind="EXCHANGE", url="https://x/r", published_at=datetime.now(UTC),
                         category="results", category_origin="RULE", dedupe_key="k"))
    jn.add_entry(session, lt.id, "w", "c", "h", date(2026, 1, 1))
    assert al.evaluate_alerts(session)["created"] == 2
    assert al.evaluate_alerts(session)["created"] == 0
    listed = al.list_alerts(session)
    assert listed["unread"] == 2
    al.mark_read(session, listed["alerts"][0]["id"])
    assert al.list_alerts(session)["unread"] == 1
    st.put(session, "alerts", {**RULES, "review_due": False, "announcement": False})
    session.query(Alert).delete()
    assert al.evaluate_alerts(session)["created"] == 0
