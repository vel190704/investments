# Deploying the app

> **Status:** these sections cover the multi-user core (checkpoint 6a): the database role, email sign-in, the
> encryption secret, and keeping preview separate from production. The full click-by-click guide (Supabase, Vercel,
> backend host, CI, every environment variable, custom domain, rollback, how a push reaches production) is added in
> checkpoint 6b.
>
> Variable **names** only appear here. Never put a value in this file, in `.env.example`, in a commit, in a chat or in
> an issue. Values go into the dashboard of the platform that needs them.

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
