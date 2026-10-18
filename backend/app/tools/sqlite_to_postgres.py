"""One-time: move a single-user SQLite database into the (multi-user) Postgres database, into one account.

    cd backend && .venv/bin/python -m app.tools.sqlite_to_postgres \\
        --sqlite ../data/investments.db --postgres "$TARGET_DATABASE_URL" --owner-email you@example.com

What it does (the SQLite file itself is never modified):
1. copies the SQLite file to a scratch file and migrates the copy to the latest schema (0008 assigns all rows to an
   owner account);
2. migrates the target Postgres to the latest schema; it must hold no user data yet;
3. copies every table, keeping ids, and gives the owner account --owner-email (role admin);
4. resets Postgres id sequences;
5. computes the owner's totals on both sides (value, invested, P&L, holdings, transactions, snapshots, latest
   snapshot) and exits non-zero unless they are identical.
Secrets: the target URL is read from the argument or TARGET_DATABASE_URL and never printed.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, func, select, text

TOTAL_KEYS = ("total_value_paise", "total_invested_paise", "invested_in_priced_paise", "pnl_paise",
              "today_change_paise", "realised_paise", "dividends_paise", "open_holdings", "transactions", "snapshots",
              "latest_snapshot")


def totals(url: str, email: str) -> dict:
    """The owner's portfolio totals, computed by the app's own services on the given database."""
    from app import db
    from app.models import PortfolioSnapshot, Transaction, User
    from app.services.portfolio import load_rows, summary

    db.configure(url)
    with db.session_scope(system=True) as s:
        uid = s.scalar(select(User.id).where(func.lower(User.email) == email.lower()))
    if uid is None:
        raise SystemExit(f"no account {email!r} in that database")
    with db.session_scope(user_id=uid) as s:
        sm = summary(s)
        snaps = list(s.scalars(select(PortfolioSnapshot).order_by(PortfolioSnapshot.snapshot_date)))
        latest = snaps[-1] if snaps else None
        out = {
            **{k: sm[k] for k in ("total_value_paise", "total_invested_paise", "invested_in_priced_paise", "pnl_paise",
                                  "realised_paise", "dividends_paise")},
            "today_change_paise": sm["today_change"]["paise"],
            "open_holdings": len(load_rows(s)[0]),
            "transactions": s.scalar(select(func.count()).select_from(Transaction)),
            "snapshots": len(snaps),
            "latest_snapshot": (latest.snapshot_date.isoformat(), latest.total_value_paise, latest.total_invested_paise)
            if latest else None,
        }
    db.get_engine().dispose()
    return out


def copy_all(sqlite_url: str, pg_url: str, owner_email: str) -> dict:
    from app.db import Base
    import app.models  # noqa: F401  (register tables)

    src = create_engine(sqlite_url)
    dst = create_engine(pg_url)
    counts = {}
    with src.connect() as s, dst.begin() as d:
        d.execute(text("SELECT set_config('app.system', 'on', true)"))
        existing = d.execute(text("SELECT count(*) FROM users")).scalar()
        if existing:
            raise SystemExit("the target database already has accounts; run this only into an empty database")
        for t in Base.metadata.sorted_tables:  # parents first
            rows = [dict(r._mapping) for r in s.execute(select(t))]
            if t.name == "users":
                for r in rows:
                    if r["role"] == "admin" and r["email"].endswith("@localhost"):
                        r["email"] = owner_email.lower()
            for i in range(0, len(rows), 500):
                d.execute(t.insert(), rows[i:i + 500])
            counts[t.name] = len(rows)
        for t in Base.metadata.sorted_tables:  # keep future ids above the copied ones
            pk = list(t.primary_key.columns)
            if len(pk) == 1 and pk[0].autoincrement is not False and str(pk[0].type) == "INTEGER":
                d.execute(text(f"SELECT setval(pg_get_serial_sequence('{t.name}', '{pk[0].name}'), "
                               f"COALESCE((SELECT MAX({pk[0].name}) FROM {t.name}), 0) + 1, false)"))
    src.dispose()
    dst.dispose()
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--sqlite", required=True, help="path to the single-user SQLite file (not modified)")
    ap.add_argument("--postgres", default=os.environ.get("TARGET_DATABASE_URL"),
                    help="target Postgres URL (or TARGET_DATABASE_URL); never printed")
    ap.add_argument("--owner-email", required=True, help="the account that will own the data (yours)")
    args = ap.parse_args(argv)
    if not args.postgres or not args.postgres.startswith("postgresql"):
        print("a postgresql+psycopg:// target URL is required", file=sys.stderr)
        return 2
    from app.migrate import migrate

    with tempfile.TemporaryDirectory() as d:
        copy = Path(d) / "source-copy.db"
        shutil.copy(args.sqlite, copy)
        sqlite_url = f"sqlite:///{copy}"
        print("1/5 migrating a copy of the SQLite file to the latest schema …")
        migrate(create_engine(sqlite_url), backup=False)
        before = totals(sqlite_url, os.environ.get("LEGACY_OWNER_EMAIL") or "owner@localhost")
        print("2/5 migrating the target Postgres to the latest schema …")
        migrate(create_engine(args.postgres), backup=False)
        print("3/5 copying tables …")
        counts = copy_all(sqlite_url, args.postgres, args.owner_email)
        print("    " + ", ".join(f"{k}={v}" for k, v in counts.items() if v))
        print("4/5 sequences reset; 5/5 comparing totals …")
        after = totals(args.postgres, args.owner_email)
    width = max(len(k) for k in TOTAL_KEYS)
    print(f"\n{'':{width}}  {'SQLite (before)':>28}  {'Postgres (after)':>28}")
    ok = True
    for k in TOTAL_KEYS:
        same = before[k] == after[k]
        ok &= same
        print(f"{k:{width}}  {str(before[k]):>28}  {str(after[k]):>28}  {'=' if same else 'DIFFERENT'}")
    print("\nIdentical totals." if ok else "\nTOTALS DIFFER: do not use the target; investigate first.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
