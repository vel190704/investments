# PLAN — Personal Investment Dashboard

Single-user, local-first portfolio analytics and planning tool for an Indian retail investor.
It **never places orders**. Excel workbook = source of truth for transactions.

Status: Phase 0 and Phase 1 done. Phase 2 (§10) in progress: migrations, in-app transactions,
snapshots, XIRR, settings, drift, planner, projections, emergency fund, change log.

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
12. Displayed percentages are rounded half-up everywhere (so the same weight reads the same on
    every page); rounded figures may not add to exactly 100.0%. Calculations use exact fractions.
13. NSE prices from yfinance are rounded to 2 decimals (yfinance returns float artefacts such
    as 3693.3999).
14. Today's date is 2026-10-03, the same as the OPENING rows, so P&L reflects the move from
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


---

## 10. Phase 2 design

### 10.1 Migrations (first)
- Alembic in `backend/migrations/`, `render_as_batch=True` (SQLite ALTER support).
  `0001_baseline` reproduces the Phase 1 schema exactly (autogenerated from the Phase 1 models
  against an empty DB, so it equals what `create_all` produced).
- `init_db()` now runs migrations instead of `create_all`:
  - An existing DB with Phase 1 tables but no `alembic_version` is **stamped** `0001_baseline`
    first, then upgraded.
  - An empty DB is upgraded from scratch.
- Before applying any pending migration to a file DB, a backup is written to
  `data/backups/investments-<UTC timestamp>-pre-<revision>.db`, using SQLite's online backup
  API so WAL contents are included.
- `make backup` writes an ad-hoc backup; `make migrate` applies migrations explicitly.
- Tests:
  - every test DB is built through migrations (the production path);
  - a test checks the models and migrations have no drift (alembic `compare_metadata`);
  - a test migrates a Phase-1-shaped DB with data and checks the data is preserved, and also
    runs against a copy of `data/investments.db` when present.

### 10.2 Schema changes (`0002_phase2`)
| table | change |
|---|---|
| `transactions` | `source` constrained to `excel` / `ui` (CHECK). UI rows get `row_key = "ui:<uuid>"`. |
| `portfolio_snapshots` (new) | `id`, `snapshot_date` UNIQUE, `total_value_paise` (priced holdings), `total_invested_paise` (all open holdings), `invested_priced_paise`, `unpriced` (JSON list of names), `trigger`, `created_at`, `updated_at` |
| `snapshot_asset_classes` (new) | `snapshot_id` FK (cascade), `asset_class`, `value_paise`, `invested_paise` |
| `snapshot_holdings` (new) | `snapshot_id` FK (cascade), `instrument_id`, `quantity`, `avg_cost`, `invested_paise`, `price` (nullable), `price_date`, `price_source`, `value_paise` (nullable) |
| `app_settings` (new) | `key` PK, `value` JSON, `updated_at` — one row per settings section |
| `change_log` (new) | `id`, `occurred_at`, `kind`, `instrument_id` (nullable), `snapshot_date` (nullable), `cause` (`import`/`ui`/`snapshot`), `summary`, `details` JSON |

### 10.3 Transaction provenance and in-app entry
- **Re-import:**
  - deletes only `source='excel'` rows that are missing from the file, and only when the file
    has zero row errors (unchanged from Phase 1);
  - never touches `ui` rows, snapshots, settings or the change log.
- **Excel rows that duplicate a UI row:** an Excel row whose identity (date, type,
  instrument, quantity, price, amount, charges, platform) equals an existing UI row is
  reported as "already present as an in-app entry" and not inserted. Identical rows are
  counted one-for-one. The UI row is never converted or deleted, so exporting and re-importing
  never duplicates, and importing an older file never loses an in-app entry.
- **Oversell check on import:** SELL rows are checked against Excel + UI rows together.
- **Add transaction** (`POST /api/transactions`):
  - Types: BUY, SELL, SIP, DIVIDEND. OPENING stays Excel-only.
  - Validated by the same `parse_txn` rules as the Excel importer, plus an oversell check
    against the current position.
  - The instrument is an existing one or a new one (asset type, name, NSE symbol for stocks).
  - MF: units + NAV + amount; amount is authoritative, and a price × units mismatch is a warning.
- **Delete:** only `ui` rows can be deleted in-app (`DELETE /api/transactions/{id}`). Excel rows
  are managed in the file.
- **Export** (`GET /api/export.xlsx`):
  - Writes sheets `README`, `transactions`, `holdings_fallback` and `monthly_plan` in the exact
    input layout and column order; dates are `YYYY-MM-DD` text, money is in rupees.
  - `transactions` contains all rows, Excel and UI.
  - `monthly_plan` has a `TOTAL` row.
  - Round trip is tested: exporting and re-importing into the same DB inserts 0 rows; importing
    into an empty DB gives identical positions.

### 10.4 Snapshots and growth
- `take_snapshot(date=today IST)` upserts one snapshot per date (children rewritten).
- It runs after every price refresh (manual, scheduled, start-up), from the "Take snapshot"
  button, and once on start-up when no snapshot exists ("first snapshot of Phase 2").
- The snapshot date is the IST calendar date of valuation. Each holding row keeps its own
  price date and source.
- Growth chart: value vs invested by snapshot date.
  - With fewer than 2 snapshots it shows "History builds from today"; nothing is back-filled
    or estimated.
  - Snapshots where some holdings were unpriced are marked as partial.

### 10.5 XIRR
- Per instrument, per asset class and whole portfolio, from dated BUY/SIP/SELL/DIVIDEND rows
  only. OPENING rows and their units are excluded (Phase 1 method). Closed positions count in
  class and portfolio XIRR.
- Every N/A has a reason:
  - "N/A (needs dated transactions)" — only OPENING rows;
  - "N/A (only one cash flow)";
  - "N/A (all cash flows on the same day)";
  - "N/A (cash flows do not change sign)";
  - "N/A (did not converge)";
  - "N/A (price unavailable)".
- Reference tests: Microsoft's documented example, plus exact constructed cases (10% over
  730 days; two annual flows at 10%).

### 10.6 Settings (`GET/PUT /api/settings`, stored in `app_settings`)
| section | contents | default |
|---|---|---|
| `targets` | % per class: Mutual funds, Indian stocks, International ETFs, Gold, Debt/Cash; must total exactly 100 | **none** — drift and planner show "Set your targets" |
| `drift` | tolerance band, percentage points | 5 |
| `concentration` | low/high per threshold key | the Phase 1 constants |
| `projection` | Conservative / Base / Higher annual rates, default years, default step-up, `reviewed` flag | **placeholders** 6% / 9% / 12%, 10 years, 0%, `reviewed=false` (UI asks you to review) |
| `emergency_fund` | monthly essential expenses, current balance, target months (3–6) | **none** — empty state |

- The monthly budget and split always come from `monthly_plan`. A planner budget override is
  per-page and temporary, never saved to the file.

### 10.7 Allocation drift
For each target class:
- **current %** = value / total portfolio value (priced holdings);
- **target %**;
- **deviation** = current − target, in percentage points;
- **value difference vs target** = current value − target % × total.

Status: OVERWEIGHT if deviation > +tolerance, UNDERWEIGHT if < −tolerance, otherwise
WITHIN BAND. Each status shows its reason and calculation. Charts: a 100% stacked bar
(current vs target) and a diverging deviation bar chart with the tolerance band shaded.
"Indian ETFs" (none held) are folded into Indian stocks for drift.

### 10.8 Monthly contribution planner (`POST /api/planner`)
- **Budget:** presets 6k / 8k / 10k / 15k / 20k / custom; the default is the `monthly_plan` total.
- **(a) Plan proportions:** the budget is split by `monthly_plan` fractions.
  - MF rows go to their funds.
  - The "Direct stocks & ETFs" bucket is either split equally across stocks/ETFs the user picks
    (whole shares only, remainder uninvested), or, if none are picked, held at class level and
    attributed to Indian stocks / International ETFs pro rata to their current values (stated
    assumption; company weights are then only diluted).
- **(b) Targets** (only when targets are set): contribution-only rebalancing.
  - `desired_c = target_c × (total + budget)`, `gap_c = max(0, desired_c − current_c)`.
  - If Σgap ≥ budget, the budget is split pro rata to the gaps; otherwise each gap is filled and
    the remainder is split by target weights.
  - Within Mutual funds, money is split by the `monthly_plan` MF proportions.
  - Gold / Debt/Cash amounts are shown at class level ("not held").
- **Output per mode:**
  - per class: current → +contribution → projected %;
  - per MF: projected % of MF total;
  - "Allocation consideration" flags with reasons: over/underweight vs targets after the
    contribution, single-company weight vs the concentration thresholds, international and
    thematic exposure.
- Thematic descriptions are a static map of what each index covers (MAFANG = 10-stock US
  technology-focused NYSE FANG+ index; HNGSNGBEES = single-market Hang Seng index). They are
  descriptions, not market data. Nothing is executed, and nothing is phrased as an order.

### 10.9 Projection calculator (`POST /api/projection`) — mathematical scenarios
- Monthly rate `r = (1 + R)^(1/12) − 1`, so R is an effective annual rate.
- Contributions are made at the end of each month. The monthly contribution rises by the
  step-up % at the start of each new year.
- Formula shown: `FV = P(1+r)^n + Σ_{k=1..n} C_k (1+r)^(n−k)`; with no step-up,
  `FV = P(1+r)^n + C((1+r)^n − 1)/r` (`C·n` when r = 0).
- Output: total contributions, growth, ending value, and a yearly series per scenario
  (Conservative / Base / Higher plus an optional custom rate) with a chart.
- Wording: "If the portfolio averaged X% annually and contributions were Y, the mathematical
  future value would be approximately Z." Real (inflation-adjusted) values are not shown;
  that is stated.

### 10.10 Emergency fund (separate)
- target = monthly expenses × months; % complete = balance / target;
  remaining = max(0, target − balance).
- Stored only in settings. It is never read by portfolio, holdings, allocation, XIRR,
  snapshots or the planner; a test asserts every portfolio endpoint is identical before and
  after setting it.

### 10.11 Change log
Recorded entries:
- `TXN_ADDED` / `TXN_REMOVED` — import inserts or prunes, UI adds or deletes;
- `QTY_CHANGED` / `AVG_COST_CHANGED` — position before vs after each import or UI change, per
  instrument;
- `ALLOCATION_CHANGED` — per asset class vs the previous snapshot; written at snapshot time and
  rewritten when that date's snapshot is upserted; changes under 0.1 pp are ignored.

Compare (`GET /api/compare?a=<date>&b=<date|live>`): per instrument (quantity, avg cost,
value, weight, added/removed) and per asset class (value, weight).

### 10.12 Other
- "Asset classes not held" panel on Allocation (Gold, Debt/Cash): a static description of the
  role each can play — information, not a recommendation.
- Every analysis page keeps the disclaimer footer.

### 10.13 New endpoints
`GET /instruments` · `POST /transactions` · `DELETE /transactions/{id}` · `GET /export.xlsx` ·
`GET /snapshots` · `POST /snapshots` · `GET /snapshots/series` · `GET /compare` ·
`GET /changes` · `GET /xirr` · `GET/PUT /settings` · `POST /planner` · `POST /projection` ·
`GET /emergency-fund`; `GET /allocation` gains `drift`.

### 10.14 New pages
`/transactions` (list, add, delete UI rows, export) · `/history` (growth chart, snapshots,
take snapshot) · `/changes` (change log + compare) · `/planner` · `/projection` ·
`/emergency-fund` · `/settings`. The Allocation page gains drift, XIRR by class and the "not
held" panel. The nav is grouped (Overview / Holdings / Analysis / Planning / Data).

### 10.15 Phase 2 assumptions
1. Snapshot date = IST calendar date of valuation (a Saturday snapshot carries Friday closes,
   shown per holding).
2. A partial snapshot (some holdings unpriced) is stored and marked partial, not dropped.
3. Projections use effective annual rates, end-of-month contributions and an annual step-up,
   in nominal rupees.
4. Placeholder projection rates (6/9/12%) are illustrative inputs only, flagged until you
   review them.
5. Planner mode (b) only directs new money; it never assumes selling.
6. The "Direct stocks & ETFs" bucket has no instrument split in `monthly_plan` (see §10.8).
7. Target classes are the five you listed; "Indian ETFs" are folded into Indian stocks for
   drift until a gold/debt classification exists (Phase 3 can classify ETFs by underlying).
