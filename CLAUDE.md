# CLAUDE.md — conventions for this repo

Personal, single-user, local-first investment **analytics** dashboard (Indian retail investor).
It never places orders. See PLAN.md for the design and README.md for usage.

## Commands
- `make setup`  — create `backend/.venv`, install Python deps, `npm install` in frontend
- `make dev`    — backend on 127.0.0.1:8000 + frontend on 127.0.0.1:3000
- `make test`   — backend pytest + frontend tests
- `make import FILE=data/personal_investment_tracker_clean.xlsx` — CLI import
- `make refresh` — fetch prices/NAVs and store today's snapshot
- `make backup` / `make migrate` — SQLite backup to data/backups/ / apply Alembic migrations
- `make fundamentals` — fetch fundamentals (yfinance) now
- `make lint` — eslint + tsc; `make test` also runs the frontend formatter tests
- Backend only: `cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload`
- Frontend only: `cd frontend && npm run dev`
- CLI import: `cd backend && .venv/bin/python -m app.import_excel ../data/<file>.xlsx`

## Working rules
- Work in phases; finish a phase, then stop and summarise for review.
- State assumptions in PLAN.md instead of silently choosing.
- Every financial calculation has a pytest test. Run tests before committing.
- Small commits per milestone. Never commit `.env`, `data/`, `*.db`, `node_modules`, `.venv`.
- No secrets in the repo; keys go in `.env` (template: `.env.example`).

## Schema changes
- Every schema change is an Alembic migration in `backend/migrations/versions/` (autogenerate
  against a DB at the previous head, then review; CHECK constraints are hand-written).
- `init_db()` runs migrations (never `create_all`) and backs up a SQLite file before applying any.
- `tests/test_migrations.py` must stay green: no model/migration drift; Phase-1 DBs upgrade with
  their data intact.

## Data provenance
- `transactions.source` is `excel` (owned by the workbook) or `ui` (entered in the app).
- An import may delete only `excel` rows missing from the file, and only when the file has zero
  errors. It never deletes `ui` rows, snapshots, settings or the change log.
- Every transaction or position change writes change-log entries (`app/services/changelog.py`).

## Architecture rules
- Single user: no auth, no user tables, no `user_id`. Backend binds to 127.0.0.1 only.
- DB access only through `app/db.py` + `app/repository.py`; switching to Postgres must be a
  `DATABASE_URL` change.
- `app/calc/` holds pure functions (no DB, no network) — that is what tests target.
- Market data sits behind the `PriceProvider` interface; results are cached in `price_quotes`.
  Pages read from the DB; only refresh jobs hit the network.

## Money and numbers
- Money is integer **paise** (`*_paise`); never float. Quantities/prices/NAVs/weights are
  `Decimal` (stored via `DecimalText`). Floats only for chart rendering.
- Display INR with Indian grouping (`1,23,456.00`): `app/money.py::format_inr`,
  `frontend/src/lib/format.ts::formatINR`.
- `allocation_percent` in the Excel is a fraction (0.6 = 60%).
- Weights = current market value / total portfolio value. Never share count.

## Data honesty
- Every market-derived number shows its source and as-of time; if missing show
  "Data unavailable". Never fabricate/estimate prices, P/E, ROE, ROCE, beta, expense ratio,
  tracking error, market cap or promoter holding.
- Identifier matches (ISIN, AMFI scheme code) are proposed, never silently applied: the user
  confirms them on the Mappings screen.
- OPENING rows count for quantity/invested/value/P&L but are excluded from XIRR.

## Classification and look-through
- Effective asset class: manual override > ETF by NSE "ETF Underlying" > Phase 1 rule. Effective sector:
  MANUAL > EXCEL (holdings_fallback.sector) > NSE index lists. Overrides are always tagged "manual".
- Fund look-through matches companies by **ISIN only** (equity = security code 01). A stock without a
  confirmed ISIN is listed as "not combined", never matched by name.
- AMC parsers live in `app/disclosures/engine.py` (one Layout per AMC). Unknown layouts must raise
  `DisclosureFormatError` with what was looked for and found; tests use synthetic fixtures built in
  `tests/disclosure_fixtures.py`, never real downloads.
- Fundamentals: a value is shown only if the source provided it and it passes the bounds in
  `app/calc/fundamentals.py`; otherwise "N/A (reason)". Manual values need a source note and an
  as-of date and are shown with a "manual" tag. Never scrape sites whose terms forbid it.
- Portfolio Health has no overall score or ranking; LOW/MODERATE/HIGH only where a threshold exists
  in code (editable in Settings › health); everything else is "information only".

## Outbound requests, news and the LLM (Phase 4)
- All news/announcement fetching goes through `app/net/polite.py`, which:
  - checks robots.txt (a 403 on robots.txt means not permitted);
  - rate-limits per host and caches responses;
  - skips a failing host for 10 min.
  - Blocked sources show "Source unavailable". Never spoof the User-Agent or otherwise work
    around blocking. Google News RSS is disallowed by its robots.txt.
- News text stored is the source's own title/summary only. Categories come from keyword rules
  first; the LLM may only suggest a category for items the rules left as "other" (origin MODEL).
- LLM calls happen only when the privacy toggle (`llm.outbound_enabled`, default false) is on,
  `ANTHROPIC_API_KEY` is set, and the monthly cap allows it (`app/services/analysis.py::gate`).
- LLM input is built only from stored data (`app/llm/inputs.py`): percentages, never rupee
  amounts, quantities, platform/account details or other holdings; thesis text only with
  per-holding opt-in.
- LLM output must pass `app/llm/validate.py` (no invented numbers, no recommendation/prediction
  wording, citations to input ids, schema); failures are flagged, never shown as analysis.
  Bump `PROMPT_VERSION` when the prompt or schema changes.
- Broker adapters are read-only: no order/modify/cancel methods, and the Groww HTTP layer
  allow-lists only the token and holdings endpoints (tested). Reconciliation never writes;
  the user confirms an in-app transaction.
- The thesis journal is append-only (no update/delete paths).

## Settings
- User choices have no invented defaults: targets and the emergency fund start unset ("Set your
  targets", empty state). Projection rates ship as flagged placeholders until reviewed.
- The monthly budget and split come from the workbook's `monthly_plan`; planner overrides are
  temporary.
- The emergency fund is never included in portfolio value, P&L, XIRR, allocation, snapshots or
  the planner (tested).

## Language and safety
- Neutral wording: "Adding ₹1,000 here would raise X from a% to b%". Never "buy/sell X".
- Suggestions are labelled "Allocation consideration". No return guarantees or price
  predictions. Projections are "mathematical scenario" with assumptions shown.
- Projection wording: "If the portfolio averaged X% annually and contributions were Y, the
  mathematical future value would be approximately Z." Never "you will have".
- Time series show only stored snapshots; never back-fill or estimate history.
- Show the date of all data; separate historical data from assumptions.
- Footer disclaimer: personal analytics tool, not investment advice. Analysis pages (news, macro,
  AI analysis) also carry: "Scenario and context analysis, not a prediction or investment advice."

## Style
- Python 3.12+ compatible (machine has 3.14), type hints, FastAPI + SQLAlchemy 2.x style.
- Frontend: Next.js App Router, TypeScript strict, Tailwind, shadcn/ui components in
  `src/components/ui`, Recharts for charts. Dark mode default, no decorative animation.
