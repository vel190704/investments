# PLAN — Personal Investment Dashboard

Single-user, local-first portfolio analytics and planning tool for an Indian retail investor.
It **never places orders**. Excel workbook = source of truth for transactions.

Status: Phases 0–4 done (§10 = Phase 2, §11 = Phase 3, §12 = Phase 4). Phase 5 (§13) in progress:
Excel-only workflow, hygiene, valuation framework, peers, qualitative notes, fund/portfolio AI cards, reliability.

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
8. XIRR treats a dividend paid after a full sale as an inflow, attributed by the dated share at
   the time of sale.
9. After an import, an Excel row's `source_row` refers to the most recently imported file.


---

## 11. Phase 3 design

### 11.1 Data sources (checked 2026-10-03)
| need | source | reliability / decision |
|---|---|---|
| Stock sector | NSE index constituent CSVs (`ind_niftytotalmarket_list.csv` — 750 stocks, `ind_niftymicrocap250_list.csv`), column **Industry**, keyed by ISIN | Official, the same approach as the ISIN lists. Stocks in neither list are "Unclassified" until a manual sector is set (MOSCHIP today). |
| ETF asset class / region | NSE `eq_etfseclist.csv`: `ETF Underlying` (EQUITY / COMMODITY / DEBT / GLOBAL INDICES) + `Underlying Key` (GOLD, SILVER, …) + `Underlying Asset` | Official. Region for global indices is a small code map of the index named by NSE (Hang Seng → Hong Kong/China; NYSE FANG+, Nasdaq 100 → US technology-heavy); unknown global index → "International (region not classified)". |
| MF category | AMFI `NAVAll.txt` section header above the scheme (e.g. "Equity Scheme - Mid Cap Fund") | Parsed reliably. |
| Expense ratio, exit load, tracking error, tracking difference | AMFI's TER and tracking-error pages are client-rendered (no stable file); `TER.txt` is a 404 | **Manual entry** with a required source note + as-of date; N/A otherwise. No scraping. |
| Fundamentals | yfinance `Ticker.info`: marketCap, trailingPE, returnOnEquity, debtToEquity (Yahoo gives a percentage: 97.64 = 0.98×), revenueGrowth, earningsGrowth, beta, mostRecentQuarter | Used only when present **and** inside plausibility bounds; otherwise "N/A (not provided by source)" or "N/A (implausible value rejected: …)". |
| ROCE, promoter holding, alpha | none reliable and free | "N/A (no reliable source)" + manual entry (source note + as-of required, tagged "manual"). |
| Fund holdings | **Upload** of the AMC monthly portfolio disclosure (xlsx/csv) | Parsers for HDFC, ICICI Prudential and Kotak layouts; an unknown layout fails with a clear error. |
| Index weights (Nifty 50 / Next 50) | NSE constituent CSVs have **no weights**; weights live in PDF factsheets | **Upload only** (CSV: ISIN, weight). Labelled "approximated from index weights, as of <date>". |

### 11.2 Classification and asset classes
- New asset classes: **Gold**, **Debt/Cash**, **Other commodities** (silver etc.), alongside
  Mutual funds, Indian stocks, International ETFs and Indian ETFs.
- Effective asset class, in order:
  1. a manual asset-class override (Classification page);
  2. ETFs by NSE underlying: GOLD → Gold; other COMMODITY → Other commodities;
     DEBT → Debt/Cash; GLOBAL INDICES → International ETFs; EQUITY → Indian ETFs;
  3. the Phase 1 rule (MF → Mutual funds, STOCK → Indian stocks, ETF with
     `exposure=INTERNATIONAL` → International ETFs).
- Existing data keeps its classes: MAFANG and HNGSNGBEES stay International ETFs through
  either rule; the migration only adds nullable columns.
- Drift: Gold and Debt/Cash now carry real values. Indian ETFs fold into Indian stocks;
  Other commodities has no target class and is listed as "no target" with its weight.
- Sector, effective in priority order: **manual (app) > Excel `holdings_fallback.sector` >
  NSE**. Each assignment stores origin, source and as-of; overrides are tagged "manual".
- Region / geography: India for domestic holdings; for international ETFs the NSE-derived
  region, which can be overridden manually.

### 11.3 Schema changes (`0003_phase3`)
| table | change |
|---|---|
| `instruments` | + `asset_class_override`, + `etf_underlying` (NSE ETF Underlying), + `etf_underlying_key`, + `region` (nullable) |
| `sector_assignments` (new) | `instrument_id`, `origin` (NSE / EXCEL / MANUAL), `sector`, `source`, `as_of`, `note`; UNIQUE(instrument_id, origin) |
| `instrument_facts` (new) | `instrument_id`, `metric`, `origin` (AUTO / MANUAL), `value` (DecimalText, nullable), `value_text`, `source`, `as_of`, `fetched_at`, `note`, `status` (OK / MISSING / REJECTED); UNIQUE(instrument_id, metric, origin) |
| `fund_disclosures` (new) | `instrument_id` (fund), `kind` (AMC_DISCLOSURE / INDEX_WEIGHTS), `as_of`, `index_name`, `parser`, `source_file`, `file_sha256`, `uploaded_at`, `equity_weight`, `rows`; UNIQUE(instrument_id, kind, as_of) — re-uploading the same month replaces it, earlier months are kept |
| `disclosure_holdings` (new) | `disclosure_id` (cascade), `isin` (nullable), `name`, `industry`, `weight` (fraction of NAV), `is_equity` |

Settings sections added: `sector_ranges` (desired min/max % per sector, **no defaults**),
`themes` (user tags → company ISINs, **no defaults**), `health` (thresholds; defaults =
the values in code).

### 11.4 Fundamentals and fund facts
- Stocks: price (latest cached quote), market cap, P/E, ROE, D/E, revenue growth, profit
  growth, beta (yfinance) and ROCE, promoter holding, alpha (manual only).
- Each value carries its source and as-of: the fetch time, plus "latest reported quarter"
  when Yahoo gives `mostRecentQuarter`.
- Plausibility bounds live in `app/calc/fundamentals.py`; a value outside them is rejected and
  shown as N/A with the reason. Nothing is filled in or estimated.
- "Within my portfolio" sector median: shown when at least 3 *other* direct holdings in the
  same sector have that metric, otherwise omitted. Never labelled "industry".
- Funds: category (AMFI) and expense ratio, exit load, tracking error, tracking difference
  (manual). Tracking metrics apply only to index funds; other funds show "Not applicable".
- Manual entries need a value inside the plausibility bounds, a non-empty source note, and an
  as-of date that is not in the future. They are stored per metric and can be deleted.

### 11.5 Look-through and overlap (`app/calc/lookthrough.py`, pure)
- Fund holdings come from the newest disclosure per fund; if an AMC disclosure and index
  weights share an as-of date, the AMC disclosure wins. The label says which, and the as-of.
- Weights are normalised to fractions: a file whose % column sums to more than 1.5 is in
  percent.
- Companies are matched **by ISIN only**:
  - equity ISINs are `IN?…` with security code `01` at positions 8–9;
  - a direct stock without a confirmed ISIN cannot be combined, and is listed as such.
- Exposure per company:
  - `direct_value + Σ_f fund_value_f × weight_{f,company}`;
  - shown as direct %, indirect % per fund and total % of total portfolio value.
- Notable exposure thresholds (in code, shown in the UI, editable in Settings › health):
  total % of portfolio, LOW < 5%, MODERATE 5–10%, HIGH ≥ 10%.
- Coverage is stated: the equity weight covered by each disclosure, and funds with no
  disclosure are listed as "not looked through".
- Pairwise fund overlap = Σ_isin min(w_A, w_B) over common holdings, with that list.
- Stale warning when a disclosure's as-of is more than 2 calendar months before today.
- Sector look-through: a fund holding's sector comes from the NSE classification of its
  ISIN when available, otherwise the AMC's industry label (marked "AMC label").

### 11.6 AMC parsers (`app/disclosures/`)
- One shared engine: find the header row (an ISIN column plus a % of NAV column, using the
  aliases for each AMC), read rows with a valid ISIN or a name, find the as-of date in the top
  rows ("as on …" in several date formats), and choose the sheet whose title matches the
  fund.
- HDFC, ICICI Prudential and Kotak each have their own aliases, sheet rules and AMC
  detection. A generic CSV layout (`isin, name, weight[, industry]`) serves index weights and
  hand-made files.
- Unknown layouts raise `DisclosureFormatError`, which lists the columns looked for and the
  first rows found. Nothing partial is stored.
- Tests use small synthetic workbooks built in code (no real downloads).

### 11.7 Portfolio Health (`app/calc/health.py`)
There is no overall score and no ranking; each dimension stands alone. LOW / MODERATE / HIGH
appears only where a threshold exists in code:
| dimension | metric | level |
|---|---|---|
| Company concentration (look-through) | largest company total % of portfolio | 5% / 10% |
| Sector concentration | largest sector % of equity exposure (look-through) + HHI shown | 25% / 40% |
| Asset allocation drift | largest abs. deviation vs targets | ≤ tolerance LOW, ≤ 2× MODERATE, else HIGH; needs targets |
| Fund overlap | largest pairwise overlap | 30% / 50% |
| International exposure | international % of portfolio | information only (no objective threshold) |
| Liquidity | direct equity vs fund share | information only |
| Volatility exposure | value-weighted annualised volatility from ≥ 60 stored daily quotes per holding | information only; N/A until enough history |
| Emergency fund coverage | balance ÷ target | ≥ 100% LOW, 50–100% MODERATE, < 50% HIGH; only if entered |

### 11.8 Simulator upgrade
Each scenario also reports BEFORE → AFTER **total (direct + indirect) exposure** for the top
companies and the top sectors, using the same look-through inputs. The wording stays neutral
("Allocation consideration: LT's total exposure would go from X% to Y%").

### 11.9 Endpoints
- `GET /classification` · `PUT /instruments/{id}/classification` · `DELETE …/classification/{field}`
- `POST /sectors/refresh` · `GET /sectors`
- `GET /fundamentals` · `POST /fundamentals/refresh` · `PUT /facts/{instrument_id}/{metric}` ·
  `DELETE /facts/{instrument_id}/{metric}`
- `POST /disclosures` (upload) · `GET /disclosures` · `DELETE /disclosures/{id}`
- `GET /lookthrough` · `GET /overlap` · `GET /health-check` (Portfolio Health; `/health` stays the liveness probe)
- the simulator response gains `lookthrough`

### 11.10 Pages
- `/sectors`: sector table, desired ranges, geography, themes, flags.
- `/fundamentals`: stocks and fund facts, with manual entry.
- `/overlap`: upload, look-through table, pairwise overlap, stale warnings.
- `/health`
- `/classification`: asset-class, sector and region overrides; linked from Settings.
- Settings gains sector ranges, themes and the health threshold editor.

### 11.11 Phase 3 assumptions
1. NSE's index-list "Industry" is the official sector taxonomy used here; it is broad
   (e.g. "Construction", "Financial Services").
2. Index weights are an approximation of an index fund's holdings; tracking difference
   (manual) is shown next to them.
3. Look-through uses each fund's latest disclosure regardless of age; staleness is flagged,
   not hidden.
4. Debt/cash rows inside funds are not companies; they count toward the fund's non-equity
   weight.
5. Volatility uses only quotes stored by this app (no downloaded history), so it stays N/A
   for about the first three months.
6. "Liquidity" is the simple share split requested, not a market-liquidity measure.
7. Classifications refresh with the daily job (official lists are cached for 7 days); fundamentals
   refresh on Sundays and on demand.
8. The AMC column aliases come from the published column names of each AMC's monthly portfolio
   file and are verified on synthetic fixtures only. A real file whose headers differ fails with
   an error that shows the header row it found, so an alias can be added.


---

## 12. Phase 4 design

### 12.1 Data sources (checked 2026-10-17)
| need | source | finding / decision |
|---|---|---|
| Company news via **Google News RSS** (requested) | `news.google.com/rss/search` | **robots.txt disallows `/rss` for every user agent** (`Disallow: /` with exceptions only for home/topics/stories). Per the "respect robots/terms" rule the source is implemented but every fetch is refused by the robots guard and the holding shows **"Source unavailable (robots.txt disallows …)"**. It is not worked around. |
| Exchange announcements | NSE's official RSS feeds on `nsearchives.nseindia.com/content/RSS/` (`Online_announcements.xml`, `Board_Meetings.xml`, `Financial_Results.xml`, `Corporate_action.xml`), published for feed readers; no robots.txt (404 = allowed) | Used. Each item's link starts with the NSE symbol (`LT_17102026…pdf`) → matched by symbol, stored by ISIN. Only a rolling window of recent items is published, so history builds from the first fetch. |
| BSE announcements | `api.bseindia.com` returns 403 to non-browser clients | Not used ("Source unavailable"); no evasion. |
| Market news | Publisher RSS feeds whose robots.txt allows the feed URL. **Default: ET Markets, Mint Markets.** Business Standard and Moneycontrol answered **HTTP 403 to `robots.txt`** for this tool's identifying User-Agent during the live test (2026-10-17), which the guard treats as "not permitted"; they are not in the defaults and are not worked around (no UA spoofing) | Feed list editable in Settings; the guard reports each feed's status. Items are matched to holdings by exact company-name phrase or upper-case NSE symbol (≥ 3 letters) in the headline. This is relevance matching for a news feed only; financial calculations still match by ISIN. |
| USD/INR, Brent, Nifty 50 | yfinance `INR=X`, `BZ=F`, `^NSEI` | Automated; source + as-of shown; N/A on failure. |
| Repo rate, CPI and others | none reliable | **Manual** entry with source note + as-of; N/A otherwise. Never filled from memory. |
| Groww holdings | Official Groww Trade API: `POST /v1/token/api/access` (`key_type: totp`) → token (expires daily); `GET /v1/holdings/user` (`X-API-VERSION: 1.0`) | Read-only adapter behind `GROWW_ENABLED`; secrets only in `.env`. |
| LLM | Anthropic Messages API (`anthropic` SDK), default model `claude-opus-5-5`, structured outputs (`output_config.format` JSON schema), server-side refusal fallbacks (`fallbacks: "default"`) | Off unless an API key is set **and** the privacy toggle allows outbound calls. |

Polite fetching (`app/net/polite.py`):
- one shared client with a clear User-Agent (`personal-portfolio-dashboard/0.4 (single-user, local)`);
- a robots.txt check per URL, with robots files cached for 24 h;
- at least 2 s between requests to the same host;
- feed responses cached for 30 min;
- after a network failure (e.g. a timeout) the host is skipped for 10 min, so one slow server
  doesn't stall the whole refresh;
- no retries on 401/403/429 ("Source unavailable").

### 12.2 Schema (`0004_phase4`)
| table | columns |
|---|---|
| `news_items` | `id`, `isin` (indexed), `instrument_id` (nullable), `title`, `source`, `source_kind` (EXCHANGE / NEWS), `url` UNIQUE, `published_at`, `fetched_at`, `category`, `category_origin` (RULE / MODEL), `summary` (source text only), `dedupe_key` |
| `news_source_status` | `source`, `isin` (nullable), `ok`, `message`, `checked_at`; UNIQUE(source, isin) |
| `macro_values` | `key`, `origin` (AUTO / MANUAL), `value`, `unit`, `source`, `as_of`, `fetched_at`, `status`, `note`; UNIQUE(key, origin) |
| `sector_sensitivities` | `sector` PK, `tags` JSON, `origin` (STARTER / USER), `note`, `updated_at` |
| `llm_analyses` | `id`, `instrument_id`, `input_hash` (indexed), `input_json`, `output_json`, `status` (OK / FAILED), `errors` JSON, `model`, `prompt_version`, `data_as_of`, `created_at`, `attempts`, `input_tokens`, `output_tokens` |
| `llm_calls` | `id`, `purpose` (analysis / category), `model`, `created_at`, `input_tokens`, `output_tokens`, `ok`, `error` |
| `thesis_entries` | `id`, `instrument_id`, `version`, `why`, `change_view`, `horizon`, `review_date`, `created_at`, `linked_txn_ids` JSON, `linked_change_ids` JSON; UNIQUE(instrument_id, version) — **append-only** |
| `thesis_optin` | `instrument_id` PK, `send_to_llm`, `updated_at` |
| `alerts` | `id`, `rule`, `dedupe_key` UNIQUE, `instrument_id`, `title`, `detail`, `created_at`, `read_at` |
| `alert_state` | `key` PK, `value` JSON (last known flag levels) |

New settings sections:
- `llm`: `outbound_enabled` **false** by default (privacy toggle), `model`, `monthly_call_cap` (30), `weekly_job` (false), `price_in_per_mtok` / `price_out_per_mtok` (4 / 20 for `claude-opus-5-5`, editable), `effort` (high).
- `news`: the feed list.
- `alerts`: rule toggles and the announcement categories to alert on.

The API key and Groww secrets live only in `.env`; they are never in the DB, the UI or the logs.

### 12.3 News
- Rule categories, first match wins, keyword lists in `app/calc/news.py`:
  results · order win / contract · dividend · board meeting · acquisition / merger ·
  regulatory / legal · management change · rating action · other.
- The LLM may only *suggest* a category for items the rules leave as "other", and only when
  outbound LLM calls are enabled. Only the headline is sent. Origin MODEL is stored and shown.
- Dedupe: identical URL, or headline token-set Jaccard ≥ 0.8 with an item for the same ISIN
  within 3 days (normalised: lower case, no punctuation, stop words removed).
- Retention: items with `published_at` older than 90 days are deleted on every refresh.
- Tracked companies: direct stocks, plus the top 5 look-through holdings (by portfolio
  exposure) of each fund with a disclosure. Funds without a disclosure show "No holdings
  uploaded — fund news is not shown". Generic fund news is never shown.
- Feed sort: company total exposure (direct + through funds), then recency. Filters: holding,
  category, days.
- Dashboard widget: "Recent events for my holdings" (last 7 days, max 8).

### 12.4 Macro and sensitivity
- `macro_values` keys:
  - automated: `usd_inr`, `brent_usd`, `nifty50`;
  - manual: `repo_rate`, `cpi_inflation`, plus any key the user adds.
  - Manual values need a source note and an as-of date that is not in the future.
- Sector sensitivity tags: `rate-sensitive`, `export/currency-exposed`,
  `import/currency-exposed`, `foreign-currency assets`, `crude-input-exposed`,
  `commodity-input-exposed`, `regulation-exposed`, `demand-cyclical`.
  - A STARTER set for the sectors held ships labelled "general characteristics — review and
    edit; not facts about any company"; edits become USER.
- Scenario → tag map (code only, no LLM):
  - rate cut / rate rise → rate-sensitive;
  - weaker rupee → export/currency-exposed, import/currency-exposed, foreign-currency assets
    (listed separately, because the pressure differs by tag);
  - higher crude → crude-input-exposed;
  - sector regulation → regulation-exposed;
  - demand slowdown → demand-cyclical.
  - The view lists the sectors and holdings carrying the tag and their combined look-through
    weight, titled "Exposure by sensitivity tag" (not a forecast).

### 12.5 LLM scenario analysis (`app/llm/`)
- `LLMProvider` protocol: `name`, `model`, `complete_json(system, messages, schema, max_tokens) ->
  (text, usage)`. `AnthropicProvider` (SDK) and `StubProvider` ("not configured" / tests).
- Availability gate, checked before every call; the first failing check is shown:
  1. privacy toggle on (`outbound_enabled`);
  2. `ANTHROPIC_API_KEY` present;
  3. monthly call cap not reached;
  4. holding is a direct stock (funds and ETFs: "analysis not supported — see look-through").
- **Input** (built only from stored data; every value has an `id`):
  - holding: name, symbol, sector + source;
  - portfolio: weight %, direct %, total look-through %;
  - fundamentals: display value or "N/A (reason)", source, as-of;
  - "within my portfolio" medians when they exist;
  - news: last 30 days, max 10, with ids `n:<id>`;
  - macro snapshot;
  - the sector's sensitivity tags (with origin);
  - thesis text only if opted in;
  - the allowed scenario list.
  - **Never** sent: rupee amounts, quantities, invested or P&L values, platform, account
    details, other holdings' names, or journal text without opt-in. A test asserts this.
- **Output** JSON schema (structured outputs; `additionalProperties: false`):
  - `valuation_context[]`, `business_quality[]`, `key_risks[]`, `macro_sensitivity[]`,
    `what_would_change_this_view[]`, `data_gaps[]`: each `{text, citations[≥1]}`;
  - `scenarios[]`: `{scenario ∈ {rate_cut, rate_rise, weaker_rupee, higher_crude,
    sector_regulation, demand_slowdown}, direction ∈ {upward pressure, downward pressure,
    mixed, unclear}, because, citations[≥1]}`.
  - Code renders: "If X happens, the likely direction of pressure on this holding is Y,
    because Z."
- **Guardrails** (`app/llm/validate.py`, tested); an output is rejected if:
  - (a) any number in the output text is not in the input (numbers normalised; citation ids
    excluded);
  - (b) it contains banned wording: buy / sell / hold / accumulate / reduce / exit /
    add more, target price, price target, fair value, upside / downside of, will
    rise / fall / increase / decrease / go up / go down, multibagger, guaranteed;
  - (c) any statement has no citation, or cites an id not in the input;
  - (d) the JSON schema fails.
  - On rejection it retries once with the errors listed. A second failure is stored as
    FAILED with the reasons and **not shown as analysis**.
- **Prompt** (`app/llm/prompts.py`, versioned `PROMPT_VERSION`): the model is told to
  - give scenario and context analysis of one listed company for a private portfolio-analytics
    tool;
  - use only the provided input and cite input ids for every statement;
  - copy numbers exactly from the input or use none;
  - give no recommendations, price targets or predictions;
  - describe direction of pressure, not outcomes;
  - list missing data in `data_gaps`.
- **Cache:** `input_hash = sha256(canonical input JSON + model + PROMPT_VERSION)`. A stored
  analysis with the same hash is returned unless Refresh is clicked. Each card shows the
  data-as-of, model and generation time, plus "View exactly what was sent" (the stored input
  JSON and system prompt).
- **Cost:** every call is logged in `llm_calls`; Settings shows calls this month vs the cap
  and an estimated cost from token counts × the configured prices.
- **Weekly job** (opt-in, Sundays): only holdings with news newer than their last analysis,
  within the cap.

### 12.6 Thesis journal
- POST creates version n+1; there are no edit or delete endpoints (append-only).
- Fields: why I hold it, what would change my view, horizon, review date, linked transactions
  and change-log entries. Each new version writes a `THESIS_UPDATED` change-log entry.
- "Review due": the latest version per holding with a review date ≤ today.
- Opt-in per holding to include the latest thesis in LLM input (off by default).
- Strategy vs actual (`GET /strategy?since=`), purely factual:
  - targets and drift now;
  - latest thesis notes;
  - the snapshot on/after `since` vs today (compare);
  - transactions and change-log entries since that date.

### 12.7 Broker adapters (`app/brokers/`)
- `BrokerAdapter` protocol: `name`, `holdings() -> list[BrokerHolding(isin, symbol, quantity,
  avg_price)]`. There are no order methods; a test inspects the class and asserts no
  order/modify/cancel/place attribute exists.
- `FakeAdapter`, for tests.
- `GrowwAdapter`, behind `GROWW_ENABLED=true`:
  - its HTTP layer allow-lists exactly `POST /v1/token/api/access` and
    `GET /v1/holdings/user`; any other path raises before sending (tested with a mock
    transport that records requests);
  - TOTP comes from `GROWW_TOTP_SECRET` (RFC 6238, stdlib, tested on RFC vectors) or a code
    typed in the UI, which is used once and not stored;
  - the token is kept in memory until its expiry and never logged.
- `KiteMFAdapter`: a documented stub that raises NotImplementedError.
- Reconciliation (pure): Groww-platform stocks/ETFs vs broker holdings by ISIN.
  - Rows: missing in DB, missing at broker, quantity differs, average price differs
    (> 0.5%). Differences only.
  - "Add as transaction" opens a pre-filled in-app transaction form the user must confirm.
    Nothing is written automatically.

### 12.8 Alerts (in-app)
Each rule is a toggle in Settings, and each alert is created once per dedupe key:
- new announcement in a chosen category for a holding I own;
- company-concentration / sector / overlap level changed (vs `alert_state`);
- a disclosure became stale;
- a thesis review date was reached.

Alerts are evaluated after news refresh, price refresh and on page load. Mark-as-read only.

### 12.9 Endpoints
- News: `GET /news` · `POST /news/refresh` · `GET /news/recent` · `GET /news/sources`
- Macro: `GET /macro` · `POST /macro/refresh` · `PUT/DELETE /macro/{key}`
- Sensitivity: `GET /sensitivities` · `PUT /sensitivities/{sector}` · `GET /scenarios`
- Analysis: `GET /analysis` · `POST /analysis/{iid}` (`?refresh=true`) · `GET /analysis/{iid}/preview` (input that would be sent, without calling) · `GET /llm/status`
- Journal: `GET /journal` · `POST /journal/{iid}` · `PUT /journal/{iid}/optin` · `GET /journal/review-due` · `GET /strategy?since=`
- Broker: `GET /broker/status` · `POST /broker/groww/token` · `GET /reconcile`
- Alerts: `GET /alerts` · `POST /alerts/evaluate` · `POST /alerts/{id}/read`

### 12.10 Pages
`/news`, `/macro` (snapshot, sensitivity table, exposure by tag), `/analysis`, `/journal`,
`/strategy`, `/reconcile`, `/alerts`; dashboard widget; Settings gains LLM, news feeds and
alert rules. Analysis pages carry the footer "Scenario and context analysis, not a prediction
or investment advice."

### 12.11 Phase 4 assumptions
1. Google News RSS cannot be used under the robots rule (see 12.1). Publisher RSS feeds plus
   NSE's official feeds replace it.
2. News relevance matching uses company names and symbols in headlines; a headline that
   names a company only indirectly is missed rather than guessed.
3. LLM analysis is for direct stocks only.
4. The privacy toggle defaults to **off**; the app makes no LLM calls until you turn it on and
   set a key.
5. Refusal fallbacks (`fallbacks: "default"`) are enabled on LLM calls, so a safety decline is
   retried on Anthropic's recommended fallback model; the card shows the model that served it.
6. Reconciliation covers Groww stocks/ETFs only (Coin mutual funds have no adapter).
7. One news URL is stored once; if a headline names two holdings it is filed under the one with
   the larger exposure.
8. NSE's RSS host timed out during the live test (2026-10-17); it degrades to "Source
   unavailable" and is retried on the next refresh after the 10-minute cool-down.


---

## 13. Phase 5 design

**Decision (user): the Excel workbook is the ONLY input for holdings and transactions; the app
never connects to a trading account.** The AI works only from what is imported and entered.

### 13.0 Engineering hygiene
- `make check`: backend pytest, frontend tests, eslint and `tsc --noEmit`, run with
  `set -euo pipefail` so any failure fails the target. No command may pipe a test result into
  something that hides its exit code.
- Git pre-commit hook `.githooks/pre-commit`, installed by `make setup` (`make hooks` →
  `git config core.hooksPath .githooks`). It:
  - refuses staged content matching secret patterns (`sk-ant-…`, `ANTHROPIC_API_KEY=<value>`);
  - then runs `make check`.
- LLM settings:
  - `model` is free text (validated characters); the default comes from `CLAUDE_MODEL` in
    `.env`, else `claude-opus-5-5`.
  - **Prices have no hard-coded defaults:** cost estimates show "set prices in Settings" until
    entered, and Settings notes "verify against the provider's pricing page".
  - `refusal_fallback` is a toggle, **default off**; when on, requests carry the server-side
    fallback.
  - Each analysis stores `requested_model` and the model that answered; a card shows both
    when they differ.

### 13.1 Excel-only workflow
- The read-only account adapters, reconciliation page, feature flag, env vars, tests and docs
  are deleted. Phase 4 created no tables for them, so the migration has nothing to drop
  (stated, not invented).
- **Import preview (dry run):**
  - `POST /import/preview` saves the upload under `data/cache/import-preview/<sha256>.xlsx` and
    runs the real importer inside a SAVEPOINT that is rolled back.
  - It returns rows to add, rows to remove (Excel-source only, and only when the file has no
    errors), rows already present as in-app entries, and rows with errors (row numbers and
    reasons).
  - `POST /import/confirm {token}` applies that exact file (sha verified).
  - The CLI gains `--dry-run`.
- **Monthly update** (`GET /monthly-update`, page `/monthly`) — a checklist whose ticks are
  derived from data for the current IST month:
  1. each `monthly_plan` fund has a SIP/BUY row dated this month (otherwise a warning naming
     the fund);
  2. stock/ETF buys recorded this month (count);
  3. a successful import this month;
  4. prices refreshed in the last 24 h;
  5. today's snapshot exists.
  - It also shows how to turn Coin units/NAV into a SIP row (amount authoritative).

### 13.2 Valuation framework (`app/calc/valuation.py`, pure)
New metrics come from yfinance where present and plausible; otherwise N/A with the reason. A
manual override needs a source note and an as-of date.

| metric | definition / source | N/A when |
|---|---|---|
| P/S | `priceToSalesTrailing12Months` | missing, ≤ 0 or > 200 |
| PEG | **P/E ÷ (earnings growth × 100)**, with P/E = `trailingPE` and growth = `earningsGrowth` (YoY, latest quarter); formula and inputs shown | no P/E; growth missing, ≤ 0 or > 1000%; result > 100 |
| FCF (latest annual + trend) | cash-flow statement "Free Cash Flow" per fiscal year | not reported |
| FCF margin | FCF ÷ Total Revenue, same fiscal year | either missing / revenue ≤ 0 |
| FCF yield | latest FCF ÷ market cap | either missing |
| Interest coverage | EBIT ÷ Interest Expense (latest year) | either missing, interest ≤ 0; **not applicable** for sectors in the rules table |

- Annual statement lines are stored in `annual_financials`: revenue, net income, EBIT,
  interest expense, FCF, equity, total debt, diluted EPS.
- Own history (only what the stored years allow): ROE (net income ÷ equity), net margin,
  FCF, FCF margin and EPS per fiscal year.
- **Historical P/E** is computed only if a stored price exists within ±7 days of the fiscal
  year end (price ÷ that year's diluted EPS); otherwise N/A. It is never estimated.
- **Framework check** (Settings › rubric; defaults below). Each check is MEETS / DOES NOT
  MEET / N/A / NOT APPLICABLE (sector), with values, sources and the rule. There is **no
  overall score, ranking or verdict**.
  - P/E ≤ peer median (tolerance 0%);
  - P/E ≤ own historical P/E median;
  - PEG < 1.0;
  - ROE > 15%;
  - debt/equity < 2.0;
  - FCF latest > 0;
  - FCF not declining (latest ≥ previous fiscal year).
- **Sector rules** (Settings, editable): metrics not meaningful for a sector. The default is
  `Financial Services → debt_to_equity, interest_coverage`.

### 13.3 Peers (user-maintained; nothing seeded)
- Table `peer_sets` holds, per stock: up to 8 NSE symbols and a "why these peers" note.
- Peer metrics are fetched via yfinance at most once a day per symbol, 1 s apart, cached in
  `peer_metrics` with source and as-of. The metrics are P/E, P/S, PEG, ROE, D/E, revenue
  growth, profit growth, FCF margin and FCF yield.
- The comparison shows my value vs the **peer median** (labelled "peers chosen by me") and lists
  every peer value. A median needs at least 3 peers with a value; otherwise N/A.

### 13.4 Qualitative fields
- Table `qualitative_entries`, append-only and versioned. Fields:
  - moat type ∈ {brand, switching costs, cost advantage, network effects, regulatory or
    licence, none or unclear};
  - moat note and capital-allocation note;
  - source note and as-of (both required);
  - optional link to a thesis entry.
- LLM input includes them only when the holding's existing opt-in box is ticked (now
  labelled "thesis and qualitative notes").

### 13.5 AI upgrades
- Stock input adds:
  - framework checks (`fc:<key>`);
  - peer comparisons (`pc:<metric>`, with peer values);
  - P/S, PEG (with inputs), FCF figures, FCF history (`hist:<metric>:<FY>`);
  - opted-in qualitative fields (`q:…`).
- **Fund cards**, for every mutual fund. The input is built by code only:
  - category and fund type (index vs active);
  - expense ratio, exit load, tracking difference (manual, else N/A);
  - top 10 look-through holdings with weights and the disclosure as-of + stale flag;
  - sector weights inside the fund;
  - overlap with each other fund, and with my direct stocks;
  - the fund's share of the portfolio %;
  - the thesis/qualitative notes if opted in;
  - a `focus` list (index: tracking difference, cost, top-constituent concentration; active:
    concentration, sector tilts, overlap).
  - Output schema `cost_and_tracking[]`, `concentration[]`, `sector_tilts[]`, `overlap[]`,
    `key_risks[]`, `what_would_change_this_view[]`, `data_gaps[]` — each `{text, citations}`.
- **Portfolio summary** card (optional, one per input hash). The input is concentration
  (look-through), drift, sector metrics and health dimensions; the output is a `summary[]` of
  factual statements plus `data_gaps[]`.
- The same validator applies to all three card kinds (schema per kind). The banned list gains:
  switch / switching, good/bad/great/poor/best/worst fund|choice|investment, and returns
  will / should / are expected.
- `llm_analyses` gains `kind` (stock / fund / portfolio), a nullable `instrument_id` and
  `requested_model`.

### 13.6 Reliability
- `source_events` (`source`, `ok`, `message`, `at`; kept 90 days) is recorded by price refresh
  (yfinance, AMFI), classification and identifier refresh (NSE lists, AMFI), fundamentals and
  peers (yfinance statements), news feeds, macro (yfinance) and LLM calls. The page `/sources`
  shows last success, last failure, last error and a 30-day daily status strip
  (ok / failed / mixed / none).
- **Startup catch-up:** on start, if the last snapshot is before today:
  - refresh prices and NAVs;
  - take today's snapshot;
  - record every missed calendar date in `snapshot_gaps` (reason "app not running").
  - The growth series includes gaps as null points, so the chart shows a break; no value is
    interpolated or back-filled.
- A systemd user service is documented in README (not installed).
- Recorded fixtures (`tests/fixtures/`) come from real successful fetches on 2026-10-17 and
  contain no personal data:
  - yfinance daily bars for LT.NS;
  - LT.NS statement lines;
  - AMFI NAVAll lines for the held schemes;
  - NSE Total Market rows;
  - NSE announcement RSS items.
  - Parser regression tests use them.

### 13.7 Schema (`0005_phase5`)
- New tables: `annual_financials`, `peer_sets`, `peer_metrics`, `qualitative_entries`,
  `source_events`, `snapshot_gaps`.
- `llm_analyses`: + `kind`, + `requested_model`, `instrument_id` nullable (batch alter).
- No tables to drop.

### 13.8 Endpoints and pages
- Import: `POST /import/preview` · `POST /import/confirm`
- Monthly: `GET /monthly-update`
- Valuation: `GET /valuation` · `GET /valuation/{iid}` · `PUT /peers/{iid}` · `POST /peers/refresh`
- Qualitative: `GET /qualitative/{iid}` · `POST /qualitative/{iid}`
- Analysis: `POST /analysis/fund/{iid}` · `POST /analysis/portfolio` · `GET /analysis/portfolio`
  · `GET /analysis/sent/{aid}`
- Sources: `GET /source-health`
- Pages: `/monthly`, `/valuation`, `/sources`; Import gains preview/confirm; Journal gains
  qualitative notes; AI analysis gains fund cards and the portfolio summary; Settings gains the
  rubric, sector rules and the LLM model/prices/fallback.
- Removed: the reconcile page and nav entry.

### 13.9 Phase 5 assumptions
1. "Earnings growth percentage" for PEG = yfinance `earningsGrowth` (latest quarter, YoY) ×
   100.
2. "FCF not declining" = latest fiscal-year FCF ≥ the previous fiscal year's.
3. The peer median uses peers only (my stock excluded).
4. Missed snapshot dates are calendar days, including weekends and holidays, since the app
   was off.
5. The model name and token prices are user settings; the app ships no prices.
6. `CLAUDE_MODEL` in `.env` sets the default model (`claude-sonnet-5` in this `.env`); a model
   chosen in Settings overrides it.
