# Launch

The go-live checklist (§1), the incident runbook (§2) and where friends and family read how to use the app (§3).
Details live in [DEPLOY.md](DEPLOY.md) (setup), [OPERATIONS.md](OPERATIONS.md) (backups, uptime, kill switches)
and [SECURITY.md](SECURITY.md) (review). Names only here: values stay in your password manager.

## 1. Go-live checklist (in order)

Tick each box only when you have seen the expected result.

**Before anything is created**
- [ ] **1. Rotate the Anthropic key that was in your local `.env`.** Anthropic Console › API keys: create a new key,
  delete the old one, put the new one in your password manager.
  *Expected:* the old key is listed as revoked or is gone. `make check` still passes locally (tests never read `.env`).
- [ ] **2. CI is green on `main`.** GitHub › Actions › the latest run on `main`.
  *Expected:* the jobs **checks**, **security** and **docker** are all green. The "npm audit including build tooling"
  step may show the known report-only finding (SECURITY.md).

**Supabase** (DEPLOY.md §2, §3, §5)
- [ ] **3. Preview project, then production project**, both in Singapore.
  *Expected:* two projects; Authentication › "Allow new users to sign up" is **off** in both.
- [ ] **4. App role in each project** (DEPLOY.md §2).
  *Expected:* `select rolbypassrls, rolsuper from pg_roles where rolname = 'investments_app'` returns `f, f`.
- [ ] **5. SMTP for production** (DEPLOY.md §3).
  *Expected:* a test magic link to yourself arrives from your sender address, not Supabase's default sender.
- [ ] **6. Backups on your plan** (OPERATIONS.md §1.1, ⚠ verify on your plan).
  *Expected:* you know the retention in days from Database › Backups. You will use that number in steps 11 and 19.

**Secrets you generate** (stored in your password manager only)
- [ ] **7. `FIELD_ENCRYPTION_KEY`, one per environment** (DEPLOY.md §4).
  *Expected:* two different values saved, labelled production and preview.
- [ ] **8. Backup key and role** (OPERATIONS.md §1.2): gpg key pair (private key exported to the password manager),
  `backup_role.sql` run on production.
  *Expected:* `gpg --list-secret-keys` shows the key; connecting as `investments_backup` and running a `DELETE`
  fails with "read-only".

**Render** (DEPLOY.md §6, §9)
- [ ] **9. Preview service** with `ENV=preview` and `PREVIEW_ALLOWED_SUPABASE_REFS=<preview ref>`.
  *Expected:* the deploy log shows migrations up to `0012_kill_switches`. `https://<preview api>/api/health` returns
  `{"status":"ok"}`. Optional proof: set `SUPABASE_URL` to the production project and redeploy. The service refuses
  to start ("not on PREVIEW_ALLOWED_SUPABASE_REFS"). Then set it back.
- [ ] **10. Production service** (Starter, Singapore, health check path `/api/health`, `ENV=production`).
  *Expected:* `/api/health` returns `{"status":"ok"}`. `https://<api>/docs` and `/openapi.json` return **404**.
  `curl -sI https://<api>/api/health` shows `strict-transport-security`, `x-frame-options: DENY` and
  `content-security-policy`.

**Vercel** (DEPLOY.md §7, §9)
- [ ] **11. Both scopes' variables**, including `NEXT_PUBLIC_BACKUP_RETENTION_DAYS` (from step 6) and, in the
  Preview scope, `NEXT_PUBLIC_PREVIEW_SUPABASE_REFS`. "Automatically expose System Environment Variables" is on.
  *Expected:* the production URL shows the sign-in page. `/terms` shows your retention days. `/help` opens without
  signing in.
- [ ] **12. CORS and Supabase URLs.** Set `CORS_ORIGINS` (production) and `CORS_ORIGIN_REGEX` (preview) on Render, and
  Site URL plus redirect URLs in Supabase.
  *Expected:* after signing in, the browser console shows no CORS errors. A request from another origin gets no
  `access-control-allow-origin` header.

**GitHub and monitoring**
- [ ] **13. Release flow** (DEPLOY.md §17, or branch protection §8).
  *Expected:* `make release` on a commit whose CI is not green refuses with the reason.
- [ ] **14. Uptime monitor** on `https://<api>/api/health` every 5 minutes (OPERATIONS.md §2.1).
  *Expected:* the monitor is green. Pausing the Render service for a minute triggers the alert email; resume it.
- [ ] **15. Sentry (optional)** with `SENTRY_DSN` on Render (DEPLOY.md §15).
  *Expected:* the project receives no events during normal use.

**Your account and data**
- [ ] **16. Move your data** into the empty production database before anyone signs in (DEPLOY.md §10 step 5).
  *Expected:* the tool prints "Identical totals."
- [ ] **17. Sign in as the admin** (the address in `ADMIN_EMAILS`).
  *Expected:* the Dashboard shows the same totals as locally. The Admin page lists you, all **kill switches are
  off**, and the audit log is empty or shows only your actions.
- [ ] **18. Smoke test the preview:** `make smoke URL=<preview frontend>` (DEPLOY.md §16).
  *Expected:* `PASS`.
- [ ] **19. First backup and a proven restore:** `make backup-prod` with `BACKUP_KEEP_DAYS` equal to step 6, then
  `make restore-test` (OPERATIONS.md §1.2–1.3).
  *Expected:* two `.gpg` files with mode 600 outside the repo; `restore test of …: PASS`.
- [ ] **20. Deletion register:** create the private CSV outside the repo with its header line (OPERATIONS.md §1.4).
  *Expected:* the file exists, mode 600. It is not in any git repository.
- [ ] **21. Kill switch drill:** Admin page › turn **New sign-ins off** on, then off again.
  *Expected:* the audit log shows `new_signins_off_on` and `new_signins_off_off` with your numeric id.
- [ ] **22. Feedback works:** Send feedback from any page.
  *Expected:* it appears on the Admin page under Feedback; **mark as done** moves it to "done". Render's log shows
  `feedback_received` with a length, never the text.

**Go live, gently**
- [ ] **23. Invite one friend first.** Admin page › Invite (plus a Supabase invite if no service key). Send them the
  link to `/help`. Ask them to sign in, import their workbook and use the app for about a week.
  *Expected:*
  - they sign in with the emailed link;
  - the Admin page shows them as "signed in" with row counts;
  - Render's log has no `level=ERROR` lines for their numeric id;
  - any feedback reaches the Admin page.

  Only then invite the next two or three people, then the rest, a few at a time.

## 2. Incident runbook

Write down what you do, with times, as you go (a note in your password manager is fine). It is your record for the
people affected.

### 2.1 Suspected cross-user data exposure (someone saw data that wasn't theirs)

1. **Contain (minutes).** Admin page › **Pause everyone except admins**. Every member request is refused at once,
   with no redeploy. If you are not sure the admin path is safe either, suspend the Render production service.
2. **Rotate keys.**
   - Supabase › Project Settings › JWT signing keys: rotate, then revoke the old key. This ends every session.
   - The app role's database password: `ALTER ROLE investments_app PASSWORD '…'`, then update `DATABASE_URL` on
     Render.
   - `SUPABASE_SERVICE_ROLE_KEY`, if set.
   - The Anthropic key, if you suspect it too (§2.2).
3. **Review.**
   - Render › Logs for the period: filter on `uid=`. Look for one numeric id requesting routes with ids it doesn't
     own, unusual 200s, or `level=ERROR`.
   - Admin page › audit log: unexpected `user_ai_changed`, `invite_added`, `members_paused_off` and the like.
   - Sentry, if enabled.
   - Reproduce on **preview**, never production: `make test-postgres` and the cross-user attack tests
     (`test_isolation.py`, `test_postgres.py`) against the code that was deployed.
4. **Fix and verify.** Fix on a branch with a test that fails before the fix. CI green, then `make release`, then
   `make smoke` on preview. Turn the pause off only after the fix is live.
5. **Notify the affected people** promptly and plainly:
   - what happened and when;
   - what may have been seen (which data, by how many people);
   - what you have done;
   - what they can do (e.g. delete their account; export first).

   Don't speculate; correct it later if you learn more. Personal data exposure may carry legal duties to report
   (in India, under the Digital Personal Data Protection Act, 2023). Check what applies to you.
6. **Restore only if data was changed or destroyed** (OPERATIONS.md §1.3), then re-apply the deletion register
   (§1.4).

### 2.2 Leaked API key or secret

| leaked | do now | then |
|---|---|---|
| `ANTHROPIC_API_KEY` | Console › revoke it; Admin page › **AI off for everyone** | new key on Render (the service restarts); AI back on; check usage in the Anthropic Console |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase › API keys › rotate (or disable that secret key) | new value on Render; check Authentication › Users for accounts you didn't create |
| database password (app or backup role) | `ALTER ROLE … PASSWORD …` as `postgres` | new `DATABASE_URL` on Render (the backup URL lives only on your machine) |
| `FIELD_ENCRYPTION_KEY` | treat people's own stored AI keys as exposed | §2.5 (rotate the key); ask people who stored one to revoke it with their provider |
| `SENTRY_DSN` | Sentry › Client Keys › revoke | new DSN on Render (low risk: it only allows sending events) |
| a secret committed to git | rotate it first (history is already copied) | then remove it from history if you like; CI's gitleaks job shows where it is |

### 2.3 Bad deploy

1. **Roll back** (DEPLOY.md §12):
   - Render › Deploys › last good › **Rollback**;
   - Vercel › Deployments › last good › **Promote to Production**.

   Migrations 0011 and 0012 only add tables or columns, so the previous backend runs on the new schema.
2. If the backend is crash-looping and rollback is not enough, **Pause everyone except admins** (if it starts at all)
   or suspend the service. The uptime monitor tells you when it is back.
3. Fix forward: `git revert <commit>` on a branch, then pull request, CI green, `make release`.
4. If a migration damaged data: restore (OPERATIONS.md §1.3) and re-apply the deletion register.

### 2.4 Deletion request

DEPLOY.md §18 has the full procedure. In short:
1. Verify the requester: the request comes from their invited email.
2. Offer **Account › Export my data** first.
3. Admin page › People › **delete all data…** (type their email).
4. Remove their Supabase sign-in account if the service key is not set.
5. Add a line to your private deletion register (`deleted_at,user_id,email`).
6. Confirm in writing, mentioning that backups expire within the retention stated on the Terms page.

The audit log records `user_deleted` with their numeric id.

### 2.5 Lost encryption key

- **`FIELD_ENCRYPTION_KEY` lost or rotated:** only people's own AI keys are encrypted with it; nothing else is.
  1. Generate a new key and set it on Render.
  2. Stored own keys can no longer be read. The app then refuses to use them; it never falls back to the app's key
     (tested).
  3. Ask those people to enter their key again on the Account page. Admin page › People shows who had one.
- **Backup gpg private key lost:** every existing dump is unreadable, and nothing can recover it.
  1. Make a new key pair (export the private key to your password manager this time).
  2. Set `BACKUP_GPG_RECIPIENT`, run `make backup-prod` and `make restore-test` at once.
  3. Delete the old, useless dumps.

  Until the new backup exists, your only backups are Supabase's own (if your plan has them).
- **Lost access to the password manager:** that is why the recovery codes for it are kept offline. Without them,
  treat every secret as lost:
  1. rotate everything in §2.2;
  2. generate new encryption keys (above);
  3. take a new backup.

## 3. For friends and family

The app has a plain-language guide at **`/help`** ("How to use" in the menu, in the footer of every page, and on the
sign-in page). It is readable before signing in, so you can send the link with the invitation. It covers:
- what the app is and isn't;
- signing in with the emailed link;
- filling in the Excel template;
- importing (preview first, then Confirm) and confirming Mappings;
- the monthly routine and the main pages;
- privacy, and what to do when something looks wrong ("server is waking up", request ids, Send feedback).
