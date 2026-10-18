-- Read-only role for `make backup-prod` (pg_dump). Run once per database as the Supabase `postgres` role:
--   psql "$ADMIN_URL" -v backup_password='...' -f backend/deploy/backup_role.sql
-- It can READ everything (BYPASSRLS is required: pg_dump must see every user's rows, and the per-user tables
-- FORCE row level security) but can write nothing: only SELECT is granted and every transaction is read-only.
-- Keep its password only where you run backups (your machine), never on Render or Vercel.
CREATE ROLE investments_backup LOGIN PASSWORD :'backup_password' NOSUPERUSER BYPASSRLS NOCREATEDB NOCREATEROLE;
ALTER ROLE investments_backup SET default_transaction_read_only = on;
GRANT USAGE ON SCHEMA public TO investments_backup;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO investments_backup;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO investments_backup;
-- tables created later by migrations (they run as investments_app) are readable too
ALTER DEFAULT PRIVILEGES FOR ROLE investments_app IN SCHEMA public GRANT SELECT ON TABLES TO investments_backup;
ALTER DEFAULT PRIVILEGES FOR ROLE investments_app IN SCHEMA public GRANT SELECT ON SEQUENCES TO investments_backup;
