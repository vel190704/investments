"""Data-access layer: every query used by services/importer lives here."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import (
    FallbackHolding, IdentifierCandidate, ImportRun, Instrument, IntradayTick, MonthlyPlanItem, PriceQuote,
    RefreshRun, Transaction,
)


# idempotent seeding
def insert_ignore(s: Session, model, rows: list[dict], conflict_cols: list[str]) -> int:
    """INSERT ... ON CONFLICT DO NOTHING (SQLite and Postgres). Safe when two requests seed at once.
    Returns the number of rows actually inserted."""
    if not rows:
        return 0
    name = s.get_bind().dialect.name
    if name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    elif name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:  # pragma: no cover - only SQLite/Postgres are supported
        raise NotImplementedError(f"insert_ignore: unsupported dialect {name}")
    res = s.execute(insert(model).values(rows).on_conflict_do_nothing(index_elements=conflict_cols))
    return res.rowcount or 0


# instruments
def instruments_by_key(s: Session) -> dict[str, Instrument]:
    return {i.instrument_key: i for i in s.scalars(select(Instrument))}


def all_instruments(s: Session) -> list[Instrument]:
    return list(s.scalars(select(Instrument).order_by(Instrument.asset_type, Instrument.name)))


def get_instrument(s: Session, iid: int) -> Instrument | None:
    return s.get(Instrument, iid)


# transactions
def all_transactions(s: Session) -> list[Transaction]:
    return list(s.scalars(select(Transaction).order_by(Transaction.date, Transaction.source_row, Transaction.id)))


def excel_row_keys(s: Session) -> dict[str, Transaction]:
    return {t.row_key: t for t in s.scalars(select(Transaction).where(Transaction.source == "excel"))}


def ui_transactions(s: Session) -> list[Transaction]:
    return list(s.scalars(select(Transaction).where(Transaction.source == "ui")))


def instrument_ids_with_transactions(s: Session) -> set[int]:
    return set(s.scalars(select(Transaction.instrument_id).distinct()))


# fallback / plan
def replace_fallback(s: Session, rows: list[FallbackHolding]) -> None:
    s.execute(delete(FallbackHolding))
    s.add_all(rows)


def used_fallbacks(s: Session) -> list[FallbackHolding]:
    return list(s.scalars(select(FallbackHolding).where(FallbackHolding.used.is_(True))))


def replace_plan(s: Session, rows: list[MonthlyPlanItem]) -> None:
    s.execute(delete(MonthlyPlanItem))
    s.add_all(rows)


def plan_items(s: Session) -> list[MonthlyPlanItem]:
    return list(s.scalars(select(MonthlyPlanItem).order_by(MonthlyPlanItem.source_row)))


# identifiers
def candidates(s: Session, instrument_id: int | None = None) -> list[IdentifierCandidate]:
    q = select(IdentifierCandidate).order_by(IdentifierCandidate.instrument_id, IdentifierCandidate.kind,
                                             IdentifierCandidate.score.desc())
    if instrument_id is not None:
        q = q.where(IdentifierCandidate.instrument_id == instrument_id)
    return list(s.scalars(q))


def get_candidate(s: Session, cid: int) -> IdentifierCandidate | None:
    return s.get(IdentifierCandidate, cid)


def find_candidate(s: Session, instrument_id: int, kind: str, value: str) -> IdentifierCandidate | None:
    return s.scalar(select(IdentifierCandidate).where(
        IdentifierCandidate.instrument_id == instrument_id, IdentifierCandidate.kind == kind,
        IdentifierCandidate.value == value))


# prices
def latest_quotes(s: Session) -> dict[int, PriceQuote]:
    """Newest quote per instrument (by market date, then fetch time)."""
    out: dict[int, PriceQuote] = {}
    for q in s.scalars(select(PriceQuote).order_by(PriceQuote.price_date, PriceQuote.fetched_at)):
        out[q.instrument_id] = q
    return out


def quote_on(s: Session, instrument_id: int, source: str, price_date) -> PriceQuote | None:
    return s.scalar(select(PriceQuote).where(PriceQuote.instrument_id == instrument_id,
                                             PriceQuote.source == source, PriceQuote.price_date == price_date))


def previous_quote(s: Session, instrument_id: int, source: str, before) -> PriceQuote | None:
    return s.scalar(select(PriceQuote).where(
        PriceQuote.instrument_id == instrument_id, PriceQuote.source == source, PriceQuote.price_date < before,
    ).order_by(PriceQuote.price_date.desc()).limit(1))


def newest_fetch_time(s: Session) -> datetime | None:
    return s.scalar(select(func.max(PriceQuote.fetched_at)))


# runs
def import_runs(s: Session, limit: int = 20) -> list[ImportRun]:
    return list(s.scalars(select(ImportRun).order_by(ImportRun.id.desc()).limit(limit)))


def refresh_runs(s: Session, limit: int = 5) -> list[RefreshRun]:
    return list(s.scalars(select(RefreshRun).order_by(RefreshRun.id.desc()).limit(limit)))


# intraday ticks (live prices; never used for snapshots, XIRR or history)
def _utc(dt: datetime) -> datetime:
    """SQLite stores datetimes without converting the zone, so every bound value must already be UTC."""
    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)


def add_ticks(s: Session, rows: list[dict]) -> int:
    """rows: {instrument_id, ts, price, source, fetched_at}; duplicates (same bar) are ignored."""
    rows = [{**r, "ts": _utc(r["ts"]), "fetched_at": _utc(r["fetched_at"])} for r in rows]
    return insert_ignore(s, IntradayTick, rows, ["instrument_id", "ts", "source"])


def ticks_since(s: Session, since: datetime, instrument_ids: list[int] | None = None) -> list[IntradayTick]:
    q = select(IntradayTick).where(IntradayTick.ts >= _utc(since))
    if instrument_ids is not None:
        q = q.where(IntradayTick.instrument_id.in_(instrument_ids))
    return list(s.scalars(q.order_by(IntradayTick.instrument_id, IntradayTick.ts)))


def latest_tick_per_instrument(s: Session) -> dict[int, IntradayTick]:
    newest = (select(IntradayTick.instrument_id, func.max(IntradayTick.ts).label("ts"))
              .group_by(IntradayTick.instrument_id).subquery())
    q = select(IntradayTick).join(newest, (IntradayTick.instrument_id == newest.c.instrument_id)
                                  & (IntradayTick.ts == newest.c.ts))
    return {t.instrument_id: t for t in s.scalars(q)}


def prune_ticks(s: Session, before: datetime) -> int:
    return s.execute(delete(IntradayTick).where(IntradayTick.ts < _utc(before))).rowcount or 0


def close_before(s: Session, instrument_id: int, day) -> PriceQuote | None:
    """The latest end-of-day quote dated before `day` (the previous session's close)."""
    return s.scalar(select(PriceQuote).where(PriceQuote.instrument_id == instrument_id, PriceQuote.price_date < day)
                    .order_by(PriceQuote.price_date.desc(), PriceQuote.fetched_at.desc()).limit(1))
