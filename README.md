# Personal Investment Dashboard

An invite-only, multi-user **portfolio analytics and planning** web app for a small group of
Indian retail investors (friends and family; Groww stocks/ETFs + Zerodha Coin mutual funds).
Each person uploads their own Excel tracker and sees only their own data. It reads your Excel tracker,
values holdings with public market data, and shows allocation, concentration, and how a next
contribution would change your mix.

It also tracks daily history, allocation drift against your own targets, a monthly
contribution planner, mathematical projections, and a separate emergency fund.

It shows sector exposure, fundamentals, and what your funds hold combined with your direct
stocks (look-through), plus a Portfolio Health page with no overall score.

Phase 4 adds:
- news and exchange announcements per holding;
- a macro snapshot and exposure by sensitivity tag;
- optional AI scenario analysis with strict guardrails;
- a thesis journal;
- in-app alerts.

Phase 5 adds:
- an import preview (dry run) and a **Monthly update** checklist;
- a valuation framework (P/S, PEG, FCF, interest coverage) checked against **your** rubric,
  with peers you choose and the company's own history;
- versioned qualitative notes (moat, capital allocation);
- AI cards for funds and an optional portfolio summary;
- a **Source health** page and honest snapshot gaps after downtime.

**Excel is the only input for holdings and transactions.** The app never connects to a broker
or platform account; you copy figures from Groww/Coin into the workbook (or the in-app form)
and import. The AI works only from what you import.

Phase 6 adds accounts: invite-only sign-in (Supabase Auth), per-user data isolation, an admin
page, Postgres for deployment, and shared market data fetched once for everyone.

It **never places orders**. Locally it runs in dev mode (no login, one local user, `127.0.0.1`).
*Personal analytics tool, not investment advice.*

- Design, schema, formulas and assumptions: [PLAN.md](PLAN.md)
- Conventions for contributors / AI assistants: [CLAUDE.md](CLAUDE.md)

## Setup

Requirements: Python 3.12+ (developed on 3.14), Node 20+, `make`.

```bash
make setup          # backend/.venv + pip install, frontend npm install, git pre-commit hook
cp .env.example .env   # optional — defaults work without it
```

`make setup` points git at `.githooks/`. Its pre-commit hook:
- refuses staged lines that look like an API key, and any `.env*` file except `.env.example`;
- runs `make check` and blocks the commit if anything fails.

Never put secrets in `.env.example` (it is tracked); they belong in `.env` (git-ignored).

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

## Accounts and isolation (Phase 6)

- **Local development** (`make dev` sets `ENV=development DEV_AUTH=1`): no sign-in; you are `DEV_USER_EMAIL`
  (default `owner@localhost`, an admin). An existing single-user database is upgraded in place
  (migration 0008) and all its data becomes this user's.
- **Deployment** (Vercel + Render + Supabase, CI, preview vs production, rollback, custom domain):
  [docs/DEPLOY.md](docs/DEPLOY.md). The backend ships as a Docker image (`backend/Dockerfile`, non-root,
  health check); every push and pull request runs CI (`.github/workflows/ci.yml`).
- **Going live and running it:** [docs/LAUNCH.md](docs/LAUNCH.md) (go-live checklist, incident runbook),
  [docs/OPERATIONS.md](docs/OPERATIONS.md) (backups with a proven restore, uptime and cold starts, kill switches),
  [docs/SECURITY.md](docs/SECURITY.md) (security review, `make audit`). Friends and family read `/help` in the app.
- **Everywhere else** sign-in is required (fail closed): unset or unknown `ENV` counts as production,
  `DEV_AUTH=1` outside development/test refuses to start, and without Supabase settings the app
  refuses to start. Sign-in is by email magic link; only invited emails get in
  (open sign-up is off in Supabase and the backend checks its own invite list). Deployment steps:
  docs/DEPLOY.md (checkpoint 6b).
- **What is shared:** market data (prices, NAVs, fundamentals, sector lists, news, macro) is
  fetched once for the union of everyone's holdings. Each person sees prices and news only for
  their own holdings.
- **What is private:** everything a person uploads or enters (workbook rows, settings, journal,
  notes, peers, disclosures, analyses, alerts). Every query is filtered to the signed-in user in
  one place; tests attack every route as another user. Postgres Row Level Security is a second
  layer.
- **Admin page** (admins only): people, last activity, row counts (never figures), AI usage;
  invite or remove; enable AI per person with a monthly cap; delete someone's data completely.
- **Account page:** export my data (Excel), optional own AI key (stored encrypted), delete my
  account and all data.
- **New users** see a short getting-started guide with a downloadable blank Excel template.
- **Simple mode** (Account page, per person): a shorter menu without the advanced pages (Valuation & peers,
  Fund look-through, Fundamentals, Macro & scenarios). On by default for members, off for admins; Dashboard,
  Holdings, Allocation, Next contribution, Monthly planner and Projection are always in the menu.

**AI for others:** off until the admin enables it per person. The app's key never leaves the
server. Caps: each person's own cap, the admin's per-person cap (default 10/month) and a global
monthly cap for the app's key (Settings › AI platform).

**Moving your existing data into the hosted database** (one time, after 6b sets up Postgres):

```bash
cd backend
TARGET_DATABASE_URL='<postgres url, see DEPLOY.md>' .venv/bin/python -m app.tools.sqlite_to_postgres \
    --sqlite ../data/investments.db --owner-email you@example.com
```

The SQLite file is not modified. The tool migrates a copy, copies every table into the empty
Postgres database under your account, and prints both sides' totals (value, invested, P&L,
holdings, transactions, snapshots). It exits with an error unless they are identical, and refuses
a target that already has accounts.

## Monthly routine (Excel is the only input)

The **Monthly update** page is a checklist whose ticks come from your data, not from
checkboxes:

1. **Add this month's SIP rows.** In Coin, open each SIP order and note the units and NAV. Add a
   row to the `transactions` sheet (date, SIP, MF, the fund name exactly as before, units,
   NAV, amount), or use *Transactions › Add transaction*. The amount is authoritative.
   - A warning appears for every `monthly_plan` fund without a SIP row dated in the current
     month.
2. **Add any new stock/ETF buys** (from Groww's order history) the same way.
3. **Import** the workbook on the Import page. You see a preview first; nothing changes until
   you click Confirm.
4. **Refresh prices and NAVs** (button on the dashboard, or `make refresh`).
5. **Take today's snapshot.** Every refresh stores one; the History page also has a button.

## Pages

| page | what it shows |
|---|---|
| Dashboard | value, invested, P&L, today's change, monthly plan, allocation, top holdings, flags, growth |
| History | growth chart (value vs invested), snapshot list, "Take snapshot" |
| Changes | change log (transactions, quantity/avg-cost, allocation) and compare snapshot A vs B or today |
| Stocks & ETFs / Mutual funds | holdings tables with source, as-of date and XIRR |
| Dashboard / Stocks & ETFs (live) | Live toggle, market status, live value and day P&L from fresh quotes, sparklines, intraday chart |
| Monthly update | this month's checklist (SIP rows, buys, import, prices, snapshot) with missing-SIP warnings |
| Transactions | all rows with their source; add BUY/SIP/SELL/DIVIDEND; delete in-app rows; export to Excel |
| Allocation | asset classes, drift vs targets (tolerance band), XIRR by class, concentration, "not held" info |
| Next contribution | one-off amount: before → after per scenario |
| Monthly planner | budget modes; distribution by monthly_plan and by your targets; allocation considerations |
| Projection | Conservative / Base / Higher mathematical scenarios with formula and assumptions |
| Emergency fund | target, % complete, remaining (never part of the portfolio) |
| Portfolio health | separate dimensions with reasons: company (look-through), sector, drift, overlap, international, liquidity, volatility, emergency fund |
| Sectors | sector exposure incl. funds, HHI and largest sector, geography, your desired ranges and themes |
| Fund look-through | upload AMC disclosures / index weights; total company exposure (direct + via funds); pairwise overlap |
| Fundamentals | per-stock metrics from Yahoo Finance with source/date (P/S, PEG, FCF, coverage show their formula on hover); manual values incl. FCF in ₹ crore; fund facts |
| Valuation & peers | your rubric per stock (meets / does not meet / N/A / not applicable, no score), peers you chose vs their median, own annual history |
| Classification | override asset class (e.g. Gold, Debt/Cash), sector and region per instrument |
| News & announcements | NSE official announcement feeds + allowed publisher feeds, rule-categorised, sorted by your look-through exposure |
| Macro & scenarios | USD/INR, Brent, Nifty 50 (automated); repo rate, CPI (manual); sector sensitivity tags; exposure by tag |
| AI analysis | stock, fund and portfolio-summary cards (optional, guardrailed, cached), with "View exactly what was sent" and the model that answered |
| Thesis journal / Strategy vs actual | append-only theses and qualitative notes (moat, capital allocation) with review dates; stated targets/theses next to what changed |
| Source health | per data source: last success, last failure and error, a 30-day strip |
| Alerts | in-app alerts from rules you toggle in Settings |
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
make check          # everything the pre-commit hook runs: backend tests, frontend tests, lint, typecheck
make pg-up          # throwaway local Postgres in Docker (tests only)
make test-postgres  # Postgres-only tests: RLS, advisory locks, cross-user attack, data move
make test-all-postgres  # the whole backend suite on Postgres
docker build -t investments-backend backend   # the deployable backend image
```

CI (GitHub Actions) runs `make check`, the Postgres tests and the Docker build on every push and pull
request; deployments wait for it (docs/DEPLOY.md §8, §11).

`make` runs recipes with `bash -euo pipefail`, so a failing step can never be hidden behind a
pipe. Network and LLM calls are always mocked in tests. Parser regression tests replay trimmed
real responses recorded on 2026-10-17 (`backend/tests/fixtures/`: Yahoo statements and prices,
AMFI NAVAll, an NSE sector list and an NSE announcements feed; no personal data).

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

Edit the workbook, then upload it on the Import page or run `make import` again.

On the Import page, the upload is a **preview** (a dry run inside a transaction that is
always rolled back). It lists:
- rows to add;
- rows to remove (only workbook rows; in-app rows are never removed);
- rows with errors.

Click **Confirm** to apply exactly that file; the preview token is tied to the file's hash and
works once. From the command line, `--dry-run` prints the same preview without saving.

Imports are idempotent:
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
cd backend && .venv/bin/python -m app.import_excel ../data/file.xlsx --dry-run      # preview only
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

## News sources and what is (not) fetched

All fetching goes through one polite client:
- a clear User-Agent;
- `robots.txt` checked first; a 403 on `robots.txt` counts as "not permitted";
- at least 2 s between requests to the same host, and responses cached for 30 min;
- a 25 s read timeout per request (`SOURCE_TIMEOUT_SECONDS`; per host: `SOURCE_TIMEOUTS='{"nsearchives.nseindia.com": 40}'`
  in `.env`);
- timeouts, connection errors and 502/503/504 are retried **once** after 5 s; 401/403/429 never are;
- a host that still fails is skipped for 10 min.

A blocked source shows **"Source unavailable"** and is never worked around.

| source | status |
|---|---|
| NSE official RSS feeds (announcements, board meetings, results, corporate actions) | used; matched to holdings by NSE symbol, stored by ISIN |
| ET Markets, Mint Markets RSS (default feeds; editable in Settings) | used; a headline must name the company or its upper-case symbol |
| Google News RSS | **not usable**: its robots.txt disallows `/rss`, so it always shows "Source unavailable" |
| Business Standard, Moneycontrol | answered 403 to `robots.txt` for this tool on 2026-10-17, so they are not in the defaults |
| BSE | API refuses non-browser clients, so it is not used |

Only holdings with a **confirmed ISIN** (Mappings) are tracked. For funds, news covers their
top 5 holdings by your look-through exposure, never generic fund news. Items older than 90
days are deleted.

When the page shows no items it says why: not fetched yet, every source failed (with each
reason), items were fetched but no holdings are tracked yet (confirm ISINs on Mappings), or
nothing mentioned your tracked companies. The Sources box shows how many items each source
returned and how many matched.

## Valuation framework, rubric and peers

**Valuation & peers** shows, per stock:
- **P/S**; **PEG** = P/E ÷ (earnings growth × 100), with the formula and inputs shown. PEG is
  N/A (with the reason) when there is no P/E, or growth is missing, zero/negative or
  implausible. The growth figure is Yahoo's `earningsGrowth` (latest quarter, year on year).
- **FCF** (latest fiscal year and trend), FCF margin, FCF yield and interest coverage, from
  Yahoo's annual statements.
- Any of these can be entered manually on Fundamentals, with a required source note and
  as-of date (FCF in ₹ crore). Manual values are tagged "manual".

**Framework check.** Each rule in your rubric is shown as *meets / does not meet / N/A /
not applicable*, with the value and its source. There is no overall score, ranking or verdict.
Interest coverage is shown for context only.

**Settings › Rubric** holds the thresholds. Defaults:
- P/E at or below the peer median (tolerance 0%) and at or below its own historical median;
- PEG below 1.0;
- ROE above 15%;
- D/E below 2.0;
- FCF positive and not declining.

The thresholds are editable; the two FCF rules can also be switched off. To exclude a metric
for a whole sector, use sector rules.

**Settings › Sector rules** lists metrics that are *not applicable* per sector. The default
marks debt/equity and interest coverage as not applicable for Financial Services. Add a sector
(the exact name shown on the Sectors page) and tick metrics to extend it.

**Peers.** Open a stock's *Details*, type up to 8 NSE symbols and a "why these peers" note,
then **Save peers**. Nothing is suggested or seeded. Click **Refresh fundamentals & peers**
to fetch the same metrics for them.
- Peer fetches are rate-limited (1 s apart) and cached for 24 h.
- The comparison is labelled "peers chosen by me".
- A median needs at least 3 peers with a value; otherwise it is N/A.

**Own history** comes only from the annual statements Yahoo provides (usually four years).
A historical P/E appears only when a stored price within 7 days of a fiscal year end exists;
otherwise it is N/A. History is never estimated.

## AI analysis: API key, model, privacy toggle, what is sent

1. Put `ANTHROPIC_API_KEY=...` in `.env` (never in `.env.example`) and restart the backend.
   Optionally set `CLAUDE_MODEL=...` there too.
2. In **Settings › AI analysis**, tick **Allow outbound LLM calls**. It is off by default; while
   it is off, nothing is sent anywhere. You can also set:
   - the **model id** (free text). If it is empty, `CLAUDE_MODEL` from `.env` is used, and
     failing that `claude-opus-5-5`;
   - **input/output prices per million tokens**. The app ships none, so the cost shows N/A
     until you enter them. Verify them against the provider's pricing page;
   - **refusal fallback** (off by default). When on, a refused request may be answered by
     another model. The card then shows "Answered by X (fallback — you requested Y)";
   - effort, a monthly call cap (default 30) and the optional weekly job.
3. On **AI analysis**, click **Generate** on a stock, a fund or the optional **Portfolio
   summary**. Results are cached by a hash of the inputs, the model and the prompt version; a
   call is made again only when one of these changes or you click Refresh.

**Sent** (per stock):
- company name, NSE symbol and sector;
- your portfolio weight and look-through exposure as **percentages**;
- fundamentals as displayed, with source/as-of, and "N/A" kept as N/A;
- "within my portfolio" medians;
- framework results, PEG/P-S/FCF/coverage, the peer comparison and own history, each with an id;
- up to 10 headlines from the last 30 days;
- the macro snapshot and the sector's sensitivity tags;
- your latest thesis and qualitative notes **only if** you ticked "include in AI analysis" for
  that holding (Thesis journal).

**Sent** (per fund; built by code only):
- category, index/active, share of the portfolio (%) and costs as entered;
- top-10 holdings and sector weights from your uploaded disclosure, with its date (flagged
  when stale);
- overlap with your direct stocks and with other funds.

Index funds emphasise tracking difference, cost and top-constituent concentration. Active
funds emphasise concentration, sector tilts and overlap.

**Sent** (portfolio summary): health dimensions, top company exposures and drift, all as
percentages. The emergency fund is excluded.

**Never sent:**
- rupee amounts, quantities, invested/value/P&L, average cost;
- platform or account details;
- other holdings' names (stock cards);
- journal or qualitative text without opt-in.

The exact system prompt and input of every analysis are shown under **View exactly what was
sent** (or *Preview what would be sent* before the first call).

Every answer is validated before display. It is rejected if it:
- (a) contains a number that is not in the input;
- (b) uses buy/sell/hold/switch, target-price, "will rise", good/bad fund or return-prediction
  wording;
- (c) has a statement without a valid citation to an input id;
- (d) fails the JSON schema.

A rejected answer is retried once with the reasons; if it fails again it is flagged and not
shown.

## Live intraday prices

**Settings › Live prices** turns it on (off by default) and sets the poll interval (60 s by
default, 30–300 s). While it is on:
- the backend polls quotes for your **direct stocks and ETFs** during market hours only:
  09:15–15:30 IST, Monday–Friday, excluding the holidays in **Settings › Market holidays**;
- it polls only while a page showing live prices (Dashboard, Stocks & ETFs) is open, and the
  page refreshes only while its browser tab is visible;
- each cycle is one batched yfinance request for 1-minute bars; failed cycles back off (2×, 4×,
  … up to 10 min). "Refresh quotes now" works any time, at most once per 30 s.

**Mutual funds are not polled**: an AMFI NAV is published once a day.

What you see:
- Live value and day P&L vs the previous close, from **fresh quotes only**. A quote older than
  two poll intervals is marked *delayed/stale* and left out, as is any instrument whose quote
  failed; a warning lists them.
- Per stock: live price, quote time, day change, and a sparkline of today's real 1-minute bars.
- A portfolio intraday chart. Each point values the included holdings at their last traded price
  at or before that minute; minutes before a holding's first trade of the day are omitted.
- Outside market hours: "Market closed", the reason and the next open; the table shows the last
  close.

Quotes are real (Yahoo Finance via yfinance, may be delayed): nothing is simulated or
interpolated. Ticks are kept 14 days in `intraday_ticks` and **never** feed snapshots, XIRR or
history; those stay end-of-day.

**Market holidays.** The table starts empty: enter each NSE trading holiday by hand (date and
name) and verify it against the NSE holiday list (nseindia.com › Resources › Exchange
Communication › Holidays). Nothing is scraped. A weekday that isn't in the table is treated as a
trading day, and the dashboard warns while the table is empty.

## Logs and debugging

The backend logs to the console and to `logs/app.log` (rotated at 10 MB, 5 files kept;
`logs/` is git-ignored).
- One line per event, as `key=value` pairs (or JSON with `LOG_FORMAT=json`); level from
  `LOG_LEVEL` (default `INFO`).
- Every line carries `rid=`, the request id. The response sends it back as `X-Request-ID`, and
  error messages in the UI show it with a copy button, so you can find the matching lines.
- Logged: every request (method, path, status, duration); 4xx details (validation errors list
  the field and message, never the submitted value); 5xx full tracebacks; every outbound call
  (source, host, status, duration, retries, error class); every LLM call (model, input hash,
  tokens, latency, outcome, validator rejection reasons); every scheduled job (start, end,
  duration, outcome); every live poll cycle; the start-up catch-up.
- **Never logged:** API keys, Authorization or x-api-key headers, key or token URL
  parameters (a redaction filter removes them from every line, tracebacks included), journal or
  qualitative text, and LLM prompts or inputs.

```bash
make logs          # follow logs/app.log
make logs-errors   # follow WARNING and above (plus tracebacks)
```

**AI connection test.** *Settings › AI analysis › Test connection* sends one fixed line (no
portfolio data, at most 16 output tokens) to check the key and the model id you typed. It shows
the model that answered, the latency and the provider's exact error text, and says whether
refusal fallback is on. It works while outbound calls are off, because it carries nothing about
you; it is logged and counts toward the monthly cap.

## Reliability: source health, start-up catch-up, running as a service

**Source health** records every fetch (Yahoo prices, fundamentals, peers and macro; AMFI;
NSE lists and announcements; news feeds; the LLM provider). For each it shows the last
success, the last failure with its error, and a 30-day strip. Events are kept for 90 days.

**Start-up catch-up.** When the backend starts, it:
1. records every day since the last snapshot as a **gap** ("no snapshot: the app was not
   running");
2. fetches current prices and stores today's snapshot.

The growth chart breaks the line at gaps and marks them; it never interpolates or back-fills.

**Optional: run the backend as a systemd user service.** This is documentation only; the app
does not install it. Create `~/.config/systemd/user/investments.service`:

```ini
[Unit]
Description=Personal investment dashboard (backend, 127.0.0.1 only)

[Service]
WorkingDirectory=%h/projects/investments/backend
ExecStart=%h/projects/investments/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure

[Install]
WantedBy=default.target
```

Then run `systemctl --user daemon-reload && systemctl --user enable --now investments`.
`loginctl enable-linger $USER` keeps it running while you are logged out. Start the UI with
`make frontend` when you want it.

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
| Annual statements (FCF, coverage, own history) | Yahoo Finance via yfinance (`income_stmt`, `cashflow`, `balance_sheet`) | usually four fiscal years |
| Peer metrics | Yahoo Finance via yfinance, for the symbols you chose | rate-limited, cached 24 h |
| Intraday quotes (live) | Yahoo Finance via yfinance, 1-minute bars, one batched request per poll | market hours only; may be delayed; kept 14 days |
| Market holidays | **manual** (Settings), verified against the NSE holiday list | nothing scraped |
| ROCE, promoter holding, alpha, expense ratio, exit load, tracking error/difference | **manual** (source note + as-of date required) | no reliable free source; nothing is scraped |
| Fund holdings | your uploads of AMC disclosures / index weights | |
| USD/INR, Brent, Nifty 50 | Yahoo Finance via yfinance (`INR=X`, `BZ=F`, `^NSEI`) | N/A on failure; never filled from memory |
| Repo rate, CPI and others | **manual** (source note + as-of required) | |

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
