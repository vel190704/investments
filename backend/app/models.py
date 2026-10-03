"""ORM models. Single user: no user tables, no user_id columns.

Money: integer paise (*_paise). Quantities, prices, fractions: DecimalText (exact).
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.types import DecimalText
from app.timeutil import utcnow


class Instrument(Base):
    __tablename__ = "instruments"

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_key: Mapped[str] = mapped_column(String(200), unique=True)
    asset_type: Mapped[str] = mapped_column(String(10))  # STOCK | ETF | MF
    name: Mapped[str] = mapped_column(String(300))
    symbol: Mapped[str | None] = mapped_column(String(50))
    isin: Mapped[str | None] = mapped_column(String(20))
    scheme_code: Mapped[str | None] = mapped_column(String(20))
    exposure: Mapped[str] = mapped_column(String(20), default="DOMESTIC")  # DOMESTIC | INTERNATIONAL
    category: Mapped[str | None] = mapped_column(String(100))
    platform: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="instrument")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    date: Mapped[date] = mapped_column(Date)
    type: Mapped[str] = mapped_column(String(10))  # BUY|SELL|SIP|DIVIDEND|OPENING
    quantity: Mapped[Decimal | None] = mapped_column(DecimalText)
    price: Mapped[Decimal | None] = mapped_column(DecimalText)
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    charges_paise: Mapped[int] = mapped_column(BigInteger, default=0)
    platform: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="excel")
    row_key: Mapped[str] = mapped_column(String(100), unique=True)
    source_file: Mapped[str | None] = mapped_column(String(300))
    source_row: Mapped[int | None] = mapped_column(Integer)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    instrument: Mapped[Instrument] = relationship(back_populates="transactions")


class FallbackHolding(Base):
    __tablename__ = "fallback_holdings"

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    as_of_date: Mapped[date] = mapped_column(Date)
    platform: Mapped[str | None] = mapped_column(String(50))
    quantity: Mapped[Decimal] = mapped_column(DecimalText)
    invested_paise: Mapped[int] = mapped_column(BigInteger)
    monthly_plan_paise: Mapped[int | None] = mapped_column(BigInteger)
    sector: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    source_row: Mapped[int | None] = mapped_column(Integer)


class MonthlyPlanItem(Base):
    __tablename__ = "monthly_plan_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str | None] = mapped_column(String(50))
    asset_type: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(300))
    monthly_amount_paise: Mapped[int] = mapped_column(BigInteger)
    allocation_fraction: Mapped[Decimal] = mapped_column(DecimalText)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"))
    is_bucket: Mapped[bool] = mapped_column(Boolean, default=False)
    source_row: Mapped[int | None] = mapped_column(Integer)


class IdentifierCandidate(Base):
    __tablename__ = "identifier_candidates"
    __table_args__ = (UniqueConstraint("instrument_id", "kind", "value"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # ISIN | SCHEME_CODE
    value: Mapped[str] = mapped_column(String(50))
    label: Mapped[str] = mapped_column(String(400))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(100))
    score: Mapped[float] = mapped_column(Float, default=0.0)  # match score, not money
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING|CONFIRMED|REJECTED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PriceQuote(Base):
    __tablename__ = "price_quotes"
    __table_args__ = (UniqueConstraint("instrument_id", "source", "price_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    source: Mapped[str] = mapped_column(String(50))
    source_ref: Mapped[str | None] = mapped_column(String(100))
    price: Mapped[Decimal] = mapped_column(DecimalText)
    previous_close: Mapped[Decimal | None] = mapped_column(DecimalText)
    previous_date: Mapped[date | None] = mapped_column(Date)
    price_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ImportRun(Base):
    __tablename__ = "import_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    file_name: Mapped[str] = mapped_column(String(300))
    file_sha256: Mapped[str] = mapped_column(String(64))
    ok: Mapped[bool] = mapped_column(Boolean)
    rows_loaded: Mapped[int] = mapped_column(Integer, default=0)
    rows_skipped: Mapped[int] = mapped_column(Integer, default=0)
    rows_errors: Mapped[int] = mapped_column(Integer, default=0)
    report: Mapped[dict] = mapped_column(JSON, default=dict)


class RefreshRun(Base):
    __tablename__ = "refresh_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    trigger: Mapped[str] = mapped_column(String(20))  # manual | scheduled | startup
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ok_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    results: Mapped[list] = mapped_column(JSON, default=list)
