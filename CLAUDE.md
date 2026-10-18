# CLAUDE.md — conventions for this repo

Invite-only, multi-user investment **analytics** web app for ~5-15 friends and family (Indian retail investors;
Phase 6). Each user uploads their own Excel workbook.
It never places orders and never connects to a broker or platform account: **Excel (plus the
in-app transaction form) is the only input for holdings and transactions.** See PLAN.md for the design and README.md for usage.

## Commands
- `make setup`  — create `backend/.venv`, install Python deps, `npm install` in frontend, install the
  git pre-commit hook (`core.hooksPath=.githooks`)
- `make check`  — backend tests + frontend tests + lint + typecheck; fails on any error. The
  pre-commit hook runs it (plus a secret scan). Never bypass it with `--no-verify`.
- `make dev`    — backend on 127.0.0.1:8000 + frontend on 127.0.0.1:3000
- `make test`   — backend pytest + frontend tests
- `make import FILE=data/personal_investment_tracker_clean.xlsx` — CLI import
- `make refresh` — fetch prices/NAVs and store today's snapshot
- `make backup` / `make migrate` — SQLite backup to data/backups/ / apply Alembic migrations
- `make fundamentals` — fetch fundamentals (yfinance) now
- `make lint` — eslint + tsc; `make test` also runs the frontend formatter tests
- `make logs` / `make logs-errors` — follow `logs/app.log` (all / WARNING and above)
- Backend only: `cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload`
- Frontend only: `cd frontend && npm run dev`
- CLI import: `cd backend && .venv/bin/python -m app.import_excel ../data/<file>.xlsx [--user EMAIL]` (`--dry-run` to preview)
- `make pg-up` / `make test-postgres` / `make test-all-postgres` — local throwaway Postgres for tests (Docker)
- One-time data move: `cd backend && .venv/bin/python -m app.tools.sqlite_to_postgres --sqlite <file>
  --owner-email <you>` (target URL from `TARGET_DATABASE_URL`; refuses a non-empty target; compares totals)

## Working rules
- Work in phases; finish a phase, then stop and summarise for review.
- State assumptions in PLAN.md instead of silently choosing.
- Every financial calculation has a pytest test. Run tests before committing.
- Small commits per milestone. Never commit `.env`, `data/`, `*.db`, `node_modules`, `.venv`.
- No secrets in the repo; keys go in `.env` (template: `.env.example`, which must never hold a
  real value). Tests never read `.env` (autouse fixture in `tests/conftest.py`).
- Never let a command swallow a test result: Make recipes run under `bash -euo pipefail`; don't
  pipe test output through `tail`/`grep` without `pipefail`.

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
- The Import page previews first (`preview_workbook`: a savepoint that is always rolled back) and
  applies only on Confirm with the one-shot token (the file's sha256). Keep preview and apply on
  the same code path.
- No broker/platform adapters, credentials, env vars or reconciliation: removed in Phase 5 by
  decision. Don't reintroduce them.

## Architecture rules
- Multi-user (Phase 6): see "Users and isolation" below. Local dev still binds to 127.0.0.1.
- DB access only through `app/db.py` + `app/repository.py`; switching to Postgres must be a
  `DATABASE_URL` change.
- `app/calc/` holds pure functions (no DB, no network) — that is what tests target.
- Market data sits behind the `PriceProvider` interface; results are cached in `price_quotes`.
  Pages read from the DB; only refresh jobs hit the network.

## Users and isolation (Phase 6)
- Per-user tables inherit `UserOwned` (models.py). Never filter by user_id by hand: sessions carry the user and
  `app/tenancy.py` adds `user_id = :uid` to every ORM SELECT/UPDATE/DELETE (incl. `session.get`) and stamps new rows.
  A session with neither a user nor `system=True` cannot touch per-user tables (fail closed).
- Routes get the user's session from `app/auth.py::get_session`; admin routes use `require_admin` /
  `get_admin_session`. Use `session_scope(system=True)` only for global jobs and admin maintenance.
- Market data is global (securities, price_quotes, intraday_ticks, security_facts, security_sectors, news, macro,
  annual_financials, peer_metrics). Never store anything about a user there, and never show a user global rows
  that reveal another user's holdings (e.g. filter news and refresh results to the user's own securities).
- Core INSERTs on per-user tables go through `repository.insert_ignore` (it stamps the owner).
- `tests/test_isolation.py` attacks EVERY route as another user and must stay green; a new route needs a case
  there (the test fails on uncovered routes). Postgres RLS (migration 0009) is defence in depth.
- Jobs run once globally (`app/jobs.py`, `scheduler.run_job` under `job_lock`); per-user steps loop users with
  `jobs.for_each_user`.
- Auth: Supabase JWT (JWKS/HS256) and the invite list; fail closed: the local fake user needs
  `DEV_AUTH=1` AND `ENV=development|test`; unset/unknown ENV = production; never weaken this.
- Logs carry the numeric user id (`uid=`), never emails, financial figures, workbook contents or journal text.
- Postgres-only behaviour (string lengths, RLS, advisory locks) is tested with `make pg-up && make test-postgres`;
  `make test-all-postgres` runs the whole suite on Postgres.

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

## Outbound requests, news and the LLM
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
  Bump `PROMPT_VERSION` when the prompt or schema changes. Card kinds: stock, fund, portfolio
  (`app/llm/prompts.py::KINDS`); fund and portfolio inputs are built by code only.
- AI is off for non-admin users until the admin enables it per user; caps: the user's own, the admin's per-user
  cap, and a global cap for the platform key (`llm_platform`). Optional own key: Fernet-encrypted, never returned.
- Model id is free text (Settings › llm, then `CLAUDE_MODEL`, then `claude-opus-5-5`). No token
  prices ship with the app (cost is N/A until the admin sets them in llm_platform). Refusal fallback is opt-in
  (default off); cards show the answering model and the requested one when they differ.
- Don't make live LLM calls during development without the user's approval (it costs money).
- The thesis journal is append-only (no update/delete paths).

## Valuation, peers and qualitative notes (Phase 5)
- P/S, PEG, FCF (latest, trend, margin, yield) and interest coverage are pure functions in
  `app/calc/valuation.py`; each N/A carries its reason, and PEG carries its formula and inputs.
- Framework checks (`app/calc/framework.py`) return MEETS / DOES NOT MEET / N/A / NOT APPLICABLE /
  INFO per rule with value and sources. Never add a score, count-based verdict or ranking.
  Thresholds live in Settings › rubric; per-sector "not applicable" metrics in Settings ›
  sector_rules.
- Peers are chosen by the user only (max 8 NSE stocks, never seeded or suggested); label them
  "peers chosen by me". A median needs ≥3 peer values. Peer fetches are rate-limited and cached.
- Own history only from stored annual statements; historical P/E only from a stored price near
  the fiscal year end. Never estimate history.
- Qualitative notes are append-only versions with a source note and as-of date; they reach the
  LLM only with the same per-holding opt-in as the thesis.

## Reliability
- Every fetcher records a source-health event (`app/services/source_health.record`, never raises).
- Start-up catch-up records missed days as `snapshot_gaps`; charts break the line there. Never
  interpolate or back-fill snapshots.
- Parser regression tests use trimmed real responses in `backend/tests/fixtures/` (no personal
  data). Re-record them when a source format changes.

## Logging (app/logging_config.py)
- Use `logging.getLogger("app.<area>")` and `event(log, "name", **fields)` for structured lines; never print().
- Never log secrets, Authorization/x-api-key headers, thesis/qualitative text, LLM prompts or inputs, or
  submitted form values. Log ids, hashes, counts, durations, status and error classes. The redaction filter is a
  backstop, not a licence. `tests/test_logging.py` must stay green.
- Outbound calls go through `app/net/outbound.outbound(...)` (source, host only, status, duration, retries).
- Scheduled work runs through `scheduler.run_job` (start/end/duration/outcome; never raises).
- API errors return `{"detail", "request_id"}`; the UI shows status, message and the request id.
- Smoke tests against a copy of the real DB run with `ANTHROPIC_API_KEY=` (empty): the user's DB may have the AI
  toggle on, and a live call costs money.

## Routes and datetimes
- Type id path params (`{iid:int}`) and register static paths before dynamic ones; `tests/test_routes.py` fails on
  any static path shadowed by an earlier dynamic route.
- Datetime columns use `UTCDateTime` (app/types.py): SQLite stores no zone, so every value is converted to UTC.
- Lazy seeding uses `repository.insert_ignore` (INSERT ... ON CONFLICT DO NOTHING), never check-then-insert, and
  never on a GET.

## Live intraday prices
- Market hours: `app/calc/market_hours.py` (09:15 inclusive – 15:30 exclusive IST, Mon–Fri, minus the user's
  holiday table in Settings › market_holidays, which ships empty; never scrape the NSE list).
- One shared poller for the securities held by any user; it runs only when the market is open and a user with
  Settings › live on was seen recently;
  one batched request per cycle; backoff on failures; manual refresh is the only write outside market hours.
- Real quotes only; never simulate or interpolate. Stale = older than 2 poll intervals; totals use fresh quotes
  only and list what was left out. `intraday_ticks` (14-day retention) never feeds price_quotes, snapshots, XIRR or
  history.

## Settings
- Per-user sections live in `app_settings` (user_id, key); platform sections (`news`, `market_holidays`,
  `live_platform`, `llm_platform`) in `platform_settings`, admin-only writes.
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
