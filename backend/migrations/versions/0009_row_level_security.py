"""phase 6: Postgres Row Level Security (defence in depth; no-op on SQLite)

Per-user tables: RLS enabled and FORCED, one policy: a row is visible/writable when its user_id equals the
transaction's `app.user_id`, or when `app.system = 'on'` (jobs, migrations). The app sets both with SET LOCAL at the
start of every transaction (app/tenancy.py). Roles with BYPASSRLS (superusers) ignore policies: the app must connect
as a role without it (docs/DEPLOY.md).

Global tables: RLS enabled with no policy, so Supabase's Data API roles (anon, authenticated) can read nothing; the
backend owner role is not affected (RLS not forced there).

Revision ID: 0009_row_level_security
Revises: 0008_multi_user
Create Date: 2026-10-18
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0009_row_level_security"
down_revision: Union[str, Sequence[str], None] = "0008_multi_user"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

USER_TABLES = [
    "instruments", "transactions", "fallback_holdings", "monthly_plan_items", "identifier_candidates", "import_runs",
    "import_previews", "portfolio_snapshots", "snapshot_asset_classes", "snapshot_holdings", "app_settings",
    "change_log", "sector_assignments", "instrument_facts", "fund_disclosures", "disclosure_holdings",
    "sector_sensitivities", "llm_analyses", "llm_calls", "thesis_entries", "thesis_optin", "alerts", "alert_state",
    "peer_sets", "qualitative_entries",
]
GLOBAL_TABLES = [
    "users", "allowed_emails", "securities", "price_quotes", "intraday_ticks", "security_facts", "security_sectors",
    "annual_financials", "peer_metrics", "news_items", "news_source_status", "macro_values", "source_events",
    "refresh_runs", "snapshot_gaps", "platform_settings", "alembic_version",
]
POLICY = ("current_setting('app.system', true) = 'on' "
          "OR user_id = NULLIF(current_setting('app.user_id', true), '')::integer")


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for t in USER_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING ({POLICY}) WITH CHECK ({POLICY})")
    for t in GLOBAL_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
    # Supabase exposes the public schema to these roles through its Data API; the app never uses it.
    op.execute("""
        DO $$
        DECLARE r text;
        BEGIN
          FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
              EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM %I', r);
              EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM %I', r);
            END IF;
          END LOOP;
        END $$;
    """)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for t in USER_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {t}")
        op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")
    for t in GLOBAL_TABLES:
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")
