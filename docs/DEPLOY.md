# Deploying the app

Frontend on **Vercel**, backend (Docker) on **Render**, database and sign-in on **Supabase**. Two fully separate
environments: **production** (`main`) and **preview** (pull requests). Why this setup: PLAN.md §16.

> Variable **names** only appear here. Never put a value in this file, in `.env.example`, in a commit, in a chat or in
> an issue. Values go into the dashboard of the platform that needs them.
>
> Dashboards change their wording from time to time; if a label below differs slightly, look for the same setting
> nearby.

**Contents:** 1 Environments · 2 Database role · 3 Email (SMTP) · 4 Encryption secret · 5 Supabase projects ·
6 Render backend · 7 Vercel frontend · 8 GitHub CI and branch protection · 9 Environment variables (all) ·
10 First deployment, in order · 11 How a push reaches production · 12 Rollback · 13 Custom domain (optional) ·
14 After each deploy

## 1. Two separate environments: production and preview

| | Production | Preview (pull requests) |
|---|---|---|
| Supabase project | `investments-prod` | `investments-preview`, a **separate project** |
| Database | prod project's Postgres | preview project's Postgres (test data only) |
| Backend service | prod service | preview service |
| Vercel env scope | **Production** | **Preview** |
| Users | real people, invited | you and test accounts only |

**Rule: preview deployments must never receive production database or Supabase credentials.**
- In Vercel, set each variable separately for the *Production* and *Preview* scopes. Never tick both scopes for
  `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` or `NEXT_PUBLIC_API_URL`; give Preview the preview
  project's values.
- The preview backend service gets the preview `DATABASE_URL`, `SUPABASE_URL` and (if used)
  `SUPABASE_SERVICE_ROLE_KEY`; never the production ones.
- Use different `FIELD_ENCRYPTION_KEY` values for production and preview.
- Don't share the production `ANTHROPIC_API_KEY` with preview. Leave AI off there, or use a separate key with its
  own spending limit.
- CI never needs any of these: tests use a throwaway Postgres started inside the CI job.
- The one-time data move (`app.tools.sqlite_to_postgres`) is run by you, from your machine, with the production
  `TARGET_DATABASE_URL` in your shell only. It refuses a database that already has accounts.
- If a production value is ever pasted into the wrong place, rotate it: create a new database password, a new
  Supabase key, or a new Anthropic key, and update production.

## 2. The database role (required for Row Level Security)

Row Level Security does not apply to superusers or roles with BYPASSRLS. On Supabase, don't connect the app as
`postgres`. Create the app role once per project (production and preview):

```bash
psql "<admin connection string from Supabase › Connect>" -v app_password='<new strong password>' \
     -f backend/deploy/app_role.sql
```

- The app connects as `investments_app` (`DATABASE_URL=postgresql+psycopg://investments_app:<password>@<host>:5432/postgres`).
- The release step (`alembic upgrade head`) runs as the same role, so it owns the tables. The per-user policies
  are FORCED, so they also apply to the owner.
- The backend **refuses to start** (outside development/test) if its role is a superuser or has BYPASSRLS. A
  wrong `DATABASE_URL` fails loudly instead of quietly turning off the second layer.
- Check by hand in the Supabase SQL editor:
  `select rolname, rolsuper, rolbypassrls from pg_roles where rolname = 'investments_app';` → `false, false`.

### Which connection string for what

Supabase › **Connect** offers a direct connection (port 5432; may be IPv6-only), a **session pooler** (port 5432,
IPv4) and a **transaction pooler** (port 6543, IPv4). Always connect as `investments_app` (never `postgres`) except
where noted.

| use | connection | why |
|---|---|---|
| Backend app (`DATABASE_URL` on Render) | **Session pooler** (recommended) or transaction pooler | Both are safe for user isolation: the per-request user is set per *transaction* (`set_config(..., true)` = `SET LOCAL`) at the start of every transaction, and the job lock is a transaction-level advisory lock. Tested through PgBouncer in transaction mode (`make test-pooler`). The session pooler is simplest because it also suits the release step. |
| Release step (`alembic upgrade head`, Render pre-deploy) | **Session pooler** or direct, never the transaction pooler | migrations are DDL in one long transaction. If the app uses the transaction pooler, set a separate `MIGRATE_DATABASE_URL` (session pooler) and make the pre-deploy command `DATABASE_URL="$MIGRATE_DATABASE_URL" alembic upgrade head`. |
| One-time data move (`sqlite_to_postgres`, from your machine) | **Session pooler** (or direct if your network has IPv6) | it migrates and then copies in one long transaction |
| Creating the app role (`app_role.sql`, as `postgres`) | direct or session pooler, user `postgres` | administrative, once |
| CI and local tests | local containers only | never a Supabase URL |

Behind a transaction pooler, anything set at *session* level would leak into other clients' transactions on the
same server connection (demonstrated by `test_negative_control_session_level_settings_do_leak_through_the_pooler`).
The app never does that. It also sets both `app.user_id` and `app.system` at the start of every transaction, so a
polluted pooled connection cannot change what it sees (tested).

## 3. Email for magic-link sign-in (SMTP)

Sign-in emails are sent by Supabase Auth. Supabase's built-in email sender is meant for trying things out: it
sends only a few emails per hour, and Supabase may restrict which addresses it delivers to. Check the current
limits in Supabase's docs before relying on it. For friends and family, set up your own SMTP sender:

1. Pick an email provider with SMTP (e.g. Resend, Postmark, Amazon SES, Brevo, or a mailbox provider's SMTP). Use
   a domain you control, and add the provider's SPF and DKIM DNS records so the links don't land in spam.
2. Supabase › **Authentication › Emails › SMTP Settings** (production project): enable custom SMTP. Enter host,
   port, username, password (the SMTP password lives only here), sender address and sender name.
3. Supabase › **Authentication › Rate limits**: set the email rate to suit 5–15 people (sign-ins are infrequent).
   Keep it low enough that a misbehaving client can't send hundreds of emails.
4. Supabase › **Authentication › Emails › Templates**: optionally adjust the "Magic link" and "Invite user" texts.
   Keep the link token placeholder as it is.
5. Test: invite yourself on a second address, then sign in from a private browser window.

The preview project can keep Supabase's built-in sender; only you and test accounts sign in there.

## 4. The encryption secret for people's own AI keys

`FIELD_ENCRYPTION_KEY` encrypts the optional Anthropic keys people store on their Account page (Fernet).
- **Where it lives:** only in the backend host's environment variables, for each environment separately. Never
  in Vercel, never in the repository, never in the database, never in logs. Generate one with:
  `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- **If it is not set:** storing an own key is disabled ("storing your own key is disabled on this server"). The
  shared app key still works for people the admin enabled.
- **If it changes or is lost:** stored own keys can no longer be decrypted. People who stored one see "stored key
  cannot be decrypted" and AI is blocked for them until they re-enter or remove their key on the Account page. It
  never silently falls back to the app's shared key (tested). Nothing else is affected.
- **Rotating it:** set the new value, tell the people who use their own key to re-enter it (the Admin page shows
  who has one), and remove the old value.
- **Backups:** the database backup contains only encrypted values. Keep the secret in your password manager,
  separately from database backups. Without it, those values are unreadable, which is the point.


## 5. Supabase projects (production and preview)

Do this twice: once named `investments-prod`, once `investments-preview`.

1. supabase.com › **New project**. Region: **Southeast Asia (Singapore)** (same region as the Render backend). Use a
   strong database password and store it in your password manager.
2. **Authentication › Sign In / Providers**:
   - turn **off** "Allow new users to sign up" (invite-only);
   - keep **Email** enabled;
   - turn off any providers you don't use.
3. **Authentication › URL Configuration**:
   - **Site URL**: the frontend URL. Production: your Vercel production URL or domain. Preview: the preview
     deployment URL pattern you use.
   - **Redirect URLs**: add `<frontend URL>/auth/callback`. For preview, a wildcard for Vercel preview URLs, e.g.
     `https://investments-*-<your-vercel-team>.vercel.app/auth/callback`.
4. **Authentication › Emails**: production uses custom SMTP (§3).
5. **Project Settings › API / Data API**: the app does not use Supabase's Data API (the backend reads Postgres
   directly). Turn it off, or remove `public` from the exposed schemas if the switch is not offered. Migration 0009
   also enables RLS on every table and revokes table access from `anon` and `authenticated`.
6. **Create the app role** (§2) in the SQL editor or with `psql`.
7. **Note these values** (they go into §9; never into git):
   - Project URL: `SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_URL`.
   - Publishable ("anon") key: `NEXT_PUBLIC_SUPABASE_ANON_KEY`. It is public by design.
   - Signing keys: new projects sign sessions with asymmetric keys. The backend verifies them via the project's
     public JWKS, so no secret is needed. Only if your project still uses the legacy shared secret, set
     `SUPABASE_JWT_SECRET`.
   - Service role key (optional, only for invite emails from the Admin page): `SUPABASE_SERVICE_ROLE_KEY`, backend
     only.
   - Database connection string for the app role: **Connect › Session pooler** (port 5432, IPv4; the direct
     connection may be IPv6-only, which Render can't reach). The pooler user name is usually
     `investments_app.<project-ref>`. Make it
     `DATABASE_URL=postgresql+psycopg://investments_app.<project-ref>:<app role password>@<pooler host>:5432/postgres`.
8. **Backups**: production on a paid plan has daily backups (and point-in-time recovery as an add-on). Details in
   the backups section (checkpoint 6c).

## 6. Render backend (production and preview)

Production service:
1. render.com › **New › Web Service** › connect GitHub › pick the repository.
2. **Name** `investments-api`, **Branch** `main`, **Root Directory** `backend`, **Runtime/Language** Docker (it uses
   `backend/Dockerfile`).
3. **Region**: Singapore. **Instance type**: Starter (always on). The free type sleeps after inactivity: cold
   starts, and the daily jobs don't run while asleep (gaps are recorded honestly, never back-filled).
4. **Environment variables**: the production backend set from §9.
5. **Advanced**:
   - **Health Check Path** `/api/health` (a deploy is promoted only when it answers 200);
   - **Pre-Deploy Command** `alembic upgrade head` (the release step; runs once per deploy as the app role).
     The app also checks migrations at start-up, so a missed release step can't run old code on an old schema;
   - **Auto-Deploy**: **After CI Checks Pass** (so a red build never deploys);
   - do **not** enable scaling or add instances: run one instance. Jobs are guarded by advisory locks, but the
     rate limiter and the live-price viewer signal live in memory.
6. **Create Web Service**. Watch the log for `database_role role=investments_app superuser=false bypassrls=false`.
   If the role can bypass RLS, the service refuses to start; fix `DATABASE_URL` (§2).
7. Never enable **Pull Request Previews** on this production service: Render copies its environment variables
   (production credentials) into each preview.

Preview service:
- Same steps with name `investments-api-preview`, the preview backend set from §9 (the **preview** Supabase project
  and database), and the Free instance type if you like.
- Optional: enable Pull Request Previews on this service only, if you want backend changes from a PR to get their
  own preview backend. They inherit the preview credentials only.

## 7. Vercel frontend

1. vercel.com › **Add New › Project** › import the repository.
2. **Root Directory** `frontend`; Framework preset Next.js (detected); build settings default.
3. **Environment Variables**: add each one separately for the **Production** scope and the **Preview** scope (§9).
   Never tick both scopes for the same value.
4. **Deploy**. Then **Settings › Git**: Production Branch `main`.
5. Copy the production URL into the production backend's `CORS_ORIGINS` and Supabase's Site URL. Point preview
   URLs at the preview backend (`CORS_ORIGIN_REGEX`) and the preview Supabase redirect URLs.

## 8. GitHub: CI and branch protection

- `.github/workflows/ci.yml` runs on every push and pull request:
  - **checks**: `make check`, the Postgres-only tests (RLS as the production role, advisory locks, the
    every-route cross-user attack, the data move) and the whole suite on Postgres;
  - **docker**: the backend image builds and runs as a non-root user.
  - CI needs no secrets.
- **Settings › Branches › Add branch protection rule** (or **Rules › Rulesets**) for `main`:
  - require a pull request before merging;
  - require status checks to pass: `checks` and `docker` (shown as "CI / checks", "CI / docker" after the first
    run), and require branches to be up to date;
  - do not allow bypassing the rules (include administrators); block force pushes and deletion.
- **Note:** for a *private* repository, branch protection and rulesets need a paid GitHub plan (Pro or Team). On
  GitHub Free:
  - Render still deploys only after checks pass (§6);
  - but a direct push to `main` would reach Vercel production without waiting. Work through pull requests and
    never push to `main` directly, or upgrade.

## 9. Environment variables (names only)

Backend (Render). The same names in both services, with each environment's own values:

| name | production | preview | notes |
|---|---|---|---|
| `ENV` | `production` | `preview` | unset or unknown counts as production |
| `DATABASE_URL` | prod app-role URL | preview app-role URL | never the `postgres` role |
| `SUPABASE_URL` | prod project | preview project | |
| `SUPABASE_JWT_SECRET` | only if legacy | only if legacy | |
| `SUPABASE_SERVICE_ROLE_KEY` | optional | optional | backend only; enables invite emails |
| `ADMIN_EMAILS` | your email | your email | |
| `CORS_ORIGINS` | Vercel prod URL / domain | (optional) | exact origins, comma-separated |
| `CORS_ORIGIN_REGEX` | — | Vercel preview URL pattern | |
| `ANTHROPIC_API_KEY` | optional | separate key or unset | never the production key in preview |
| `CLAUDE_MODEL` | optional | optional | default model id |
| `FIELD_ENCRYPTION_KEY` | own value | different value | §4 |
| `LOG_LEVEL`, `LOG_FORMAT` | optional | optional | `LOG_FORMAT=json` suits Render's log search |
| `SENTRY_DSN` | optional | optional (separate Sentry project) | error monitoring; events are scrubbed (below) |
| `MAX_REQUEST_BYTES`, `RATE_LIMITS_ENABLED`, `SOURCE_TIMEOUT_SECONDS` | optional | optional | defaults are fine |

Never set on Render: `DEV_AUTH`, `DEV_USER_EMAIL`, `BACKEND_URL`. Render sets `PORT` itself.

Frontend (Vercel), per scope:

| name | Production scope | Preview scope |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | production backend URL | preview backend URL |
| `NEXT_PUBLIC_SUPABASE_URL` | prod project URL | preview project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | prod publishable key | preview publishable key |

Never set on Vercel: `NEXT_PUBLIC_DEV_AUTH`, `BACKEND_URL`, or any secret. Everything `NEXT_PUBLIC_*` is visible in
the browser.

GitHub: no secrets.

## 10. First deployment, in order

1. Supabase preview project (§5), then the production project (§5), each with its app role (§2). Set up SMTP
   for production (§3).
2. Render preview service, then the production service (§6). Wait for `/api/health` to answer
   `{"status":"ok"}`.
3. Vercel project with both scopes (§7). Set `CORS_ORIGINS` / `CORS_ORIGIN_REGEX` on the backends to the
   resulting URLs, and the Supabase URL configuration.
4. GitHub branch protection (§8).
5. Move your existing data (once), **before anyone signs in**, from your machine, into the **empty** production database. Run it as the app
   role, with the URL only in your shell:
   ```bash
   cd backend
   read -rs TARGET_DATABASE_URL && export TARGET_DATABASE_URL   # paste the production app-role URL
   .venv/bin/python -m app.tools.sqlite_to_postgres --sqlite ../data/investments.db --owner-email <your email>
   unset TARGET_DATABASE_URL
   ```
   It refuses a database that already has accounts, so do it before step 6. It must print "Identical totals."
   Your first sign-in (step 6) then links your Supabase login to the copied account by email.
6. Invite yourself in Supabase (**Authentication › Users › Invite**) with the address in `ADMIN_EMAILS`, open the
   frontend, sign in, check the Admin page.
7. Invite friends: Supabase invite + Admin page › Invite (or only the Admin page if
   `SUPABASE_SERVICE_ROLE_KEY` is set). Enable AI per person if you want.

## 11. How a push reaches production

```
feature branch ──push──▶ GitHub Actions: checks + docker      Vercel: preview deployment
       │                    (no secrets)                        (preview backend + preview Supabase only)
       └─ pull request ─▶ review; both checks green (required)
                              │
                         merge to main
                              │
            ┌─────────────────┴──────────────────┐
     GitHub Actions on main                  Vercel builds main
            │ green                           ─▶ production frontend
     Render (After CI Checks Pass)
            │ pre-deploy: alembic upgrade head (as the app role)
            │ start: RLS role check, auth config check (refuses if unsafe)
            │ health check /api/health = 200
            ▼
     production backend switches to the new version (the old one keeps serving until then)
```

## 12. Rollback

- **Frontend**: Vercel › Deployments › pick the last good production deployment › **Instant Rollback** /
  **Promote to Production**.
- **Backend**: Render › the service › Events/Deploys › the last good deploy › **Rollback**. The previous image
  starts with the same environment.
- **Database**: a rollback of code does not undo migrations. Keep migrations backward-compatible (add columns and
  tables first; remove only in a later release) so the previous version still runs. Migration 0008 (multi-user) is
  one-way; recovering from it means restoring a backup (backups section, 6c).
- **Then fix forward**: `git revert <commit>` on a branch › pull request › merge. Rollbacks in dashboards are
  temporary; the next deploy from `main` replaces them.

## 13. Custom domain (optional)

1. Vercel › Project › Settings › Domains › add `invest.example.com`. Create the DNS record Vercel shows (CNAME or A).
2. Render › production service › Settings › Custom Domains › add `api.invest.example.com`. Create the CNAME Render
   shows. TLS certificates are issued automatically by both.
3. Update `NEXT_PUBLIC_API_URL` (Vercel Production) to `https://api.invest.example.com`, then redeploy the
   frontend (`NEXT_PUBLIC_*` values are built in).
4. Update `CORS_ORIGINS` (Render production) to `https://invest.example.com`.
5. Supabase production › URL Configuration: Site URL and Redirect URL `https://invest.example.com/auth/callback`.
6. If you use custom SMTP, send from the same domain (SPF/DKIM).

## 14. After each deploy

- `https://<backend>/api/health` → `{"status":"ok"}` (uptime monitoring: backups/operations section, 6c).
- Sign in, open the Dashboard and the Admin page.
- Render log: one `database_role ... bypassrls=false` line at start, no tracebacks (`level=ERROR`).

## 15. What reaches logs and error monitoring

- **Render's log stream is the app's console output**: the same lines as `logs/app.log`. They carry the request id
  (`rid=`), the numeric user id (`uid=`), the route **template** (`/api/admin/invites/{email}`, never the raw path),
  status, durations, counts, numeric security ids and error classes.
- They never carry financial figures, workbook contents, journal or note text, keys or tokens, or emails. A full
  user flow is tested for this (`tests/test_privacy_logs.py`), on top of the redaction filter.
- **Sentry** (only if `SENTRY_DSN` is set): exceptions only, no log lines, breadcrumbs, performance traces or
  sessions. Each event keeps the request method and route, the numeric user id, and the exception type with its
  message scrubbed:
  - keys and tokens redacted;
  - emails replaced with `<email>`;
  - numbers of 3+ digits replaced with `<n>`;
  - quoted text replaced with `<text>`.

  Stack frames keep file, line and function only. A synthetic event full of private values is checked in the
  tests. In the Sentry project settings, also turn on "Data Scrubber" and "Prevent Storing of IP Addresses" as a
  second layer.

## 16. Smoke test after each deploy (`make smoke`)

Run it after every deploy of the **preview** backend (and therefore before promoting to production). It signs in
two dummy accounts and checks, against the real deployment, that one never sees the other's data:
1. B uploads a workbook with a freshly generated canary holding (unique symbol, name and note).
2. A calls every GET route with B's real ids, the Excel export, the status endpoints (source health, market
   status), the admin endpoints (must be 403) and deliberate error requests (B's ids in POST/PUT/DELETE).
3. No response may contain the canary and nothing may answer 5xx.
4. B's canary is removed again.

One-time setup, preview project only:
1. Supabase **preview** › Authentication › Users › **Add user** › *Create new user* twice (e.g.
   `smoke-a@<your domain>`, `smoke-b@<your domain>`) with long random passwords, "Auto Confirm User" on. Password
   sign-in uses the Email provider, which is on by default. Never create password users in production.
2. In the **preview** app, sign in as admin › Admin › invite both emails (don't enable AI for them). Account A
   must not be an admin.
3. Keep the passwords in your password manager.

Each run, from your machine (values only in your shell):
```bash
export SMOKE_TARGET=preview
export SMOKE_SUPABASE_URL=<preview project URL>  SMOKE_SUPABASE_ANON_KEY=<preview publishable key>
export SMOKE_PRODUCTION_SUPABASE_URL=<production project URL>   # optional guard: refuses if they match
export SMOKE_A_EMAIL=... SMOKE_B_EMAIL=...
read -rs SMOKE_A_PASSWORD && export SMOKE_A_PASSWORD
read -rs SMOKE_B_PASSWORD && export SMOKE_B_PASSWORD
make smoke URL=https://<preview backend>
```
It prints `smoke: N requests as A checked for B's canary; PASS` and exits 0, or lists each problem and exits 1.
Check out the same commit that is deployed, because the route list comes from the code. The same logic runs in
the test suite (`tests/test_smoke_tool.py`), including a run where it catches a deliberately leaking app.
