# Personal Investment Dashboard — local only (binds to 127.0.0.1)
SHELL   := /bin/bash
.SHELLFLAGS := -euo pipefail -c
PY      ?= python3
VENV    := backend/.venv
BIN     := $(VENV)/bin
FILE    ?= data/personal_investment_tracker_clean.xlsx


.PHONY: check hooks help setup backend frontend dev test test-backend test-frontend import refresh lint backup migrate fundamentals logs logs-errors pg-up test-postgres test-all-postgres test-pooler smoke release backup-prod restore-test reapply-deletions test-backup audit audit-secrets audit-deps

help:
	@echo "make setup      install backend (venv) + frontend (npm) dependencies"
	@echo "make dev        run backend :8000 and frontend :3000 (Ctrl-C stops both)"
	@echo "make test       run backend pytest + frontend formatter tests"
	@echo "make check      tests + lint + typecheck; fails on any error (used by the pre-commit hook)"
	@echo "make import     import $(FILE)   (override: make import FILE=path.xlsx)"
	@echo "make refresh    fetch latest prices/NAVs now (also stores today's snapshot)"
	@echo "make fundamentals  fetch fundamentals from Yahoo Finance now (also weekly, Sundays)"
	@echo "make backup     copy the SQLite DB to data/backups/"
	@echo "make migrate    apply DB migrations (backs up first; also runs on backend start)"
	@echo "make pg-up      start a throwaway local Postgres in Docker for tests (127.0.0.1:55432)"
	@echo "make test-postgres      Postgres-only tests (RLS, advisory locks, isolation on Postgres, data move)"
	@echo "make test-all-postgres  the whole backend suite on Postgres"
	@echo "make test-pooler        user context through PgBouncer in transaction mode (Docker Compose)"
	@echo "make smoke URL=...      cross-user smoke test against a DEPLOYED preview backend (docs/DEPLOY.md §16)"
	@echo "make release            fast-forward production to main, only if CI for that commit is green (§17)"
	@echo "make backup-prod        encrypted pg_dump of production, outside the repo (docs/OPERATIONS.md)"
	@echo "make restore-test       restore the latest dump into a throwaway Postgres and verify it"
	@echo "make reapply-deletions REGISTER=path   after a restore: delete again everyone in the register"
	@echo "make test-backup        backup/restore/register tests against a synthetic database (CI)"
	@echo "make audit              gitleaks over the full git history + pip-audit + npm audit (CI: Security audit)"
	@echo "make logs       follow logs/app.log (Ctrl-C to stop)"
	@echo "make logs-errors  follow WARNING and above only"

setup: hooks
	test -d $(VENV) || $(PY) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -r backend/requirements-dev.txt
	cd frontend && npm install

# Local development uses the fake local user explicitly; anything else requires sign-in (fail closed).
LOCAL_DEV := ENV=development DEV_AUTH=1

backend:
	cd backend && $(LOCAL_DEV) .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

frontend:
	cd frontend && NEXT_PUBLIC_DEV_AUTH=1 npm run dev

dev:
	@trap 'kill 0' INT TERM EXIT; \
	(cd backend && $(LOCAL_DEV) .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload) & \
	(cd frontend && NEXT_PUBLIC_DEV_AUTH=1 npm run dev) & \
	wait

test: test-backend test-frontend

test-backend:
	cd backend && .venv/bin/python -m pytest

test-frontend:
	cd frontend && npm test

lint:
	cd frontend && npm run lint && npx tsc --noEmit

check:
	cd backend && .venv/bin/python -m pytest -q -p no:warnings
	cd frontend && npm test
	cd frontend && npm run lint
	cd frontend && rm -rf .next/dev/types .next/types && npx next typegen >/dev/null && npx tsc --noEmit
	@echo "make check: all passed"

hooks:
	git config core.hooksPath .githooks
	@echo "pre-commit hook installed (.githooks/pre-commit)"

import:
	cd backend && .venv/bin/python -m app.import_excel ../$(FILE)

refresh:
	cd backend && .venv/bin/python -m app.refresh

backup:
	cd backend && .venv/bin/python -m app.migrate --backup-only

migrate:
	cd backend && .venv/bin/python -m app.migrate

fundamentals:
	cd backend && .venv/bin/python -m app.fundamentals_cli

LOG := logs/app.log

logs:
	@test -f $(LOG) || { echo "No $(LOG) yet: start the backend (make dev)"; exit 1; }
	tail -n 100 -F $(LOG)

logs-errors:
	@test -f $(LOG) || { echo "No $(LOG) yet: start the backend (make dev)"; exit 1; }
	tail -n 2000 -F $(LOG) | grep --line-buffered -E '(level=|"level": ?")(WARNING|ERROR|CRITICAL)|^Traceback|^  File |^[A-Za-z_.]+(Error|Exception)'

# Local, throwaway Postgres for tests only (never real data; the password is not a secret).
PG_TEST_URL ?= postgresql+psycopg://postgres:localtest@127.0.0.1:55432/postgres

pg-up:
	docker start inv-pg-test >/dev/null 2>&1 || docker run -d --name inv-pg-test -e POSTGRES_PASSWORD=localtest \
		-p 127.0.0.1:55432:5432 postgres:17-alpine >/dev/null
	@echo "Postgres for tests on 127.0.0.1:55432"

test-postgres:
	cd backend && TEST_POSTGRES_URL=$(PG_TEST_URL) .venv/bin/python -m pytest -q -p no:warnings tests/test_postgres.py

test-all-postgres:
	cd backend && TEST_ALL_ON_POSTGRES=1 TEST_POSTGRES_URL=$(PG_TEST_URL) .venv/bin/python -m pytest -q -p no:warnings \
		--deselect tests/test_migrations.py

# Postgres behind PgBouncer in transaction mode (like Supabase's port-6543 pooler); test-only stack.
POOLER_COMPOSE := docker compose -f backend/tests/pooler/docker-compose.yml -p invpooler
test-pooler:
	$(POOLER_COMPOSE) up -d --wait
	cd backend && TEST_POOLER_URL=postgresql+psycopg://pooler_app:pooler_app_test@127.0.0.1:56432/pooltest \
		TEST_POOLER_DIRECT_URL=postgresql+psycopg://pooler_app:pooler_app_test@127.0.0.1:55433/pooltest \
		.venv/bin/python -m pytest -q -p no:warnings tests/test_pooler.py

# After each deploy, against the PREVIEW backend: two dummy accounts, a canary, no cross-user visibility.
smoke:
	@test -n "$(URL)" || { echo "usage: make smoke URL=https://<preview backend>"; exit 2; }
	cd backend && .venv/bin/python -m app.tools.smoke --url "$(URL)"

# Free-plan-safe release: production branch moves only to a main commit whose CI run passed (docs/DEPLOY.md §17).
release:
	cd backend && .venv/bin/python -m app.tools.release

# Backups (docs/OPERATIONS.md). Credentials only in your shell; dumps only outside the repository.
backup-prod:
	cd backend && .venv/bin/python -m app.tools.backup backup

restore-test:
	cd backend && .venv/bin/python -m app.tools.backup restore-test $(if $(DUMP),--dump "$(DUMP)",)

reapply-deletions:
	@test -n "$(REGISTER)" || { echo "usage: make reapply-deletions REGISTER=/path/outside/repo/deletions.csv"; exit 2; }
	cd backend && .venv/bin/python -m app.tools.backup reapply-deletions --register "$(REGISTER)"

test-backup:
	cd backend && TEST_POSTGRES_URL=$(PG_TEST_URL) .venv/bin/python -m pytest -q -p no:warnings tests/test_backup.py

# Security audit (also in CI). Secrets over the full history: blocking; reviewed false positives in .gitleaksignore.
GITLEAKS_IMAGE := ghcr.io/gitleaks/gitleaks:v8.24.3
audit: audit-secrets audit-deps

audit-secrets:
	docker run --rm -v "$(CURDIR)":/repo:ro $(GITLEAKS_IMAGE) git /repo --redact --no-banner

# Production dependencies: blocking. Full npm tree incl. build tooling: report only (docs/SECURITY.md).
audit-deps:
	cd backend && .venv/bin/pip-audit --progress-spinner off -r requirements.txt -r requirements-dev.txt
	cd frontend && npm audit --omit=dev --audit-level=high
	cd frontend && npm audit --audit-level=high || echo "npm audit (incl. dev tooling): findings above are report-only; see docs/SECURITY.md"
