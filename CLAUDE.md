# CLAUDE.md — conventions for this repo

Personal, single-user, local-first investment **analytics** dashboard (Indian retail investor).
It never places orders. See PLAN.md for the design and README.md for usage.

## Commands
- `make setup`  — create `backend/.venv`, install Python deps, `npm install` in frontend
- `make dev`    — backend on 127.0.0.1:8000 + frontend on 127.0.0.1:3000
- `make test`   — `pytest` in backend
- `make import FILE=data/personal_investment_tracker_clean.xlsx` — CLI import
- Backend only: `cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload`
- Frontend only: `cd frontend && npm run dev`
- CLI import: `cd backend && .venv/bin/python -m app.import_excel ../data/<file>.xlsx`

## Working rules
- Work in phases; finish a phase, then stop and summarise for review.
- State assumptions in PLAN.md instead of silently choosing.
- Every financial calculation has a pytest test. Run tests before committing.
- Small commits per milestone. Never commit `.env`, `data/`, `*.db`, `node_modules`, `.venv`.
- No secrets in the repo; keys go in `.env` (template: `.env.example`).

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

## Language and safety
- Neutral wording: "Adding ₹1,000 here would raise X from a% to b%". Never "buy/sell X".
- Suggestions are labelled "Allocation consideration". No return guarantees or price
  predictions. Projections are "mathematical scenario" with assumptions shown.
- Show the date of all data; separate historical data from assumptions.
- Footer disclaimer: personal analytics tool, not investment advice.

## Style
- Python 3.12+ compatible (machine has 3.14), type hints, FastAPI + SQLAlchemy 2.x style.
- Frontend: Next.js App Router, TypeScript strict, Tailwind, shadcn/ui components in
  `src/components/ui`, Recharts for charts. Dark mode default, no decorative animation.
