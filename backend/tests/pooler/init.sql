-- Test-only stack (throwaway passwords; nothing real). Same role shape as backend/deploy/app_role.sql.
CREATE ROLE pooler_app LOGIN PASSWORD 'pooler_app_test' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE DATABASE pooltest OWNER postgres;
\connect pooltest
GRANT USAGE, CREATE ON SCHEMA public TO pooler_app;
