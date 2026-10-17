# Personal Investment Dashboard — local only (binds to 127.0.0.1)
SHELL   := /bin/bash
.SHELLFLAGS := -euo pipefail -c
PY      ?= python3
VENV    := backend/.venv
BIN     := $(VENV)/bin
FILE    ?= data/personal_investment_tracker_clean.xlsx


.PHONY: check hooks help setup backend frontend dev test test-backend test-frontend import refresh lint backup migrate fundamentals

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

setup: hooks
	test -d $(VENV) || $(PY) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -r backend/requirements.txt
	cd frontend && npm install

backend:
	cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

frontend:
	cd frontend && npm run dev

dev:
	@trap 'kill 0' INT TERM EXIT; \
	(cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload) & \
	(cd frontend && npm run dev) & \
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
