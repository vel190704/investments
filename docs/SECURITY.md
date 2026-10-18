# Security review (6c)

What was checked before launch, where it is tested, and what was found. Re-run with `make audit`. CI runs the
"security" job on every push.

## Automated scans

| scan | scope | in CI | result (2026-10-18) |
|---|---|---|---|
| **gitleaks** v8.24.3 (Docker) | every commit in the full git history | blocking | 4 findings, all reviewed false positives (below); 0 open |
| **pip-audit** 2.10.1 | `backend/requirements.txt` + `requirements-dev.txt` (all pinned) | blocking | no known vulnerabilities |
| **npm audit --omit=dev** | production frontend dependencies | blocking (high and above) | 0 vulnerabilities |
| **npm audit** (all) | including build and dev tooling | report only (job summary) | 1 advisory, 9 dependency paths (below) |
| pre-commit scan (`.githooks/scan.sh`) | each commit, before it is made | local hook | refuses keys, DB URLs with passwords, `.env*`, dumps, PGP data, deletion registers (tested) |

**gitleaks false positives** (fingerprints in `.gitleaksignore`, each with its reason):
- the HS256 secret the tests sign fake Supabase tokens with;
- the sample input of the log-redaction test;
- the published RFC 6238 test vector in the broker tests removed in Phase 5.

None is or was a real credential. Any **new** finding fails CI.

**npm advisory GHSA-vfj7-8cjw-p6xm (`braces`, high: stack exhaustion with deeply nested glob patterns).** No fixed
version exists (all versions are affected). It reaches us only through build tooling: `fast-glob` under
`eslint-config-next` and the `shadcn` CLI. These run on the developer machine and in CI or the build, over the
repository's own file patterns. No untrusted input reaches them and nothing of them ships to the browser. Fix
applied: `shadcn` moved to devDependencies (it was listed as a runtime dependency; only its CSS is imported, at
build time), so the production dependency tree is clean. Kept report-only; revisit when a fixed `braces` is released.

**When a new finding appears:**
1. Upgrade the package (pin the fixed version) and run `make check`.
2. If no fix exists and it is not reachable, document it here. Only then ignore it, narrowly:
   - pip-audit: `--ignore-vuln <ID>` in the Makefile and CI with a comment;
   - npm: an `overrides` entry if a safe version exists.

A blocking failure also blocks `make release`, which needs a green CI.

## Verified and tested

| check | how it is enforced | test |
|---|---|---|
| API docs off when deployed | `/docs`, `/redoc`, `/openapi.json` not created unless ENV is development/test | `test_security_review.py::test_deployed_app_publishes_no_api_docs` (the real app rebuilt with production settings) |
| CORS only for the frontend origins | `CORS_ORIGINS` exact list (no `*`, refused) + optional preview regex; no credentials | `test_deployed_app_cors_headers_and_limits`, `test_hardening.py::test_cors_allows_only_configured_origins` |
| Security headers | nosniff, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, CSP `default-src 'none'; frame-ancestors 'none'`, `Cache-Control: no-store`, HSTS outside dev; frontend CSP in `next.config.ts` | same, plus `test_hardening.py` |
| Upload size limit | 413 above `MAX_REQUEST_BYTES` (10 MB) before any work; each upload route also checks 10 MB after reading (chunked bodies) | `test_deployed_app_cors_headers_and_limits`, `test_upload_route_limit_without_a_content_length` |
| No production credentials in preview | ENV=preview refuses to start unless `SUPABASE_URL`, `DATABASE_URL` (direct or pooler) and a JWT service key all belong to a project on `PREVIEW_ALLOWED_SUPABASE_REFS`. Empty = refuse. Messages name project refs only, never passwords or keys. Frontend: sign-in disabled in a Vercel preview not on `NEXT_PUBLIC_PREVIEW_SUPABASE_REFS` | `test_preview_refuses_production_credentials` (7 cases), `frontend/src/lib/envguard.test.ts` |
| Authentication fails closed | unset or unknown ENV = production; dev user only with `DEV_AUTH=1` and ENV development/test | `test_auth_accounts.py::test_authentication_fails_closed` |
| Cross-user isolation | ORM filter on every query + Postgres RLS (forced, every per-user table) | `test_isolation.py` (every route), `test_postgres.py` (RLS alone, RLS on every per-user table) |
| Private values never in logs or Sentry | structured logs with ids only; Sentry scrubbing; feedback never logged | `test_privacy_logs.py`, `test_canary.py`, `test_feedback.py` |
| Rate limits | failed sign-ins per IP; uploads, AI tests, invites per session; feedback per user | `test_hardening.py`, `test_feedback.py` |
