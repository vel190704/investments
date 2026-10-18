-- The database role the app uses in every deployed environment (production and preview).
-- Run once per database as the Supabase `postgres` role (SQL editor or psql), choosing a strong password:
--   psql "$ADMIN_URL" -v app_password='...' -f backend/deploy/app_role.sql
-- The app connects as this role AND runs its migrations as this role (so it owns the tables).
-- Why: Row Level Security does not apply to superusers or roles with BYPASSRLS; this role has neither, and the
-- policies are FORCED on per-user tables, so they also apply to it as the owner. The app refuses to start outside
-- development/test if its role can bypass RLS (app/db.py::check_rls_role).
CREATE ROLE investments_app LOGIN PASSWORD :'app_password' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
GRANT USAGE, CREATE ON SCHEMA public TO investments_app;
