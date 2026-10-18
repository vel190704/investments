"""Every timezone-aware datetime is stored and compared as UTC (SQLite drops zones without converting)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import ChangeLogEntry, NewsItem
from app.timeutil import IST


def test_ist_aware_values_are_converted_on_write_and_in_queries(session):
    ist = datetime(2026, 10, 17, 13, 6, 20, tzinfo=IST)  # an NSE filing time (IST)
    session.add(NewsItem(isin="INE018A01030", company="L&T", title="t", source="NSE announcements",
                         source_kind="EXCHANGE", url="https://x/1", published_at=ist, category="other",
                         category_origin="RULE", dedupe_key="k1"))
    session.flush()
    session.expire_all()
    n = session.scalar(select(NewsItem))
    assert n.published_at.replace(tzinfo=n.published_at.tzinfo or UTC) == ist  # same instant, not 5.5 h later
    # comparing with an IST bound value finds it; one minute later does not
    assert session.scalar(select(NewsItem).where(NewsItem.published_at >= ist)) is not None
    assert session.scalar(select(NewsItem).where(NewsItem.published_at >= ist + timedelta(minutes=1))) is None


def test_journal_since_boundary_in_ist(session):
    # 00:30 IST on 17 Oct is 19:00 UTC on 16 Oct: it belongs to "since 17 Oct (IST)"
    session.add(ChangeLogEntry(kind="X", summary="s", cause="ui", occurred_at=datetime(2026, 10, 16, 19, 0, tzinfo=UTC)))
    session.flush()
    start = datetime(2026, 10, 17, 0, 0, tzinfo=IST)
    assert session.scalar(select(ChangeLogEntry).where(ChangeLogEntry.occurred_at >= start)) is not None


def test_month_start_counts_calls_from_ist_midnight(session):
    from app.models import LlmCall
    from app.services.analysis import usage

    session.add(LlmCall(purpose="stock", model="m", ok=True, input_tokens=1, output_tokens=1,
                        created_at=datetime(2026, 9, 30, 20, 0, tzinfo=UTC)))  # 01:30 IST on 1 Oct
    session.flush()
    import app.services.analysis as an
    orig = an.utcnow
    an.utcnow = lambda: datetime(2026, 10, 5, tzinfo=UTC)
    try:
        assert usage(session)["calls_this_month"] == 1
    finally:
        an.utcnow = orig
