# PLAN — Personal Investment Dashboard

Single-user, local-first portfolio analytics and planning tool for an Indian retail investor.
It **never places orders**. Excel workbook = source of truth for transactions.

Status: Phase 0 (plan + scaffolding) and Phase 1 (import, market data, dashboard, holdings,
allocation/concentration, next-contribution simulator) are built in this round.

---

## 1. Folder structure

```
investments/
├── PLAN.md  CLAUDE.md  README.md  Makefile  .env.example  .gitignore
├── data/                      # git-ignored: Excel input, SQLite DB, download caches
│   ├── personal_investment_tracker_clean.xlsx
│   ├── investments.db
│   └── cache/                 # NAVAll.txt, NSE EQUITY_L.csv, eq_etfseclist.csv
├── backend/
│   ├── pyproject.toml / requirements.txt
│   ├── app/
│   │   ├── main.py            # FastAPI app factory, CORS, scheduler start
│   │   ├── config.py          # pydantic-settings (DATABASE_URL, DATA_DIR, …)
│   │   ├── db.py              # engine/session; the ONLY place that knows the DB URL
│   │   ├── models.py          # SQLAlchemy ORM models
│   │   ├── types.py           # DecimalText column type (exact decimals on SQLite)
│   │   ├── money.py           # paise <-> Decimal, Indian-grouped INR formatting
│   │   ├── repository.py      # data-access layer (all queries live here)
│   │   ├── import_excel.py    # `python -m app.import_excel <path>` CLI entry point
│   │   ├── importer/          # workbook reader, row validation, idempotent upsert, report
│   │   ├── calc/              # pure functions: positions, valuation, allocation,
│   │   │                      #   concentration, xirr, simulator (no DB, no network)
│   │   ├── market/            # PriceProvider interface, yfinance + AMFI providers, refresh service
│   │   ├── resolve/           # ISIN (NSE lists) + AMFI scheme-code matching -> candidates
│   │   ├── services/          # glue: load DB rows -> calc functions -> API DTOs
│   │   ├── api/               # FastAPI routers
│   │   └── scheduler.py       # daily refresh job (APScheduler)
│   └── tests/                 # pytest; financial calcs, importer, idempotency, simulator
└── frontend/                  # Next.js App Router + TS + Tailwind + shadcn/ui + Recharts
    └── src/app/{page.tsx, holdings/stocks, holdings/funds, allocation, simulator, import, mappings}
```

## 2. Database schema (SQLite now; Postgres later is a `DATABASE_URL` change)

Conventions: money is **integer paise** (`*_paise` columns, `BIGINT`). Quantities, unit prices
and NAVs are exact decimals stored via a `DecimalText` type (TEXT on SQLite — SQLite's
NUMERIC is a float internally; on Postgres this can become `NUMERIC`). Fractions (weights,
allocation_percent) are also `DecimalText`. No `user_id` anywhere.

| table | purpose / key columns |
|---|---|
| `instruments` | `id`, `instrument_key` UNIQUE (`EQ:<SYMBOL>` or `MF:<normalised name>`), `asset_type` (STOCK/ETF/MF), `name`, `symbol`, `isin`, `scheme_code`, `exposure` (DOMESTIC/INTERNATIONAL), `category` (e.g. "Nifty 50 index fund", derived from the name, labelled as such), `platform`, timestamps |
| `transactions` | `id`, `instrument_id` FK, `date`, `type` (BUY/SELL/SIP/DIVIDEND/OPENING), `quantity`, `price`, `amount_paise`, `charges_paise`, `platform`, `notes`, `source` (`excel`), `row_key` UNIQUE (idempotency key, see §3.3), `source_file`, `source_row`, `imported_at` |
| `fallback_holdings` | rows of `holdings_fallback` sheet: `instrument_id`, `as_of_date`, `quantity`, `invested_paise`, `monthly_plan_paise`, `sector`, `notes`, `used` (bool: true only if the instrument has no transactions) |
| `monthly_plan_items` | `platform`, `asset_type`, `name`, `monthly_amount_paise`, `allocation_fraction`, `instrument_id` (nullable link for MF rows), `is_bucket` (e.g. "Direct stocks & ETFs") — replaced wholesale on every import |
| `identifier_candidates` | `instrument_id`, `kind` (ISIN/SCHEME_CODE), `value`, `label`, `details` (JSON), `source`, `score`, `status` (PENDING/CONFIRMED/REJECTED), `decided_at`. UNIQUE(`instrument_id`,`kind`,`value`). Confirming copies the value onto `instruments` |
| `price_quotes` | `instrument_id`, `source`, `price`, `previous_close` (nullable), `price_date` (market as-of date), `fetched_at`, `currency`, `source_ref` (e.g. `LT.NS`, scheme code). UNIQUE(`instrument_id`,`source`,`price_date`) — history is retained (feeds Phase 2 snapshots) |
| `import_runs` | `started_at`, `file_name`, `file_sha256`, counts, full `report` JSON |
| `refresh_runs` | `started_at`, `finished_at`, `trigger` (manual/scheduled/startup), per-instrument results JSON |

Phase 2+ tables (designed, **not** created now): `portfolio_snapshots` (date, totals, per-asset
JSON), `change_log`, `emergency_fund`, `projection_scenarios`; Phase 3 `fundamentals`
(value + source + as_of, nullable), `index_constituents`, `fund_portfolio_disclosures`;
Phase 4 `news_items`, `ai_analyses` (input_hash UNIQUE, provider, JSON in/out), `thesis_notes`,
`broker_holdings` (normalised, keyed by ISIN). The ISIN/scheme_code mapping built now is what
lets broker adapters and overlap analysis join later.

Migrations: Phase 1 uses `metadata.create_all`. Alembic is introduced at the start of Phase 2,
before the first schema change to an existing table.

## 3. Import pipeline

1. Read workbook with openpyxl (`data_only=True`). Missing sheet / missing required column →
   fatal entry in the report, nothing written, no crash.
2. `transactions` rows: normalise → validate → classify as **loaded**, **skipped** (empty date;
   reported with row number) or **error** (reported with row number + reason). Warnings
   (e.g. `price × quantity` differs from `amount`) do not block a row.
3. Idempotency: `row_key = sha256(date|type|instrument_key|quantity|price|amount_paise|charges_paise|platform) + "#" + n`,
   where `n` is the occurrence index of that identical row within the file (so two genuinely
   identical SIP rows both load, and re-importing doesn't duplicate them). `notes` are excluded
   from the key and updated in place.
4. Sync semantics: rows whose key is already in the DB are "unchanged"; new keys are inserted;
   Excel-sourced rows no longer present in the file are **removed** — but only when the import
   has zero row errors (otherwise pruning is skipped and the report says so).
5. Post-validation: per-instrument chronological replay; a SELL that exceeds the held quantity
   is an error.
6. `holdings_fallback`: stored, but used only for instruments with **no** transaction rows
   (treated as an OPENING lot dated `as_of_date`).
7. `monthly_plan`: the `TOTAL` row is not stored; it is used to check that the item amounts sum
   to it and that fractions sum to 1 (mismatch = warning).
8. Report is printed by the CLI, returned by the upload API and stored in `import_runs`.

Identifier resolution (separate step, needs network; button on the Mappings screen, also run
after import best-effort):
- **ISIN** for STOCK/ETF: exact symbol match against NSE's `EQUITY_L.csv` and
  `eq_etfseclist.csv`. (yfinance's ISIN lookup is not used — it returned LTIMindtree's ISIN for
  `LT` during testing.)
- **Scheme code** for MF: AMFI `NAVAll.txt`. Detect plan (Direct/Regular) and option
  (Growth ≡ Cumulative vs IDCW) from the Excel name, filter candidates to the same plan/option,
  rank by name similarity, keep top 5.
- Every candidate is PENDING until the user confirms it. Values typed into the Excel
  `isin`/`scheme_code` columns are user-supplied and stored as CONFIRMED (source "Excel").
- MF valuation requires a confirmed scheme code; until then the MF shows "Data unavailable".

## 4. Calculation logic (pure functions in `app/calc`, all Decimal)

**Positions (average-cost method)** — replay transactions per instrument ordered by
(date, OPENING → BUY/SIP → SELL → DIVIDEND, row order):
- OPENING / BUY / SIP: `qty += q`, `cost += amount + charges`.
- SELL: `avg = cost / qty`; `cost_removed = avg × q`; `realised += (amount − charges) − cost_removed`;
  `qty −= q`; `cost −= cost_removed`.
- DIVIDEND: `dividends += amount`.
- `invested = cost` (cost basis of units still held); `avg_cost = cost / qty`.

**Valuation**: `current_value = qty × latest price` (rounded half-up to paise).
`unrealised P&L = current_value − invested`; `P&L % = P&L / invested`. Realised P&L and
dividends are shown separately (both zero today). If an instrument has no price, its value
is "Data unavailable" and it is **excluded** from totals and weights, with the exclusion
stated next to the total. Nothing is estimated from cost.

**Today's change**: `Σ (price − previous_close) × qty` over holdings that have both, for the
same quote. For yfinance, previous close comes from the prior daily bar. AMFI's file only has
the latest NAV, so an MF contributes only once a previous NAV is cached from an earlier
refresh; the UI states which holdings are covered.

**Allocation**: weight = current market value / total portfolio value (never share count).
Asset classes: `Mutual funds` (MF), `Indian stocks` (STOCK), `International ETFs` (ETF with
INTERNATIONAL exposure — MAFANG, HNGSNGBEES; corroborated by NSE's "GLOBAL INDICES" tag),
`Indian ETFs` (other ETFs; none today).

**Concentration** (direct holdings only — MF look-through is Phase 3; the UI says so).
"Direct equity" = Indian stocks (companies). Thresholds live in `app/calc/concentration.py`
and are returned by the API and shown in the UI. Level rule: `LOW` if v < low,
`MODERATE` if low ≤ v < high, `HIGH` if v ≥ high.

| metric | low | high |
|---|---|---|
| Largest company, % of direct equity | 15% | 25% |
| Top 3 companies, % of direct equity | 40% | 60% |
| HHI of direct-equity weights (Σ w² × 10,000) | 1,500 | 2,500 |
| Largest company, % of total portfolio | 5% | 10% |

Each flag carries `level`, `reason` (e.g. "LT is 37.8% of direct equity") and `calculation`
(e.g. "3,693.40 / 9,770.15 = 37.8%; HIGH because ≥ 25%").

**XIRR**: cash flows = BUY/SIP (−(amount+charges)), SELL (+(amount−charges)), DIVIDEND (+),
plus terminal value (+) at the valuation date. **OPENING rows are excluded**, and so are the
units they contributed: the replay tracks opening vs dated units, SELLs reduce both pro-rata
(consistent with average cost), and only the dated portion of SELL proceeds and of the
terminal value enters XIRR. If an instrument has no BUY/SIP row → "N/A (needs dated
transactions)". Solver: Newton–Raphson with bisection fallback on [−99.99%, 10,000%];
day count Actual/365 (Excel-compatible). Today every row is OPENING, so all XIRRs are N/A.

**Next Contribution simulator**: input amount (presets 500/1,000/2,000/4,000/10,000 or custom).
Scenarios: add to each MF; split across MFs in `monthly_plan` proportions (0.15:0.15:0.10 →
37.5/37.5/25%); add to any existing stock/ETF (selectable). Assumptions (shown in UI): prices
unchanged at the latest cached quote, no charges, MF units fractional, **stocks/ETFs whole
shares only** (unspent remainder shown; if the amount is below one share, the scenario says so).
Output per scenario: BEFORE → AFTER for asset-class weights, MF split (% of MF total), top
company weights (% of total portfolio), plus neutral sentences such as "Adding ₹1,000 here
would raise your Nifty 50 index fund exposure from 11.2% to 15.6%." Never "buy X".

**Money formatting**: Indian grouping `1,23,456.00`, implemented in Python (`money.py`) and
TypeScript (`lib/format.ts`), both tested/identical.

## 5. Market data

- `PriceProvider` protocol: `name`, `fetch(instruments) -> {instrument_id: Quote | FetchError}`.
- `YFinanceProvider`: `SYMBOL.NS`, daily bars for the last ~7 days; latest bar = price,
  prior bar = previous close; zero-volume phantom bars (holidays) are dropped. Per-ticker
  try/except; one failure never aborts the refresh.
- `AmfiNavProvider`: downloads `NAVAll.txt` (follows the redirect to portal.amfiindia.com),
  parses both the 8-column and the legacy 6-column layouts, looks up confirmed scheme codes.
- Results go to `price_quotes`; pages read only from the DB. Each number shows source + as-of.
- Refresh: `POST /api/market/refresh` (button), daily APScheduler job (default 23:30 IST,
  after AMFI publishes; configurable), and on startup if the newest quote is > 18 h old.

## 6. API (FastAPI, bound to 127.0.0.1:8000, all under `/api`)

| method | path | purpose |
|---|---|---|
| GET | `/health` | liveness |
| POST | `/import` | multipart Excel upload → import report |
| GET | `/import/runs` | import history |
| GET | `/mappings` | instruments + identifier candidates |
| POST | `/mappings/resolve` | fetch NSE/AMFI lists, (re)generate candidates |
| POST | `/mappings/candidates/{id}/confirm` · `/reject` | decide a candidate |
| POST | `/market/refresh` · GET `/market/status` | refresh prices / last run |
| GET | `/portfolio/summary` | dashboard numbers |
| GET | `/holdings` | stocks/ETFs and MF tables |
| GET | `/allocation` | asset classes, companies, HHI, flags + thresholds |
| GET | `/plan` | monthly plan |
| GET | `/transactions` | raw transactions |
| GET | `/simulator/options` · POST `/simulator` | scenarios before → after |

Money fields are integers in paise (`*_paise`); prices/quantities/weights are decimal strings.

## 7. Frontend pages

Dark, minimal, responsive; sidebar on desktop, top bar on mobile; no decorative animation.
`/` Dashboard · `/holdings/stocks` · `/holdings/funds` · `/allocation` · `/simulator` ·
`/import` (upload + report + history) · `/mappings` (confirmation screen). Next.js rewrites
`/api/*` to the backend, so there is no CORS and the backend stays on 127.0.0.1. Footer
disclaimer on every page.

## 8. Assumptions (explicit)

1. **Python 3.14** is the only interpreter on this machine; code targets 3.12+ and avoids
   3.13/3.14-only features.
2. `amount` is authoritative; `price` is informational. MF opening rows have
   `price × units ≠ amount` by a few paise — a warning is raised only above max(₹1, 0.5%).
3. Charges add to cost on purchases and reduce proceeds on sales.
4. "Total P&L" on the dashboard = unrealised P&L on current holdings; realised P&L and
   dividends are shown separately.
5. The Excel `notes` column is not part of a row's identity.
6. Instruments are identified by NSE symbol (stocks/ETFs) or normalised fund name (MF).
7. The `monthly_plan` "Direct stocks & ETFs" row is a bucket, not an instrument.
8. Company concentration uses direct stock holdings only; ETFs are not companies; MF
   look-through is Phase 3.
9. MAFANG and HNGSNGBEES are International exposure (per spec, corroborated by NSE).
10. Fund "category" labels (e.g. "Nifty 50 index fund") are derived from the fund name by
    keyword rules and labelled as derived; they are not market data.
11. yfinance data may be delayed; the as-of shown is the bar date plus fetch time.
12. Today's date is 2026-10-03, the same as the OPENING rows, so P&L reflects the move from
    the opening prices to the latest close.

## 9. Phases

- **Phase 0** (this round): plan, repo scaffolding, conventions.
- **Phase 1** (this round): §3–§7.
- **Phase 2**: Alembic; daily `portfolio_snapshots` + growth chart; monthly contribution
  planner; 5/10-year projection labelled "mathematical scenario" with assumptions; emergency
  fund (separate from portfolio); change log; XIRR as dated SIP rows arrive.
- **Phase 3**: sector exposure, fundamentals (N/A without a reliable source), MF-vs-direct
  overlap from AMC disclosures / index weights, portfolio-health flags.
- **Phase 4**: news/announcements, AI scenario analysis (LLM behind an interface, JSON in/out,
  cached by input hash), thesis journal, read-only `BrokerAdapter`s (Groww, Kite) returning
  holdings keyed by ISIN.
