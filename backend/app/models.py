"""ORM models. Single user: no user tables, no user_id columns.

Money: integer paise (*_paise). Quantities, prices, fractions: DecimalText (exact).
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
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
    # Phase 3 classification
    asset_class_override: Mapped[str | None] = mapped_column(String(50))
    etf_underlying: Mapped[str | None] = mapped_column(String(50))  # NSE: EQUITY|COMMODITY|DEBT|GLOBAL INDICES
    etf_underlying_key: Mapped[str | None] = mapped_column(String(100))  # NSE: GOLD, SILVER, Nifty 50, ...
    region: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="instrument")


TXN_SOURCES = ("excel", "ui")


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (CheckConstraint("source IN ('excel', 'ui')", name="ck_transactions_source"),)

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


class PortfolioSnapshot(Base):
    """One row per IST calendar date (upserted)."""

    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, unique=True)
    total_value_paise: Mapped[int] = mapped_column(BigInteger)  # priced holdings only
    total_invested_paise: Mapped[int] = mapped_column(BigInteger)  # all open holdings
    invested_priced_paise: Mapped[int] = mapped_column(BigInteger)
    unpriced: Mapped[list] = mapped_column(JSON, default=list)  # names of holdings without a price
    trigger: Mapped[str] = mapped_column(String(20))  # refresh | scheduled | startup | manual
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    asset_classes: Mapped[list["SnapshotAssetClass"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan")
    holdings: Mapped[list["SnapshotHolding"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan")


class SnapshotAssetClass(Base):
    __tablename__ = "snapshot_asset_classes"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("portfolio_snapshots.id", ondelete="CASCADE"), index=True)
    asset_class: Mapped[str] = mapped_column(String(50))
    value_paise: Mapped[int] = mapped_column(BigInteger)
    invested_paise: Mapped[int] = mapped_column(BigInteger)

    snapshot: Mapped[PortfolioSnapshot] = relationship(back_populates="asset_classes")


class SnapshotHolding(Base):
    __tablename__ = "snapshot_holdings"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("portfolio_snapshots.id", ondelete="CASCADE"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"))
    asset_class: Mapped[str] = mapped_column(String(50))
    quantity: Mapped[Decimal] = mapped_column(DecimalText)
    avg_cost: Mapped[Decimal | None] = mapped_column(DecimalText)
    invested_paise: Mapped[int] = mapped_column(BigInteger)
    price: Mapped[Decimal | None] = mapped_column(DecimalText)
    price_date: Mapped[date | None] = mapped_column(Date)
    price_source: Mapped[str | None] = mapped_column(String(50))
    value_paise: Mapped[int | None] = mapped_column(BigInteger)

    snapshot: Mapped[PortfolioSnapshot] = relationship(back_populates="holdings")


class AppSetting(Base):
    """One row per settings section (targets, drift, concentration, projection, emergency_fund)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ChangeLogEntry(Base):
    __tablename__ = "change_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(30))  # TXN_ADDED|TXN_REMOVED|QTY_CHANGED|AVG_COST_CHANGED|ALLOCATION_CHANGED
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"))
    snapshot_date: Mapped[date | None] = mapped_column(Date, index=True)
    cause: Mapped[str] = mapped_column(String(20))  # import | ui | snapshot
    summary: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class SectorAssignment(Base):
    """Sector per instrument and origin. Effective sector: MANUAL > EXCEL > NSE."""

    __tablename__ = "sector_assignments"
    __table_args__ = (UniqueConstraint("instrument_id", "origin"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    origin: Mapped[str] = mapped_column(String(10))  # NSE | EXCEL | MANUAL
    sector: Mapped[str] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(200))
    as_of: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)


class InstrumentFact(Base):
    """Fundamentals / fund facts. AUTO rows come from a data source, MANUAL rows from the user."""

    __tablename__ = "instrument_facts"
    __table_args__ = (UniqueConstraint("instrument_id", "metric", "origin"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    metric: Mapped[str] = mapped_column(String(40))
    origin: Mapped[str] = mapped_column(String(10))  # AUTO | MANUAL
    status: Mapped[str] = mapped_column(String(10), default="OK")  # OK | MISSING | REJECTED
    value: Mapped[Decimal | None] = mapped_column(DecimalText)
    value_text: Mapped[str | None] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(300))
    as_of: Mapped[date | None] = mapped_column(Date)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    note: Mapped[str | None] = mapped_column(Text)


class FundDisclosure(Base):
    """One uploaded portfolio disclosure (or index-weight file) for a fund and month."""

    __tablename__ = "fund_disclosures"
    __table_args__ = (UniqueConstraint("instrument_id", "kind", "as_of"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # AMC_DISCLOSURE | INDEX_WEIGHTS
    as_of: Mapped[date] = mapped_column(Date)
    index_name: Mapped[str | None] = mapped_column(String(100))
    parser: Mapped[str] = mapped_column(String(50))
    source_file: Mapped[str] = mapped_column(String(300))
    file_sha256: Mapped[str] = mapped_column(String(64))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    equity_weight: Mapped[Decimal] = mapped_column(DecimalText)
    rows: Mapped[int] = mapped_column(Integer)

    holdings: Mapped[list["DisclosureHolding"]] = relationship(back_populates="disclosure",
                                                               cascade="all, delete-orphan")


class DisclosureHolding(Base):
    __tablename__ = "disclosure_holdings"

    id: Mapped[int] = mapped_column(primary_key=True)
    disclosure_id: Mapped[int] = mapped_column(ForeignKey("fund_disclosures.id", ondelete="CASCADE"), index=True)
    isin: Mapped[str | None] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(300))
    industry: Mapped[str | None] = mapped_column(String(150))
    weight: Mapped[Decimal] = mapped_column(DecimalText)  # fraction of fund NAV
    is_equity: Mapped[bool] = mapped_column(Boolean)

    disclosure: Mapped[FundDisclosure] = relationship(back_populates="holdings")


# ---------------- Phase 4
class NewsItem(Base):
    """A news headline or exchange announcement for a company (by ISIN). Text is source text only."""

    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str] = mapped_column(String(20), index=True)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"))
    company: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(100))
    source_kind: Mapped[str] = mapped_column(String(10))  # EXCHANGE | NEWS
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    category: Mapped[str] = mapped_column(String(40))
    category_origin: Mapped[str] = mapped_column(String(10))  # RULE | MODEL
    summary: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(64), index=True)


class NewsSourceStatus(Base):
    __tablename__ = "news_source_status"
    __table_args__ = (UniqueConstraint("source", "isin"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(100))
    isin: Mapped[str | None] = mapped_column(String(20))  # None = whole-source status
    ok: Mapped[bool] = mapped_column(Boolean)
    message: Mapped[str] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MacroValue(Base):
    __tablename__ = "macro_values"
    __table_args__ = (UniqueConstraint("key", "origin"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(50))
    origin: Mapped[str] = mapped_column(String(10))  # AUTO | MANUAL
    label: Mapped[str] = mapped_column(String(100))
    value: Mapped[Decimal | None] = mapped_column(DecimalText)
    unit: Mapped[str] = mapped_column(String(30))
    source: Mapped[str] = mapped_column(String(300))
    as_of: Mapped[date | None] = mapped_column(Date)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(10), default="OK")  # OK | UNAVAILABLE
    note: Mapped[str | None] = mapped_column(Text)


class SectorSensitivity(Base):
    __tablename__ = "sector_sensitivities"

    sector: Mapped[str] = mapped_column(String(150), primary_key=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    origin: Mapped[str] = mapped_column(String(10))  # STARTER | USER
    note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class LlmAnalysis(Base):
    __tablename__ = "llm_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10), default="stock", server_default="stock")  # stock | fund | portfolio
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"), index=True)
    requested_model: Mapped[str | None] = mapped_column(String(100))
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    input_json: Mapped[dict] = mapped_column(JSON)
    output_json: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(10))  # OK | FAILED
    errors: Mapped[list] = mapped_column(JSON, default=list)
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(20))
    data_as_of: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)


class LlmCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    purpose: Mapped[str] = mapped_column(String(20))  # analysis | category
    model: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(Text)


class ThesisEntry(Base):
    """Append-only: a new version is a new row; rows are never updated or deleted."""

    __tablename__ = "thesis_entries"
    __table_args__ = (UniqueConstraint("instrument_id", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    why: Mapped[str] = mapped_column(Text)
    change_view: Mapped[str] = mapped_column(Text)
    horizon: Mapped[str] = mapped_column(String(100))
    review_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    linked_txn_ids: Mapped[list] = mapped_column(JSON, default=list)
    linked_change_ids: Mapped[list] = mapped_column(JSON, default=list)


class ThesisOptIn(Base):
    __tablename__ = "thesis_optin"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    send_to_llm: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    rule: Mapped[str] = mapped_column(String(40))
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"))
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AlertState(Base):
    __tablename__ = "alert_state"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)



# ---------------- Phase 5
class AnnualFinancial(Base):
    """Annual statement lines per NSE symbol (own holdings and peers), from yfinance."""

    __tablename__ = "annual_financials"
    __table_args__ = (UniqueConstraint("symbol", "fiscal_year_end", "metric"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(50), index=True)
    fiscal_year_end: Mapped[date] = mapped_column(Date)
    metric: Mapped[str] = mapped_column(String(40))  # revenue|net_income|ebit|interest_expense|fcf|equity|total_debt|diluted_eps
    value: Mapped[Decimal] = mapped_column(DecimalText)
    source: Mapped[str] = mapped_column(String(200))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PeerSet(Base):
    """User-maintained peers for one holding (max 8 NSE symbols). Nothing is seeded."""

    __tablename__ = "peer_sets"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    symbols: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class PeerMetric(Base):
    __tablename__ = "peer_metrics"
    __table_args__ = (UniqueConstraint("symbol", "metric"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(50), index=True)
    metric: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(10))  # OK | MISSING | REJECTED
    value: Mapped[Decimal | None] = mapped_column(DecimalText)
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(200))
    as_of: Mapped[date | None] = mapped_column(Date)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QualitativeEntry(Base):
    """Append-only, versioned qualitative notes per holding."""

    __tablename__ = "qualitative_entries"
    __table_args__ = (UniqueConstraint("instrument_id", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    moat_type: Mapped[str] = mapped_column(String(40))
    moat_note: Mapped[str] = mapped_column(Text)
    capital_allocation_note: Mapped[str] = mapped_column(Text)
    source_note: Mapped[str] = mapped_column(Text)
    as_of: Mapped[date] = mapped_column(Date)
    thesis_entry_id: Mapped[int | None] = mapped_column(ForeignKey("thesis_entries.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SourceEvent(Base):
    __tablename__ = "source_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(60), index=True)
    ok: Mapped[bool] = mapped_column(Boolean)
    message: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SnapshotGap(Base):
    """A calendar date with no snapshot because the app was not running. Never back-filled."""

    __tablename__ = "snapshot_gaps"

    gap_date: Mapped[date] = mapped_column(Date, primary_key=True)
    reason: Mapped[str] = mapped_column(String(200))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
