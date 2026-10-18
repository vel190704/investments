# Operations

Running the app day to day: backups and restores, uptime and cold starts, kill switches. Deployment itself is in
[DEPLOY.md](DEPLOY.md); the go-live checklist and incident runbook are in [LAUNCH.md](LAUNCH.md).

> Values never appear here, only variable names. Keep them in your password manager and set them in your shell when
> needed (`read -rs NAME && export NAME`).

## 1. Backups

### 1.1 What Supabase provides (⚠ verify on your plan)

At the time of writing (check Supabase › **Database › Backups** and Supabase's pricing page for your project):

| plan | what you get |
|---|---|
| Free | No backups you can restore yourself. Free projects can also be **paused** after a period of inactivity (data kept, project offline until resumed). |
| Pro | **Daily** backups, kept about **7 days**, restorable from the dashboard. They include the whole database, sign-in accounts too. |
| Team / Enterprise | Daily backups kept longer (about 14 / up to 30 days). |
| Point-in-time recovery | Paid add-on: restore to any second within its window (7, 14 or 28 days). |

A Supabase restore replaces the **whole project** with the backup: every person's data goes back to that moment.
After any restore, re-apply the deletion register (§1.4).

**Honest worst case** (Free plan, and no dumps of your own): if the project is lost, deleted or corrupted,
everything stored in the app since launch is gone. That means:
- in-app transactions;
- journal and notes;
- settings and targets;
- snapshot history, which can never be rebuilt because history is never back-filled;
- uploaded disclosures and AI analyses.

What survives: each person's own Excel workbook (the input of record: re-import it) and market data (fetched again).
That is why §1.2 exists. Run it even on a paid plan; your own copy outside Supabase protects against losing the
project or the account.

### 1.2 Your own encrypted dumps (`make backup-prod`)

**One-time setup:**
1. **A gpg key pair on your machine** (if you have none):
   `gpg --quick-gen-key "Investments backups <you@…>" default default never`. Use a strong passphrase.
   **Back up the private key** (e.g. `gpg --export-secret-keys --armor <id>` into your password manager). Without it
   no dump can ever be decrypted.
2. **The read-only backup role** in the production database, as `postgres` (SQL editor or psql):
   `psql "<admin connection>" -v backup_password='<new strong password>' -f backend/deploy/backup_role.sql`.
   It can read every row (BYPASSRLS, which pg_dump needs) but write nothing: only SELECT is granted, and every
   transaction is read-only (tested). Its password lives only on your machine, never on Render or Vercel.
3. **A folder outside the repository**, e.g. `~/investments-backups` (the tool refuses any path inside the repo).
   Optionally sync it to an encrypted cloud folder; the dumps are already encrypted.
4. **Docker** installed (pg_dump/pg_restore run from the official `postgres:17-alpine` image, matching the server).

**Each backup** (weekly, and before any risky change or a migration you're unsure of):
```bash
export BACKUP_DIR=~/investments-backups BACKUP_GPG_RECIPIENT=<your key id or email>
export BACKUP_CHECK_EMAIL=<your app email>        # whose totals the restore test recomputes
export BACKUP_KEEP_DAYS=<the number on the Terms page>
read -rs BACKUP_DATABASE_URL && export BACKUP_DATABASE_URL   # postgresql://investments_backup.<ref>:<pw>@<session pooler>:5432/postgres
make backup-prod
unset BACKUP_DATABASE_URL
```

What it does:
- opens one read-only snapshot;
- counts rows per table and computes your portfolio totals with the app's own code (the **manifest**);
- streams `pg_dump` (schema `public`, the app's data) of that same snapshot straight into gpg. Plaintext never
  touches disk;
- writes `investments-<UTC>.dump.gpg` and `….manifest.json.gpg` with mode 600;
- deletes dumps older than `BACKUP_KEEP_DAYS`.

Nothing is printed except file names and counts.

**Retention:** keep your dumps no longer than the period stated on the Terms page (`BACKUP_KEEP_DAYS` =
`NEXT_PUBLIC_BACKUP_RETENTION_DAYS`). Otherwise deleted people would live on in your dumps longer than promised.

**What dumps do not contain:** Supabase's sign-in accounts (its own `auth` schema). After restoring a dump into a
new project, people simply sign in again with their email; their accounts are matched by email.

**Never commit a dump:** `.gitignore` excludes them, and the pre-commit scan refuses dump/backup/register files and
dump-like contents whatever the name.

### 1.3 Prove a restore (`make restore-test`)

```bash
make restore-test                 # the latest dump in BACKUP_DIR
make restore-test DUMP=~/investments-backups/investments-20261018T080000Z.dump.gpg
```

It decrypts the dump (gpg asks for your key's passphrase) and restores it into a **throwaway Postgres in Docker**
(removed afterwards). It checks every table's row count against the manifest, then recomputes the check user's
portfolio totals (value, invested, P&L, today's change, realised, dividends, holdings, transactions, snapshots,
latest snapshot) with the app's own code and compares them with the backup-time values. It prints
`restore test of …: PASS`, or each mismatch and exits 1. Do this monthly and after changing the backup setup. CI
runs the same backup → restore → verify cycle on a synthetic database on every push (`make test-backup`).

**Real restore into production** (only after an incident):
1. Turn on the kill switch "new sign-ins off" (Admin page).
2. Decrypt and restore into the production database as the `postgres` role:
   `gpg -d <dump> | pg_restore --clean --if-exists --no-owner --no-privileges -d "<admin connection>"`
   (or use a Supabase dashboard backup instead).
3. Re-apply the deletion register (§1.4).
4. `make restore-test` against the same dump, and a quick look at the Admin page; then turn sign-ins back on.

### 1.4 Deletion register after a restore (`make reapply-deletions`)

The private register from DEPLOY.md §18 is a CSV **outside the repository** (the tool refuses one inside it):
```
# deletion register (private)
deleted_at,user_id,email
2026-10-18,7,friend@example.com
```
After restoring **any** backup (yours or Supabase's):
```bash
read -rs REAPPLY_DATABASE_URL && export REAPPLY_DATABASE_URL   # the restored database (app role or postgres)
make reapply-deletions REGISTER=~/private/deletions.csv
```
Everyone in the register who exists in the restored database is deleted again, with all their data, invitation and
(if `SUPABASE_SERVICE_ROLE_KEY` is set) sign-in account. It's safe to run twice. Tested end to end: delete Bob →
restore a dump made before → Bob is back → re-apply → Bob is gone, everyone else's totals unchanged.

## 2. Uptime and cold starts

### 2.1 An external uptime monitor

Use any external HTTP monitor, e.g. **UptimeRobot**, **Better Stack (Uptime)** or **cron-job.org**. The free tiers are
enough. Settings:

| setting | value |
|---|---|
| URL | `https://<your Render service>/api/health` (production; optionally a second monitor for preview) |
| method / interval | GET, every 5 minutes |
| expect | HTTP **200** with body `{"status":"ok"}` |
| alert | email to you after 2 failed checks in a row |

`/api/health` is public and reveals nothing: `{"status":"ok"}` when the app is up and its database answers. It returns
HTTP **503** `{"status":"unavailable"}` when the app is up but the database is not (e.g. Supabase paused or
unreachable), and no answer at all when the app is down or asleep. It is excluded from rate limits and logged at
DEBUG only, so monitoring doesn't fill the logs. No key or token is needed; never put one in the monitor.

### 2.2 What to expect on the Render plan (⚠ verify on your plan)

- **Starter (the recommended production type, DEPLOY.md §6):** always on. The only restarts are deploys, your manual
  restarts and Render maintenance. Each takes well under a minute. Requests during a restart may fail briefly; the app
  retries reads on its own (below).
- **Free:** at the time of writing the service **sleeps after about 15 minutes without requests** and wakes on the next
  one. That takes roughly 30–60 seconds. Free instance hours per month are limited. While it sleeps, nothing runs:
  no daily refresh, no live prices. A 5-minute monitor keeps it awake (using up the free hours faster); check
  Render's current terms before relying on that.

**What people see during a cold start:** a bar at the top says *"The server is waking up (it sleeps when nobody has
used it for a while). This usually takes under a minute."* with **Retry now**. Pages that only read data retry by
themselves: after 1, 2, 4 and 8 seconds, then every 15 seconds, for up to 90 seconds. After that the bar says *"The
server is not responding right now…"* with **Retry**.

Saving (POST/PUT/DELETE) is never retried automatically, because it might have gone through. The person sees
*"…Your change was probably not saved: check, then try again in a minute."* An answer from the app itself (any
response with an `X-Request-ID`, including its own 503) is shown as the normal error with its request id. Only the
proxy's 502/503/504 or no answer at all count as "waking up" (`frontend/src/lib/wake.ts`, tested).

### 2.3 Scheduled jobs after downtime

The daily job (prices, NAVs, everyone's snapshot; 23:30 IST, `REFRESH_HOUR`/`REFRESH_MINUTE`) and live polling run
inside the backend process. Only one instance runs each job, under a database advisory lock. If the process was down
or asleep at 23:30:
1. On the next start, **catch-up** runs (`app/services/catchup.py`). It records every missed calendar date as a
   **snapshot gap** ("no snapshot: the app was not running"), then fetches current prices and takes today's snapshot
   for everyone.
2. Charts break the line at gaps. Nothing is interpolated or back-filled, ever: a missed day stays missed.
3. Live intraday polling simply resumes when someone has the app open during market hours. Missed ticks are not
   recreated.

A restart within the same day (e.g. a deploy at 23:35 that interrupted the job) just takes the missing snapshot on start.
Long outages show up as gaps, so you can see them on the History page and in **Sources › health**.

## 3. Kill switches (Admin page › Kill switches)

All switches are stored in the database and read on every request. They take effect on the next request, on every
instance, with **no redeploy**. Admins (`ADMIN_EMAILS`) are never locked out, so you can always switch them back.

| switch | effect | people see |
|---|---|---|
| **New sign-ins off** | Nobody can sign in for the first time: no new accounts, no first sign-in of an invited email. People who already signed in keep working. | "New sign-ins are paused by the admin. Please try again later." |
| **Pause everyone except admins** | Every non-admin request is refused (HTTP 503). Data untouched. `/api/health` still answers, so monitors don't alarm. | "The app is paused by the admin for maintenance. Please try again later." |
| **AI off for everyone** | No AI call for anyone (analysis, connection test, category suggestions, weekly job), whatever the per-person setting, own key or cap. | "AI analysis is switched off for everyone by the admin." |
| **Disable one person** (People table › disable) | Every request of that person is refused (HTTP 403); their data is kept. You can't disable yourself. | "Your account has been disabled by the admin." |

Note that a signed-in person's browser keeps its Supabase session. The switches act in the backend, so they apply at
once anyway. To also end sessions everywhere, sign the person out or rotate the JWT keys in Supabase (LAUNCH.md
incident runbook).

**Audit log.** Every switch change and every admin action goes to `admin_audit`: invites, removed invites, AI
settings, disabling, deletions, and also self-service account deletions. The Admin page lists the latest 100. Each
entry has the time, the admin's numeric id, the action and the target's numeric id. Details hold flags and counts
only; an invited email appears only as a 12-character hash. No addresses or figures. The same entries go to the log
as `admin_action` lines.
