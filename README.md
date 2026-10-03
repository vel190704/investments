# Personal Investment Dashboard

A personal, single-user, local-first **portfolio analytics and planning** tool for an Indian
retail investor (Groww stocks/ETFs + Zerodha Coin mutual funds). It reads your Excel tracker,
values holdings with public market data, and shows allocation, concentration, and how a next
contribution would change your mix.

It also tracks daily history, allocation drift against your own targets, a monthly
contribution planner, mathematical projections, and a separate emergency fund.

It shows sector exposure, fundamentals, and what your funds hold combined with your direct
stocks (look-through), plus a Portfolio Health page with no overall score.

It **never places orders**, has no login, and binds only to `127.0.0.1`.
*Personal analytics tool, not investment advice.*

- Design, schema, formulas and assumptions: [PLAN.md](PLAN.md)
- Conventions for contributors / AI assistants: [CLAUDE.md](CLAUDE.md)

## Setup

Requirements: Python 3.12+ (developed on 3.14), Node 20+, `make`.

```bash
make setup          # backend/.venv + pip install, frontend npm install
cp .env.example .env   # optional — defaults work without it
```

## Run

```bash
make dev            # backend http://127.0.0.1:8000  +  frontend http://127.0.0.1:3000
```

Open http://127.0.0.1:3000. Ctrl-C stops both. Run them separately with `make backend` and
`make frontend`.

### Database migrations and backups

The schema is managed with Alembic (`backend/migrations/`).
- Migrations run automatically when the backend starts.
- Before any pending migration is applied, the SQLite file is backed up to
  `data/backups/investments-<timestamp>-pre-<revision>.db` (git-ignored).
- A Phase 1 database (created before Alembic) is recognised and stamped as the baseline.

```bash
make backup         # ad-hoc consistent copy of the DB into data/backups/
make fundamentals   # fetch fundamentals now (also refreshed every Sunday by the daily job)
make migrate        # apply migrations now (backs up first)
```

### First run

1. Put your workbook at `data/personal_investment_tracker_clean.xlsx` (`data/` is git-ignored).
2. Import it with `make import` or the **Import** page.
3. Open **Mappings** and confirm the proposed identifiers:
   - ISINs come from NSE's securities lists (exact symbol match).
   - AMFI scheme codes come from `NAVAll.txt` (same plan and option, ranked by name similarity).

   Nothing is applied until you confirm it. Mutual funds show "Data unavailable" until their
   scheme code is confirmed.
4. Click **Refresh prices**, or run `make refresh`.
   - A scheduled refresh also runs daily at 23:30 IST while the backend is up, and on start-up
     if prices are more than 18 h old.
   - Every refresh stores that day's snapshot.
5. Open **Settings** to enter your target allocation, review the projection rates (they ship as
   placeholders), and fill in the emergency fund. Nothing there is assumed for you.

## Pages

| page | what it shows |
|---|---|
| Dashboard | value, invested, P&L, today's change, monthly plan, allocation, top holdings, flags, growth |
| History | growth chart (value vs invested), snapshot list, "Take snapshot" |
| Changes | change log (transactions, quantity/avg-cost, allocation) and compare snapshot A vs B or today |
| Stocks & ETFs / Mutual funds | holdings tables with source, as-of date and XIRR |
| Transactions | all rows with their source; add BUY/SIP/SELL/DIVIDEND; delete in-app rows; export to Excel |
| Allocation | asset classes, drift vs targets (tolerance band), XIRR by class, concentration, "not held" info |
| Next contribution | one-off amount: before → after per scenario |
| Monthly planner | budget modes; distribution by monthly_plan and by your targets; allocation considerations |
| Projection | Conservative / Base / Higher mathematical scenarios with formula and assumptions |
| Emergency fund | target, % complete, remaining (never part of the portfolio) |
| Portfolio health | separate dimensions with reasons: company (look-through), sector, drift, overlap, international, liquidity, volatility, emergency fund |
| Sectors | sector exposure incl. funds, HHI and largest sector, geography, your desired ranges and themes |
| Fund look-through | upload AMC disclosures / index weights; total company exposure (direct + via funds); pairwise overlap |
| Fundamentals | per-stock metrics from Yahoo Finance with source/date; manual ROCE, promoter holding, alpha; fund facts |
| Classification | override asset class (e.g. Gold, Debt/Cash), sector and region per instrument |
| Import / Mappings / Settings | data management |

## In-app transactions and export

- **Add transaction** (Transactions page) records BUY, SIP, SELL or DIVIDEND with the same
  validation as the Excel import.
  - For an MF SIP, enter the units and NAV from Coin plus the amount; the amount is
    authoritative.
  - OPENING balances belong in the workbook.
- In-app rows (`source = ui`) are **never** removed by a re-import. If the workbook later
  contains an identical row, it is recognised and not duplicated.
- Only in-app rows can be deleted in the app. Deleting one that a later SELL depends on is
  refused.
- **Export to Excel** writes every transaction (workbook + in-app) plus `holdings_fallback`
  and `monthly_plan` in the exact input layout, so it is both a backup and a valid import.

## Tests

```bash
make test           # backend pytest (calculations, importer, idempotency, XIRR, simulator, drift,
                    # planner, projection, emergency-fund isolation, snapshots, change log, migrations, API)
                    # + frontend INR-formatting tests
make lint           # eslint + tsc
```

## Excel format

Sheet names and column headers must match exactly (case-insensitive headers). The `README`
sheet is ignored.

### `transactions` (primary source)

| column | notes |
|---|---|
| `date` | `YYYY-MM-DD`. Rows with an empty date are **skipped and reported**. |
| `type` | `BUY`, `SELL`, `SIP`, `DIVIDEND`, `OPENING` |
| `asset_type` | `STOCK`, `ETF`, `MF` |
| `name` | instrument name; for MFs this identifies the fund, so keep it consistent |
| `symbol` | NSE symbol for STOCK/ETF (required); blank for MF |
| `isin`, `scheme_code` | optional; if filled, treated as already confirmed |
| `quantity` | shares or MF units, positive (also positive for SELL) |
| `price` | per share / NAV (informational; `amount` is authoritative) |
| `amount` | total INR, positive |
| `charges` | optional, added to cost on purchases, deducted from proceeds on sales |
| `platform` | `Groww` or `Zerodha Coin` (others are allowed with a warning) |
| `notes` | free text |

Row types:
- **OPENING** is a balance as of that date. It counts toward quantity, invested amount, value
  and P&L, but is excluded from XIRR. XIRR shows "N/A (needs dated transactions)" until an
  instrument has a real BUY/SIP row.
- **SELL** uses positive quantity and amount; `type` gives the direction. A SELL larger than
  the quantity held is rejected.
- **DIVIDEND** needs `amount` only.

### `holdings_fallback`

`as_of_date, platform, asset_type, name, symbol, quantity, invested_amount, monthly_plan, sector, notes`.
Used only for an instrument that has no rows in `transactions` (treated as an OPENING balance).

### `monthly_plan`

`platform, asset_type, name, monthly_amount, allocation_percent`.
- `allocation_percent` is a **fraction** (`0.6` = 60%).
- A `TOTAL` row is optional and is only used to cross-check the sum.
- MF rows must use the same fund name as in `transactions`.

## Re-importing

Edit the workbook, then run `make import` again or upload it on the Import page. Imports are
idempotent:
- Unchanged rows are recognised and not duplicated.
- New rows are added, and edited notes are updated in place.
- Rows you deleted from the workbook are removed from the database, but only when the file has
  zero row errors. Otherwise nothing is removed and the report says so.
- Only workbook (`excel`) rows can be removed. In-app rows, snapshots, settings and the change
  log are never touched by an import.

Every import prints a report (loaded / skipped / errors with row numbers) and is kept in the
import history.

```bash
make import FILE=data/another_file.xlsx
cd backend && .venv/bin/python -m app.import_excel ../data/file.xlsx --no-resolve   # offline
```

## Fund holdings: downloading and uploading AMC disclosures

SEBI requires every AMC to publish its schemes' portfolios each month, usually by the 10th, as
of the last day of the previous month. Look-through and overlap use these files.

1. Download the **monthly portfolio** file (Excel) from the AMC's website. It is normally under
   *Downloads* or *Statutory Disclosures*, as *Monthly Portfolio* or *Portfolio Disclosure*.
   Site menus change; search the AMC site for "monthly portfolio".
   - **HDFC Mutual Fund**: hdfcfund.com → Statutory Disclosures → Monthly Portfolio. One workbook
     per month with one sheet per scheme. Upload the whole file; the sheet for your fund is
     found by name.
   - **ICICI Prudential Mutual Fund**: icicipruamc.com → Downloads → Monthly Portfolio
     Disclosures. A per-scheme or all-scheme workbook.
   - **Kotak Mahindra Mutual Fund**: kotakmf.com → Downloads / Statutory Disclosures → Portfolios
     → Monthly.
2. Open **Fund look-through** and choose the fund. Leave "AMC layout" on *Detect from file*, or
   pick the AMC, then upload the `.xlsx`.
   - The as-of date is read from the "Portfolio as on …" line. You can type it if the file has
     none.
   - Uploading the same fund and month again replaces it; other months are kept, and the newest
     is used.
3. If the parser says **"Unrecognised layout"**, the error shows the header row it found. The
   AMC has probably renamed a column. Add the new name to that AMC's aliases in
   `backend/app/disclosures/engine.py` (and a fixture test). The parsers were written from the
   AMCs' published column names and tested on small synthetic files, not real downloads.

**Index funds** (Nifty 50, Nifty Next 50) can also use index constituent weights as an
approximation:
- Choose *Index constituent weights (.csv)*.
- Enter the index name and as-of date.
- Upload a CSV with columns `ISIN, Company Name, Weightage %` (optional `Industry`). Weights are
  in NSE's monthly index factsheets; NSE's downloadable constituent lists have no weights.

These are labelled "approximated from index weights, as of <date>". A disclosure older than two
months is flagged as stale. Enter the tracking difference on Fundamentals to see how closely
the fund follows its index.

## Data sources

| what | source | notes |
|---|---|---|
| Stock/ETF prices | Yahoo Finance via `yfinance` (`SYMBOL.NS`) | daily close + previous close; may be delayed |
| MF NAVs | AMFI `NAVAll.txt` | latest NAV only; "today's change" for funds appears once a previous NAV is cached |
| ISINs | NSE `EQUITY_L.csv`, `eq_etfseclist.csv` | |
| Scheme codes | AMFI `NAVAll.txt` | |
| Stock sectors | NSE index constituent lists (Nifty Total Market, Microcap 250), "Industry" | stocks in neither list stay "Unclassified" until overridden |
| ETF classes / regions | NSE ETF list: ETF Underlying + Underlying Asset | Gold, Debt/Cash, International, … by what the ETF holds |
| Fund category | AMFI `NAVAll.txt` section headers | needs a confirmed scheme code |
| Fundamentals | Yahoo Finance via yfinance | only plausible values; otherwise N/A with the reason |
| ROCE, promoter holding, alpha, expense ratio, exit load, tracking error/difference | **manual** (source note + as-of date required) | no reliable free source; nothing is scraped |
| Fund holdings | your uploads of AMC disclosures / index weights | |

Every market-derived number shows its source and date. Anything missing shows
"Data unavailable"; nothing is estimated.

## Layout

```
backend/   FastAPI + SQLAlchemy (app/calc = pure, tested financial functions)
frontend/  Next.js App Router + TypeScript + Tailwind + shadcn/ui + Recharts
data/      your workbook, SQLite DB, download caches (git-ignored)
```

To move to Postgres later, set `DATABASE_URL` in `.env`. All DB access goes through
`app/db.py` and `app/repository.py`.
