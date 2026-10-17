from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.importer.run import import_workbook
from app.models import ChangeLogEntry, Instrument, ThesisEntry, Transaction
from app.services import journal as jn


def lt(session):
    return session.scalar(select(Instrument).where(Instrument.symbol == "LT"))


def test_versions_are_append_only(session, workbook):
    import_workbook(session, workbook)
    i = lt(session)
    v1 = jn.add_entry(session, i.id, "Infra capex", "Order slowdown", "5 years", date(2027, 1, 1))
    v2 = jn.add_entry(session, i.id, "Infra capex + defence", "Order slowdown", "5 years", date(2027, 4, 1))
    assert (v1["version"], v2["version"]) == (1, 2)
    hist = jn.history(session, i.id)
    assert [h["version"] for h in hist] == [2, 1] and hist[1]["why"] == "Infra capex"  # v1 untouched
    assert session.scalar(select(ThesisEntry).where(ThesisEntry.version == 1)).why == "Infra capex"
    assert not hasattr(jn, "update_entry") and not hasattr(jn, "delete_entry")
    kinds = [c.kind for c in session.scalars(select(ChangeLogEntry).where(ChangeLogEntry.kind == "THESIS_UPDATED"))]
    assert kinds == ["THESIS_UPDATED", "THESIS_UPDATED"]


def test_links_validated(session, workbook):
    import_workbook(session, workbook)
    i = lt(session)
    own = session.scalar(select(Transaction).where(Transaction.instrument_id == i.id))
    other = session.scalar(select(Transaction).where(Transaction.instrument_id != i.id))
    e = jn.add_entry(session, i.id, "w", "c", "h", None, [own.id])
    assert e["linked_txn_ids"] == [own.id]
    with pytest.raises(jn.JournalError, match="do not belong"):
        jn.add_entry(session, i.id, "w", "c", "h", None, [other.id])
    with pytest.raises(jn.JournalError, match="required"):
        jn.add_entry(session, i.id, " ", "c", "h", None)


def test_review_due_uses_latest_version(session, workbook):
    import_workbook(session, workbook)
    i = lt(session)
    today = date(2026, 10, 17)
    jn.add_entry(session, i.id, "w", "c", "h", today - timedelta(days=1))
    assert [d["name"] for d in jn.review_due(session, today)] == ["LT"]
    jn.add_entry(session, i.id, "w2", "c", "h", today + timedelta(days=90))  # reviewed: new version moves the date
    assert jn.review_due(session, today) == []


def test_strategy_is_factual(session, workbook):
    import_workbook(session, workbook)
    jn.add_entry(session, lt(session).id, "w", "c", "h", None)
    out = jn.strategy(session, date(2026, 10, 1))
    assert out["actual"]["compare"] is None and "No snapshot" in out["note"]
    assert len(out["actual"]["transactions"]) == 19 and out["stated"]["theses"][0]["why"] == "w"
    assert out["stated"]["drift"]["targets_set"] is False
