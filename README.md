# Personal Investment Dashboard

A personal, single-user, local-first **portfolio analytics and planning** tool for an Indian
retail investor (Groww stocks/ETFs + Zerodha Coin mutual funds). It reads your Excel tracker,
values holdings with public market data, and shows allocation, concentration, and how a next
contribution would change your mix.

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

### First run

1. Put your workbook at `data/personal_investment_tracker_clean.xlsx` (`data/` is git-ignored).
2. Import it with `make import` or the **Import** page.
3. Open **Mappings** and confirm the proposed identifiers:
   - ISINs come from NSE's securities lists (exact symbol match).
   - AMFI scheme codes come from `NAVAll.txt` (same plan and option, ranked by name similarity).

   Nothing is applied until you confirm it. Mutual funds show "Data unavailable" until their
   scheme code is confirmed.
4. Click **Refresh prices**, or run `make refresh`. A scheduled refresh also runs daily at
   23:30 IST while the backend is up, and on start-up if prices are more than 18 h old.

## Tests

```bash
make test           # backend pytest (calculations, importer, idempotency, XIRR, simulator, API)
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

Every import prints a report (loaded / skipped / errors with row numbers) and is kept in the
import history.

```bash
make import FILE=data/another_file.xlsx
cd backend && .venv/bin/python -m app.import_excel ../data/file.xlsx --no-resolve   # offline
```

## Data sources

| what | source | notes |
|---|---|---|
| Stock/ETF prices | Yahoo Finance via `yfinance` (`SYMBOL.NS`) | daily close + previous close; may be delayed |
| MF NAVs | AMFI `NAVAll.txt` | latest NAV only; "today's change" for funds appears once a previous NAV is cached |
| ISINs | NSE `EQUITY_L.csv`, `eq_etfseclist.csv` | |
| Scheme codes | AMFI `NAVAll.txt` | |

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
