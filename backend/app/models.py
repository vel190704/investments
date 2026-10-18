"""ORM models.

Multi-user (Phase 6): every per-user table inherits `UserOwned` (a NOT NULL user_id). Sessions carry the user and
app/tenancy.py adds `user_id = :uid` to every ORM query on these tables, so a forgotten filter cannot leak rows.
Market data (securities, quotes, ticks, auto fundamentals, NSE sectors, news, macro) is global: no user_id.

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
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import false
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from app.db import Base
from app.types import DecimalText, UTCDateTime
from app.timeutil import utcnow


# ---------------- accounts
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    auth_subject: Mapped[str | None] = mapped_column(String(64), unique=True)  # Supabase auth user uuid
    email: Mapped[str] = mapped_column(String(320), unique=True)
    role: Mapped[str] = mapped_column(String(10), default="user")  # admin | user
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_monthly_cap: Mapped[int] = mapped_column(Integer, default=10)
    own_key_encrypted: Mapped[str | None] = mapped_column(Text)  # Fernet token; never returned or logged
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_active_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AllowedEmail(Base):
    """Invite list: only these emails may use the app (open sign-up is off)."""

    __tablename__ = "allowed_emails"

    email: Mapped[str] = mapped_column(String(320), primary_key=True)
    invited_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class UserOwned:
    """Mixin for per-user tables. Never filter by hand: the session does it (app/tenancy.py)."""

    @declared_attr
    def user_id(cls) -> Mapped[int]:
        return mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)


# ---------------- global market identity
class Security(Base):
    """One tradable thing, shared by every user who holds it: an NSE symbol (stock/ETF) or an AMFI scheme code."""

    __tablename__ = "securities"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)  # NSE:LT | AMFI:120716
    kind: Mapped[str] = mapped_column(String(10))  # STOCK | ETF | MF
    symbol: Mapped[str | None] = mapped_column(String(50), index=True)
    scheme_code: Mapped[str | None] = mapped_column(String(20), index=True)
    isin: Mapped[str | None] = mapped_column(String(20))  # from NSE's own list (exact symbol match)
    name: Mapped[str | None] = mapped_column(String(300))
    etf_underlying: Mapped[str | None] = mapped_column(String(50))  # NSE: EQUITY|COMMODITY|DEBT|GLOBAL INDICES
    etf_underlying_key: Mapped[str | None] = mapped_column(String(100))  # NSE: GOLD, SILVER, Nifty 50, ...
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Instrument(UserOwned, Base):
    """A user's own entry for a holding (named as in their workbook), linked to a global security once known."""

    __tablename__ = "instruments"
    __table_args__ = (UniqueConstraint("user_id", "instrument_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_key: Mapped[str] = mapped_column(String(200))
    security_id: Mapped[int | None] = mapped_column(ForeignKey("securities.id"), index=True)
    asset_type: Mapped[str] = mapped_column(String(10))  # STOCK | ETF | MF
    name: Mapped[str] = mapped_column(String(300))
    symbol: Mapped[str | None] = mapped_column(String(50))
    isin: Mapped[str | None] = mapped_column(String(20))
    scheme_code: Mapped[str | None] = mapped_column(String(20))
    exposure: Mapped[str] = mapped_column(String(20), default="DOMESTIC")  # DOMESTIC | INTERNATIONAL
    category: Mapped[str | None] = mapped_column(String(100))  # label derived from the user's name for it
    platform: Mapped[str | None] = mapped_column(String(50))
    # Phase 3 classification (the user's own overrides)
    asset_class_override: Mapped[str | None] = mapped_column(String(50))
    region: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="instrument")
    security: Mapped[Security | None] = relationship(lazy="joined")

    # market metadata lives on the shared security
    @property
    def etf_underlying(self) -> str | None:
        return self.security.etf_underlying if self.security else None

    @property
    def etf_underlying_key(self) -> str | None:
        return self.security.etf_underlying_key if self.security else None


TXN_SOURCES = ("excel", "ui")


class Transaction(UserOwned, Base):
    __tablename__ = "transactions"
    __table_args__ = (CheckConstraint("source IN ('excel', 'ui')", name="ck_transactions_source"),
                      UniqueConstraint("user_id", "row_key"))

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
    row_key: Mapped[str] = mapped_column(String(100))
    source_file: Mapped[str | None] = mapped_column(String(300))
    source_row: Mapped[int | None] = mapped_column(Integer)
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    instrument: Mapped[Instrument] = relationship(back_populates="transactions")


class FallbackHolding(UserOwned, Base):
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


class MonthlyPlanItem(UserOwned, Base):
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


class IdentifierCandidate(UserOwned, Base):
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
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class PriceQuote(Base):
    __tablename__ = "price_quotes"
    __table_args__ = (UniqueConstraint("security_id", "source", "price_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), index=True)
    source: Mapped[str] = mapped_column(String(50))
    source_ref: Mapped[str | None] = mapped_column(String(100))
    price: Mapped[Decimal] = mapped_column(DecimalText)
    previous_close: Mapped[Decimal | None] = mapped_column(DecimalText)
    previous_date: Mapped[date | None] = mapped_column(Date)
    price_date: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(10), default="INR")
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class ImportRun(UserOwned, Base):
    __tablename__ = "import_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
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
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    ok_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    results: Mapped[list] = mapped_column(JSON, default=list)


class PortfolioSnapshot(UserOwned, Base):
    """One row per IST calendar date (upserted)."""

    __tablename__ = "portfolio_snapshots"
    __table_args__ = (UniqueConstraint("user_id", "snapshot_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date)
    total_value_paise: Mapped[int] = mapped_column(BigInteger)  # priced holdings only
    total_invested_paise: Mapped[int] = mapped_column(BigInteger)  # all open holdings
    invested_priced_paise: Mapped[int] = mapped_column(BigInteger)
    unpriced: Mapped[list] = mapped_column(JSON, default=list)  # names of holdings without a price
    trigger: Mapped[str] = mapped_column(String(20))  # refresh | scheduled | startup | manual
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    asset_classes: Mapped[list["SnapshotAssetClass"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan")
    holdings: Mapped[list["SnapshotHolding"]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan")


class SnapshotAssetClass(UserOwned, Base):
    __tablename__ = "snapshot_asset_classes"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("portfolio_snapshots.id", ondelete="CASCADE"), index=True)
    asset_class: Mapped[str] = mapped_column(String(50))
    value_paise: Mapped[int] = mapped_column(BigInteger)
    invested_paise: Mapped[int] = mapped_column(BigInteger)

    snapshot: Mapped[PortfolioSnapshot] = relationship(back_populates="asset_classes")


class SnapshotHolding(UserOwned, Base):
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


class AppSetting(UserOwned, Base):
    """One row per user and settings section (targets, drift, concentration, projection, emergency_fund, ...)."""

    __tablename__ = "app_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class ChangeLogEntry(UserOwned, Base):
    __tablename__ = "change_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(30))  # TXN_ADDED|TXN_REMOVED|QTY_CHANGED|AVG_COST_CHANGED|ALLOCATION_CHANGED
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"))
    snapshot_date: Mapped[date | None] = mapped_column(Date, index=True)
    cause: Mapped[str] = mapped_column(String(20))  # import | ui | snapshot
    summary: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


class SectorAssignment(UserOwned, Base):
    """The user's sector per instrument: EXCEL (holdings_fallback) or MANUAL. NSE sectors are in security_sectors.
    Effective sector: MANUAL > EXCEL > NSE."""

    __tablename__ = "sector_assignments"
    __table_args__ = (UniqueConstraint("instrument_id", "origin"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    origin: Mapped[str] = mapped_column(String(10))  # EXCEL | MANUAL
    sector: Mapped[str] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(200))
    as_of: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)


class InstrumentFact(UserOwned, Base):
    """The user's MANUAL fundamentals / fund facts (with a source note). AUTO values are in security_facts."""

    __tablename__ = "instrument_facts"
    __table_args__ = (UniqueConstraint("instrument_id", "metric", "origin"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), index=True)
    metric: Mapped[str] = mapped_column(String(40))
    origin: Mapped[str] = mapped_column(String(10), default="MANUAL")  # MANUAL
    status: Mapped[str] = mapped_column(String(10), default="OK")  # OK | MISSING | REJECTED
    value: Mapped[Decimal | None] = mapped_column(DecimalText)
    value_text: Mapped[str | None] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(300))
    as_of: Mapped[date | None] = mapped_column(Date)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    note: Mapped[str | None] = mapped_column(Text)


class SecurityFact(Base):
    """AUTO fundamentals / fund facts from a data source, shared by every holder of the security."""

    __tablename__ = "security_facts"
    __table_args__ = (UniqueConstraint("security_id", "metric"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), index=True)
    metric: Mapped[str] = mapped_column(String(40))
    origin: Mapped[str] = mapped_column(String(10), default="AUTO")
    status: Mapped[str] = mapped_column(String(10), default="OK")  # OK | MISSING | REJECTED
    value: Mapped[Decimal | None] = mapped_column(DecimalText)
    value_text: Mapped[str | None] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(300))
    as_of: Mapped[date | None] = mapped_column(Date)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    note: Mapped[str | None] = mapped_column(Text)


class SecuritySector(Base):
    """Sector from NSE index constituent lists (Industry), per security."""

    __tablename__ = "security_sectors"

    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), primary_key=True)
    sector: Mapped[str] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(200))
    as_of: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)


class FundDisclosure(UserOwned, Base):
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
    uploaded_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    equity_weight: Mapped[Decimal] = mapped_column(DecimalText)
    rows: Mapped[int] = mapped_column(Integer)

    holdings: Mapped[list["DisclosureHolding"]] = relationship(back_populates="disclosure",
                                                               cascade="all, delete-orphan")


class DisclosureHolding(UserOwned, Base):
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
    company: Mapped[str] = mapped_column(String(300))
    title: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(100))
    source_kind: Mapped[str] = mapped_column(String(10))  # EXCHANGE | NEWS
    url: Mapped[str] = mapped_column(String(1000), unique=True)
    published_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
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
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    items_fetched: Mapped[int | None] = mapped_column(Integer)  # last refresh; None when the source failed
    items_matched: Mapped[int | None] = mapped_column(Integer)


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
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="OK")  # OK | UNAVAILABLE
    note: Mapped[str | None] = mapped_column(Text)


class SectorSensitivity(UserOwned, Base):
    __tablename__ = "sector_sensitivities"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    sector: Mapped[str] = mapped_column(String(150), primary_key=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    origin: Mapped[str] = mapped_column(String(10))  # STARTER | USER
    note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class LlmAnalysis(UserOwned, Base):
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
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)


class LlmCall(UserOwned, Base):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    purpose: Mapped[str] = mapped_column(String(20))  # analysis | category
    model: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(Text)
    own_key: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # user's own key: not in the global cap


class ThesisEntry(UserOwned, Base):
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
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    linked_txn_ids: Mapped[list] = mapped_column(JSON, default=list)
    linked_change_ids: Mapped[list] = mapped_column(JSON, default=list)


class ThesisOptIn(UserOwned, Base):
    __tablename__ = "thesis_optin"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    send_to_llm: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class Alert(UserOwned, Base):
    __tablename__ = "alerts"
    __table_args__ = (UniqueConstraint("user_id", "dedupe_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    rule: Mapped[str] = mapped_column(String(40))
    dedupe_key: Mapped[str] = mapped_column(String(200))
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instruments.id"))
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AlertState(UserOwned, Base):
    __tablename__ = "alert_state"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
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
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class PeerSet(UserOwned, Base):
    """User-maintained peers for one holding (max 8 NSE symbols). Nothing is seeded."""

    __tablename__ = "peer_sets"

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.id"), primary_key=True)
    symbols: Mapped[list] = mapped_column(JSON, default=list)
    note: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


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
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class QualitativeEntry(UserOwned, Base):
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
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class SourceEvent(Base):
    __tablename__ = "source_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(60), index=True)
    ok: Mapped[bool] = mapped_column(Boolean)
    message: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class SnapshotGap(Base):
    """A calendar date with no snapshot because the app was not running. Never back-filled."""

    __tablename__ = "snapshot_gaps"

    gap_date: Mapped[date] = mapped_column(Date, primary_key=True)
    reason: Mapped[str] = mapped_column(String(200))
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class IntradayTick(Base):
    """Real intraday quotes (1-minute bars) for direct stocks/ETFs, kept 14 days. Never used by snapshots, XIRR or
    history (those stay end-of-day from price_quotes)."""

    __tablename__ = "intraday_ticks"
    __table_args__ = (UniqueConstraint("security_id", "ts", "source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int] = mapped_column(ForeignKey("securities.id"), index=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)  # the quote's own time (bar start)
    price: Mapped[Decimal] = mapped_column(DecimalText)
    source: Mapped[str] = mapped_column(String(80))
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


# ---------------- Phase 6
class PlatformSetting(Base):
    """Platform-wide settings (admin only): news feeds, market holidays, live poll interval, AI platform limits."""

    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class ImportPreview(UserOwned, Base):
    """An uploaded workbook waiting for Confirm (one-shot token = its sha256). Kept in the DB, not on disk."""

    __tablename__ = "import_previews"
    __table_args__ = (UniqueConstraint("user_id", "token"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64))
    file_name: Mapped[str] = mapped_column(String(300))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
