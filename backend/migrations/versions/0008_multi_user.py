"""phase 6: multi-user (users, invites, securities, user_id on per-user tables, shared market data)

Upgrades a single-user database in place: if it holds any data, an owner account is created
(LEGACY_OWNER_EMAIL, default DEV_USER_EMAIL / owner@localhost; role admin) and every existing row is assigned to it.
Market data is re-keyed from (per-user) instruments to shared securities. Totals are unchanged.

Revision ID: 0008_multi_user
Revises: 0007_intraday_ticks
Create Date: 2026-10-18
"""
import json
import os
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

import app.types

revision: str = "0008_multi_user"
down_revision: Union[str, Sequence[str], None] = "0007_intraday_ticks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# per-user tables that only need a user_id column (rebuilt/re-keyed tables are handled separately)
SIMPLE_USER_TABLES = [
    "instruments", "transactions", "fallback_holdings", "monthly_plan_items", "identifier_candidates", "import_runs",
    "portfolio_snapshots", "snapshot_asset_classes", "snapshot_holdings", "change_log", "sector_assignments",
    "instrument_facts", "fund_disclosures", "disclosure_holdings", "llm_analyses", "llm_calls", "thesis_entries",
    "thesis_optin", "alerts", "peer_sets", "qualitative_entries",
]
NC = {"uq": "uq_%(table_name)s_%(column_0_N_name)s",
      "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}


def _sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def _uq_name(table: str, cols: list[str]) -> str:
    if _sqlite():
        return f"uq_{table}_{'_'.join(cols)}"
    for uc in sa.inspect(op.get_bind()).get_unique_constraints(table):
        if uc["column_names"] == cols:
            return uc["name"]
    raise RuntimeError(f"unique constraint {table}{cols} not found")


def _fk_name(table: str, col: str, ref: str) -> str:
    if _sqlite():
        return f"fk_{table}_{col}_{ref}"
    for fk in sa.inspect(op.get_bind()).get_foreign_keys(table):
        if fk["constrained_columns"] == [col]:
            return fk["name"]
    raise RuntimeError(f"foreign key {table}.{col} not found")


def _ts():
    return app.types.UTCDateTime()


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    if is_pg:  # migrations run as the system (Row Level Security, 0009, uses these settings)
        bind.exec_driver_sql("SELECT set_config('app.system', 'on', true)")

    # ---- accounts and shared identity
    op.create_table("users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("auth_subject", sa.String(length=64), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("ai_enabled", sa.Boolean(), nullable=False),
        sa.Column("ai_monthly_cap", sa.Integer(), nullable=False),
        sa.Column("own_key_encrypted", sa.Text(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("last_active_at", _ts(), nullable=True),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("auth_subject"), sa.UniqueConstraint("email"))
    op.create_table("allowed_emails",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("invited_by", sa.Integer(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(["invited_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("email"))
    op.create_table("securities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("symbol", sa.String(length=50), nullable=True),
        sa.Column("scheme_code", sa.String(length=20), nullable=True),
        sa.Column("isin", sa.String(length=20), nullable=True),
        sa.Column("name", sa.String(length=300), nullable=True),
        sa.Column("etf_underlying", sa.String(length=50), nullable=True),
        sa.Column("etf_underlying_key", sa.String(length=100), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("key"))
    with op.batch_alter_table("securities") as b:
        b.create_index("ix_securities_symbol", ["symbol"], unique=False)
        b.create_index("ix_securities_scheme_code", ["scheme_code"], unique=False)
    op.create_table("security_facts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("security_id", sa.Integer(), nullable=False),
        sa.Column("metric", sa.String(length=40), nullable=False),
        sa.Column("origin", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("value", app.types.DecimalText(length=64), nullable=True),
        sa.Column("value_text", sa.String(length=300), nullable=True),
        sa.Column("source", sa.String(length=300), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=True),
        sa.Column("fetched_at", _ts(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["security_id"], ["securities.id"]),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("security_id", "metric"))
    with op.batch_alter_table("security_facts") as b:
        b.create_index("ix_security_facts_security_id", ["security_id"], unique=False)
    op.create_table("security_sectors",
        sa.Column("security_id", sa.Integer(), nullable=False),
        sa.Column("sector", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=200), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["security_id"], ["securities.id"]),
        sa.PrimaryKeyConstraint("security_id"))
    op.create_table("platform_settings",
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.PrimaryKeyConstraint("key"))
    op.create_table("import_previews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("file_name", sa.String(length=300), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("user_id", "token"))
    with op.batch_alter_table("import_previews") as b:
        b.create_index("ix_import_previews_user_id", ["user_id"], unique=False)

    # ---- owner of existing (single-user) data
    has_data = any(bind.execute(sa.text(f"SELECT 1 FROM {t} LIMIT 1")).first()
                   for t in ("instruments", "app_settings", "transactions", "portfolio_snapshots"))
    owner = None
    if has_data:
        email = (os.environ.get("LEGACY_OWNER_EMAIL") or os.environ.get("DEV_USER_EMAIL") or "owner@localhost").lower()
        bind.execute(sa.text("INSERT INTO users (email, role, ai_enabled, ai_monthly_cap, created_at) "
                             "VALUES (:e, 'admin', :t, 30, CURRENT_TIMESTAMP)"), {"e": email, "t": True})
        owner = bind.execute(sa.text("SELECT id FROM users WHERE email = :e"), {"e": email}).scalar()

    # ---- securities from instruments (stocks/ETFs by NSE symbol; funds by a confirmed scheme code)
    rows = bind.execute(sa.text("SELECT id, asset_type, symbol, scheme_code, isin, name, etf_underlying, "
                                "etf_underlying_key FROM instruments")).mappings().all()
    sec_of: dict[int, int] = {}
    for r in rows:
        if r["asset_type"] in ("STOCK", "ETF") and r["symbol"]:
            key = f"NSE:{r['symbol'].strip().upper()}"
        elif r["asset_type"] == "MF" and r["scheme_code"]:
            key = f"AMFI:{r['scheme_code'].strip()}"
        else:
            continue
        sid = bind.execute(sa.text("SELECT id FROM securities WHERE key = :k"), {"k": key}).scalar()
        if sid is None:
            bind.execute(sa.text(
                "INSERT INTO securities (key, kind, symbol, scheme_code, isin, name, etf_underlying, etf_underlying_key,"
                " created_at) VALUES (:k, :kind, :sym, :sc, :isin, :name, :eu, :euk, CURRENT_TIMESTAMP)"),
                {"k": key, "kind": r["asset_type"],
                 "sym": r["symbol"].strip().upper() if r["asset_type"] in ("STOCK", "ETF") else None,
                 "sc": r["scheme_code"].strip() if r["asset_type"] == "MF" else None,
                 "isin": r["isin"] if r["asset_type"] in ("STOCK", "ETF") else None, "name": r["name"],
                 "eu": r["etf_underlying"], "euk": r["etf_underlying_key"]})
            sid = bind.execute(sa.text("SELECT id FROM securities WHERE key = :k"), {"k": key}).scalar()
        sec_of[r["id"]] = sid

    # ---- user_id on simple per-user tables
    for t in SIMPLE_USER_TABLES:
        with op.batch_alter_table(t) as b:
            b.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        if owner is not None:
            bind.execute(sa.text(f"UPDATE {t} SET user_id = :u"), {"u": owner})
        with op.batch_alter_table(t) as b:
            b.alter_column("user_id", existing_type=sa.Integer(), nullable=False)
            b.create_foreign_key(f"fk_{t}_user_id_users", "users", ["user_id"], ["id"], ondelete="CASCADE")
            b.create_index(f"ix_{t}_user_id", ["user_id"], unique=False)

    # ---- instruments: security link, per-user key, market metadata moved to securities
    with op.batch_alter_table("instruments") as b:
        b.add_column(sa.Column("security_id", sa.Integer(), nullable=True))
    for iid, sid in sec_of.items():
        bind.execute(sa.text("UPDATE instruments SET security_id = :s WHERE id = :i"), {"s": sid, "i": iid})
    with op.batch_alter_table("instruments", naming_convention=NC) as b:
        b.drop_constraint(_uq_name("instruments", ["instrument_key"]), type_="unique")
        b.create_unique_constraint("uq_instruments_user_id_instrument_key", ["user_id", "instrument_key"])
        b.create_foreign_key("fk_instruments_security_id_securities", "securities", ["security_id"], ["id"])
        b.create_index("ix_instruments_security_id", ["security_id"], unique=False)
        b.drop_column("etf_underlying")
        b.drop_column("etf_underlying_key")

    # ---- per-user unique keys
    for t, old, new in (("transactions", ["row_key"], ["user_id", "row_key"]),
                        ("portfolio_snapshots", ["snapshot_date"], ["user_id", "snapshot_date"]),
                        ("alerts", ["dedupe_key"], ["user_id", "dedupe_key"])):
        with op.batch_alter_table(t, naming_convention=NC) as b:
            b.drop_constraint(_uq_name(t, old), type_="unique")
            b.create_unique_constraint(f"uq_{t}_{'_'.join(new)}", new)

    # ---- AUTO facts and NSE sectors become shared (per security)
    for r in bind.execute(sa.text(
            "SELECT instrument_id, metric, status, value, value_text, source, as_of, fetched_at, note "
            "FROM instrument_facts WHERE origin = 'AUTO'")).mappings().all():
        sid = sec_of.get(r["instrument_id"])
        if sid is None or bind.execute(sa.text("SELECT 1 FROM security_facts WHERE security_id = :s AND metric = :m"),
                                       {"s": sid, "m": r["metric"]}).first():
            continue
        bind.execute(sa.text(
            "INSERT INTO security_facts (security_id, metric, origin, status, value, value_text, source, as_of, "
            "fetched_at, note) VALUES (:s, :metric, 'AUTO', :status, :value, :value_text, :source, :as_of, "
            ":fetched_at, :note)"), {**dict(r), "s": sid})
    bind.execute(sa.text("DELETE FROM instrument_facts WHERE origin = 'AUTO'"))
    for r in bind.execute(sa.text("SELECT instrument_id, sector, source, as_of, note FROM sector_assignments "
                                  "WHERE origin = 'NSE'")).mappings().all():
        sid = sec_of.get(r["instrument_id"])
        if sid is None or bind.execute(sa.text("SELECT 1 FROM security_sectors WHERE security_id = :s"),
                                       {"s": sid}).first():
            continue
        bind.execute(sa.text("INSERT INTO security_sectors (security_id, sector, source, as_of, note) "
                             "VALUES (:s, :sector, :source, :as_of, :note)"), {**dict(r), "s": sid})
    bind.execute(sa.text("DELETE FROM sector_assignments WHERE origin = 'NSE'"))

    # ---- price quotes and intraday ticks: re-keyed to securities (rebuilt with a copy)
    op.create_table("price_quotes_new",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("security_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column("source_ref", sa.String(length=100), nullable=True),
        sa.Column("price", app.types.DecimalText(length=64), nullable=False),
        sa.Column("previous_close", app.types.DecimalText(length=64), nullable=True),
        sa.Column("previous_date", sa.Date(), nullable=True),
        sa.Column("price_date", sa.Date(), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("fetched_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(["security_id"], ["securities.id"]),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("security_id", "source", "price_date"))
    op.create_table("intraday_ticks_new",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("security_id", sa.Integer(), nullable=False),
        sa.Column("ts", _ts(), nullable=False),
        sa.Column("price", app.types.DecimalText(length=64), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("fetched_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(["security_id"], ["securities.id"]),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("security_id", "ts", "source"))
    for iid, sid in sec_of.items():
        bind.execute(sa.text(
            "INSERT INTO price_quotes_new (security_id, source, source_ref, price, previous_close, previous_date, "
            "price_date, currency, fetched_at) SELECT :s, source, source_ref, price, previous_close, previous_date, "
            "price_date, currency, fetched_at FROM price_quotes WHERE instrument_id = :i"), {"s": sid, "i": iid})
        bind.execute(sa.text(
            "INSERT INTO intraday_ticks_new (security_id, ts, price, source, fetched_at) "
            "SELECT :s, ts, price, source, fetched_at FROM intraday_ticks WHERE instrument_id = :i"),
            {"s": sid, "i": iid})
    op.drop_table("price_quotes")
    op.drop_table("intraday_ticks")
    op.rename_table("price_quotes_new", "price_quotes")
    op.rename_table("intraday_ticks_new", "intraday_ticks")
    if is_pg:  # keep Postgres' default names in line with a fresh database
        for t, cols in (("price_quotes", "security_id_source_price_date"), ("intraday_ticks", "security_id_ts_source")):
            bind.exec_driver_sql(f"ALTER TABLE {t} RENAME CONSTRAINT {t}_new_pkey TO {t}_pkey")
            bind.exec_driver_sql(f"ALTER TABLE {t} RENAME CONSTRAINT {t}_new_{cols}_key TO {t}_{cols}_key")
            bind.exec_driver_sql(f"ALTER TABLE {t} RENAME CONSTRAINT {t}_new_security_id_fkey TO {t}_security_id_fkey")
            bind.exec_driver_sql(f"ALTER SEQUENCE {t}_new_id_seq RENAME TO {t}_id_seq")
    with op.batch_alter_table("price_quotes") as b:
        b.create_index("ix_price_quotes_security_id", ["security_id"], unique=False)
    with op.batch_alter_table("intraday_ticks") as b:
        b.create_index("ix_intraday_ticks_security_id", ["security_id"], unique=False)
        b.create_index("ix_intraday_ticks_ts", ["ts"], unique=False)

    # ---- news is global (by ISIN)
    with op.batch_alter_table("news_items", naming_convention=NC) as b:
        b.drop_constraint(_fk_name("news_items", "instrument_id", "instruments"), type_="foreignkey")
        b.drop_column("instrument_id")

    # ---- AI calls on a user's own key don't count toward the global cap
    with op.batch_alter_table("llm_calls") as b:
        b.add_column(sa.Column("own_key", sa.Boolean(), server_default=sa.false(), nullable=False))

    # ---- tables whose primary key gains user_id (rebuilt with a copy)
    settings = bind.execute(sa.text("SELECT key, value, updated_at FROM app_settings")).mappings().all()
    sens = bind.execute(sa.text("SELECT sector, tags, origin, note, updated_at FROM sector_sensitivities")).mappings().all()
    state = bind.execute(sa.text("SELECT key, value FROM alert_state")).mappings().all()
    op.drop_table("app_settings")
    op.drop_table("sector_sensitivities")
    op.drop_table("alert_state")
    op.create_table("app_settings",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "key"))
    op.create_table("sector_sensitivities",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("sector", sa.String(length=150), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("origin", sa.String(length=10), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "sector"))
    op.create_table("alert_state",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "key"))

    def j(v):
        return v if isinstance(v, (dict, list)) else json.loads(v)

    app_settings = sa.table("app_settings", sa.column("user_id"), sa.column("key"), sa.column("value", sa.JSON),
                            sa.column("updated_at"))
    platform = sa.table("platform_settings", sa.column("key"), sa.column("value", sa.JSON), sa.column("updated_at"))
    for r in settings:
        value = j(r["value"])
        if r["key"] in ("news", "market_holidays"):
            bind.execute(platform.insert().values(key=r["key"], value=value, updated_at=r["updated_at"]))
            continue
        if r["key"] == "live":
            if "poll_seconds" in value:
                bind.execute(platform.insert().values(key="live_platform", value={"poll_seconds": value["poll_seconds"]},
                                                      updated_at=r["updated_at"]))
            value = {"enabled": bool(value.get("enabled", False))}
        if r["key"] == "llm":
            pin, pout = value.pop("price_in_per_mtok", None), value.pop("price_out_per_mtok", None)
            if pin is not None or pout is not None:
                bind.execute(platform.insert().values(key="llm_platform", value={
                    "global_monthly_cap": 200, "price_in_per_mtok": pin, "price_out_per_mtok": pout},
                    updated_at=r["updated_at"]))
        if owner is not None:
            bind.execute(app_settings.insert().values(user_id=owner, key=r["key"], value=value, updated_at=r["updated_at"]))
    sens_t = sa.table("sector_sensitivities", sa.column("user_id"), sa.column("sector"), sa.column("tags", sa.JSON),
                      sa.column("origin"), sa.column("note"), sa.column("updated_at"))
    state_t = sa.table("alert_state", sa.column("user_id"), sa.column("key"), sa.column("value", sa.JSON))
    if owner is not None:
        for r in sens:
            bind.execute(sens_t.insert().values(user_id=owner, sector=r["sector"], tags=j(r["tags"]), origin=r["origin"],
                                                note=r["note"], updated_at=r["updated_at"]))
        for r in state:
            bind.execute(state_t.insert().values(user_id=owner, key=r["key"], value=j(r["value"])))


def downgrade() -> None:
    raise NotImplementedError("0008 is one-way: restore the automatic pre-migration backup in data/backups/ "
                              "(SQLite) or a Supabase backup (Postgres).")
