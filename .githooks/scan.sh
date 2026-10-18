#!/usr/bin/env bash
# Refuses staged secrets and data files. Called by .githooks/pre-commit; tested in backend/tests/test_commit_guard.py.
set -euo pipefail

added=$(git diff --cached -U0 --no-color | grep -E '^\+' | grep -v '^+++' || true)

# 1) API keys
if printf '%s\n' "$added" | grep -Eq 'sk-ant-[A-Za-z0-9_-]{10,}|ANTHROPIC_API_KEY=[A-Za-z0-9_-]{20,}'; then
  echo "pre-commit: refusing — a secret (Anthropic API key) appears in the staged changes." >&2
  echo "Keep keys in .env (git-ignored), never in tracked files." >&2
  exit 1
fi
# 2) database URLs with a real password (throwaway test passwords and <placeholders> are fine)
if printf '%s\n' "$added" | grep -Eo 'postgres(ql)?(\+psycopg)?://[^:/[:space:]"'"'"']+:[^@[:space:]"'"'"']+@' \
   | grep -Ev ':(localtest|pooler_app_test|x|<[^>]*>|\$\{?[A-Za-z_]+\}?|\{[a-z_]+\})@$' | grep -q .; then
  echo "pre-commit: refusing — a database URL with a password appears in the staged changes." >&2
  exit 1
fi
# 3) file names: env files, dumps, encrypted backups, deletion registers
for f in $(git diff --cached --name-only --diff-filter=AM); do
  base="${f##*/}"
  case "$base" in
    .env|.env.*) [ "$base" = ".env.example" ] || { echo "pre-commit: refusing to commit $f (env file)" >&2; exit 1; } ;;
    *.dump|*.dump.*|*.pgdump|*.backup|*.gpg|*.age|*.pgp|*.sql.gz|deletions*.csv|*deletion-register*)
      echo "pre-commit: refusing to commit $f (backup, dump or deletion register: keep these outside the repo)" >&2
      exit 1 ;;
  esac
  # 4) file contents: database dumps and PGP material, whatever the file is called
  if git show ":$f" 2>/dev/null | head -c 4096 | LC_ALL=C grep -aqE '^PGDMP|^-- PostgreSQL database dump|-----BEGIN PGP (MESSAGE|PRIVATE KEY BLOCK)-----'; then
    echo "pre-commit: refusing to commit $f (looks like a database dump or PGP data)" >&2
    exit 1
  fi
done
