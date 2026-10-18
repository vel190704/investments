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
