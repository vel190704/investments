"""Encrypted backups of the production database, a proven restore, and re-applying deletions after a restore.

    make backup-prod                      # pg_dump -> gpg-encrypted file outside the repo (+ encrypted manifest)
    make restore-test [DUMP=path]         # restore the latest (or given) dump into a throwaway Postgres and verify
    make reapply-deletions REGISTER=path  # after restoring a backup: delete again everyone in the private register

Environment (values only in your shell or password manager; docs/OPERATIONS.md):
  BACKUP_DATABASE_URL    libpq URL of the read-only backup role (backend/deploy/backup_role.sql), session pooler
  BACKUP_GPG_RECIPIENT   your gpg public key (id or email); dumps are encrypted to it and only you can decrypt
  BACKUP_DIR             where dumps go; must be OUTSIDE the repository (default ~/investments-backups)
  BACKUP_CHECK_EMAIL     whose portfolio totals the restore test recomputes (default: first ADMIN_EMAILS entry)
  REAPPLY_DATABASE_URL   the database to re-apply deletions in (default DATABASE_URL)
  BACKUP_KEEP_DAYS       delete dumps older than this after each successful backup; set it to the retention stated
                         on the Terms page (NEXT_PUBLIC_BACKUP_RETENTION_DAYS) so deletions really expire

Guarantees: plaintext never touches disk (pg_dump streams straight into gpg); files are mode 600; nothing is
written inside the repository; no URL, figure or email is logged. The dump and its manifest (row counts per table and
one user's totals) come from ONE exported snapshot, so they always agree.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import os
import secrets
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import REPO_ROOT

DUMP_SUFFIX = ".dump.gpg"
MANIFEST_SUFFIX = ".manifest.json.gpg"
PG_IMAGE = os.environ.get("BACKUP_PG_IMAGE", "postgres:17-alpine")  # pg_dump/pg_restore >= the server's version


class BackupError(SystemExit):
    pass


def outside_repo(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path == REPO_ROOT or REPO_ROOT in path.parents:
        raise BackupError(f"refusing: {path} is inside the repository; dumps and registers must live outside it")
    return path


def sa_url(url: str) -> str:
    for prefix in ("postgresql+psycopg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    raise BackupError("the database URL must be a postgresql:// URL")


def libpq_url(url: str) -> str:
    return "postgresql://" + sa_url(url)[len("postgresql+psycopg://"):]


def _gpg(args: list[str], gnupghome: str | None, **kw) -> subprocess.Popen:
    env = {**os.environ, **({"GNUPGHOME": gnupghome} if gnupghome else {})}
    return subprocess.Popen(["gpg", "--batch", "--yes", "--quiet", *args], env=env, **kw)


def _encrypt_bytes(data: bytes, recipient: str, out: Path, gnupghome: str | None) -> None:
    p = _gpg(["--trust-model", "always", "--encrypt", "--recipient", recipient, "--output", str(out)], gnupghome,
             stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    _, err = p.communicate(data)
    if p.returncode != 0:
        raise BackupError(f"gpg encryption failed: {err.decode(errors='replace')[:300]}")
    out.chmod(0o600)


def _decrypt_bytes(path: Path, gnupghome: str | None) -> bytes:
    p = _gpg(["--decrypt", str(path)], gnupghome, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    data, err = p.communicate()
    if p.returncode != 0:
        raise BackupError(f"gpg could not decrypt {path.name}: {err.decode(errors='replace')[:300]}")
    return data


def table_counts(conn) -> dict[str, int]:
    names = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename")).scalars()
    return {n: conn.execute(text(f'SELECT count(*) FROM public."{n}"')).scalar() for n in list(names)}


def check_totals(conn, email: str | None) -> dict | None:
    """The app's own totals for one user, computed inside the given connection's transaction (same snapshot)."""
    from app.tools.totals import totals_in_session, user_id_for

    if not email:
        return None
    with Session(bind=conn, info={"system": True}) as s:
        uid = user_id_for(s, email)
    if uid is None:
        return {"email_found": False}
    with Session(bind=conn, info={"user_id": uid}) as s:
        return {"email_found": True, "totals": totals_in_session(s)}


def backup(db_url: str, out_dir: Path, recipient: str, check_email: str | None = None,
           gnupghome: str | None = None, network: str = "host") -> dict:
    out_dir = outside_repo(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dump_path, manifest_path = out_dir / f"investments-{stamp}{DUMP_SUFFIX}", out_dir / f"investments-{stamp}{MANIFEST_SUFFIX}"
    engine = create_engine(sa_url(db_url), isolation_level="REPEATABLE READ", connect_args={"prepare_threshold": None})
    try:
        with engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            snapshot = conn.execute(text("SELECT pg_export_snapshot()")).scalar()
            counts = table_counts(conn)
            check = check_totals(conn, check_email)
            # pg_dump reads the SAME snapshot; its output streams straight into gpg (no plaintext on disk)
            dump = subprocess.Popen(
                ["docker", "run", "--rm", "-i", "--network", network, "-e", "PGDUMP_URL", PG_IMAGE, "sh", "-c",
                 f'exec pg_dump --snapshot={snapshot} --format=custom --no-owner --no-privileges --schema=public '
                 f'"$PGDUMP_URL"'],
                env={**os.environ, "PGDUMP_URL": libpq_url(db_url)}, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            enc = _gpg(["--trust-model", "always", "--encrypt", "--recipient", recipient, "--output", str(dump_path)],
                       gnupghome, stdin=dump.stdout, stderr=subprocess.PIPE)
            dump.stdout.close()
            enc_err = enc.communicate()[1]
            dump_err = dump.stderr.read()
            dump.wait()
            conn.rollback()
    finally:
        engine.dispose()
    if dump.returncode != 0 or enc.returncode != 0:
        dump_path.unlink(missing_ok=True)
        raise BackupError(f"backup failed: pg_dump exit {dump.returncode} ({dump_err.decode(errors='replace')[:200]}), "
                          f"gpg exit {enc.returncode} ({enc_err.decode(errors='replace')[:200]})")
    dump_path.chmod(0o600)
    manifest = {"created_at": stamp, "snapshot": snapshot, "tables": counts, "check_email": check_email,
                "check": check, "format": "pg_dump custom, schema public, --no-owner --no-privileges"}
    _encrypt_bytes(json.dumps(manifest, default=str).encode(), recipient, manifest_path, gnupghome)
    return {"dump": dump_path, "manifest": manifest_path, "tables": len(counts), "rows": sum(counts.values())}


@contextlib.contextmanager
def restored(dump_path: Path, gnupghome: str | None = None) -> Iterator[str]:
    """Restore an encrypted dump into a throwaway Postgres container; yields its SQLAlchemy URL; always removes it."""
    name, pw = f"inv-restore-{secrets.token_hex(4)}", secrets.token_hex(16)
    run = subprocess.run
    r = run(["docker", "run", "-d", "--rm", "--name", name, "-e", "POSTGRES_PASSWORD", "-p", "127.0.0.1::5432",
             PG_IMAGE], env={**os.environ, "POSTGRES_PASSWORD": pw}, capture_output=True, text=True)
    if r.returncode != 0:
        raise BackupError(f"could not start a throwaway Postgres: {r.stderr[:200]}")
    try:
        deadline = time.monotonic() + 90
        while run(["docker", "exec", name, "createdb", "-U", "postgres", "restored"], capture_output=True).returncode:
            if time.monotonic() > deadline:
                raise BackupError("throwaway Postgres did not become ready")
            time.sleep(1)
        # the dump (schema public) creates the schema itself
        run(["docker", "exec", name, "psql", "-U", "postgres", "-d", "restored", "-q", "-c", "DROP SCHEMA public CASCADE"],
            capture_output=True, check=True)
        port = run(["docker", "port", name, "5432/tcp"], capture_output=True, text=True).stdout.split(":")[-1].strip()
        dec = _gpg(["--decrypt", str(dump_path)], gnupghome, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        rest = subprocess.Popen(["docker", "exec", "-i", name, "pg_restore", "-U", "postgres", "-d", "restored",
                                 "--no-owner", "--no-privileges", "--exit-on-error"],
                                stdin=dec.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        dec.stdout.close()
        _, rest_err = rest.communicate()
        dec_err = dec.stderr.read()
        dec.wait()
        if dec.returncode != 0 or rest.returncode != 0:
            raise BackupError(f"restore failed: gpg exit {dec.returncode} ({dec_err.decode(errors='replace')[:200]}), "
                              f"pg_restore exit {rest.returncode} ({rest_err.decode(errors='replace')[:300]})")
        yield f"postgresql+psycopg://postgres:{pw}@127.0.0.1:{port}/restored"
    finally:
        run(["docker", "rm", "-f", name], capture_output=True)


def verify(url: str, manifest: dict) -> list[str]:
    """Compare a restored database with the manifest taken at backup time. Returns the problems (empty = PASS)."""
    problems = []
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            counts = table_counts(conn)
            for t, n in sorted(manifest["tables"].items()):
                if counts.get(t) != n:
                    problems.append(f"table {t}: expected {n} rows, restored {counts.get(t)}")
            for t in sorted(set(counts) - set(manifest["tables"])):
                problems.append(f"table {t}: in the restore but not in the manifest")
            if manifest.get("check"):
                got = check_totals(conn, manifest["check_email"])
                if got != manifest["check"]:
                    problems.append("portfolio totals of the check user differ from the backup-time values")
    finally:
        engine.dispose()
    return problems


def prune(backup_dir: Path, keep_days: int, now: datetime | None = None) -> list[Path]:
    """Delete dumps (and their manifests) older than keep_days, judged by the timestamp in the file name."""
    now = now or datetime.now(UTC)
    removed = []
    for dump in sorted(outside_repo(backup_dir).glob(f"investments-*{DUMP_SUFFIX}")):
        stamp = dump.name[len("investments-"):-len(DUMP_SUFFIX)]
        try:
            made = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        except ValueError:
            continue
        if (now - made).days > keep_days:
            for p in (dump, dump.with_name(dump.name.replace(DUMP_SUFFIX, MANIFEST_SUFFIX))):
                p.unlink(missing_ok=True)
            removed.append(dump)
    return removed


def latest_dump(backup_dir: Path) -> Path:
    dumps = sorted(outside_repo(backup_dir).glob(f"investments-*{DUMP_SUFFIX}"))
    if not dumps:
        raise BackupError(f"no dumps in {backup_dir}")
    return dumps[-1]


def restore_test(dump_path: Path, gnupghome: str | None = None, out=print) -> int:
    manifest_path = dump_path.with_name(dump_path.name.replace(DUMP_SUFFIX, MANIFEST_SUFFIX))
    manifest = json.loads(_decrypt_bytes(manifest_path, gnupghome))
    with restored(dump_path, gnupghome) as url:
        problems = verify(url, manifest)
    rows = sum(manifest["tables"].values())
    out(f"restore test of {dump_path.name}: {len(manifest['tables'])} tables, {rows} rows"
        + (", portfolio totals of the check user recomputed" if manifest.get("check") else "")
        + (": PASS" if not problems else f": FAIL ({len(problems)})"))
    for p in problems:
        out("  - " + p)
    return 0 if not problems else 1


def read_register(path: Path) -> list[dict]:
    """Private deletion register (docs/DEPLOY.md §18): CSV with header deleted_at,user_id,email; '#' = comment."""
    path = outside_repo(path)
    lines = [ln for ln in path.read_text().splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    rows = list(csv.DictReader(lines))
    for r in rows:
        if not (r.get("user_id") or r.get("email")):
            raise BackupError("every register line needs a user_id or an email")
    return rows


def reapply_deletions(db_url: str, register: Path, out=print) -> dict:
    """Delete again everyone in the register who exists in the given (restored) database."""
    from sqlalchemy import func, select

    from app import db
    from app.models import User
    from app.services.accounts import delete_user_data

    entries = read_register(register)
    db.configure(sa_url(db_url))
    reapplied, absent = [], []
    try:
        for e in entries:
            with db.session_scope(system=True) as s:
                uid = None
                if e.get("user_id"):
                    uid = s.scalar(select(User.id).where(User.id == int(e["user_id"])))
                if uid is None and e.get("email"):
                    uid = s.scalar(select(User.id).where(func.lower(User.email) == e["email"].strip().lower()))
                if uid is None:
                    absent.append(e.get("user_id") or "?")
                    continue
                delete_user_data(s, uid, remove_account=True)
                reapplied.append(uid)
    finally:
        db.get_engine().dispose()
    out(f"deletion register: {len(entries)} entries; deleted again: {len(reapplied)}; already absent: {len(absent)}")
    return {"reapplied": reapplied, "absent": absent}


def _env(name: str, default: str | None = None) -> str:
    v = os.environ.get(name, default)
    if not v:
        raise BackupError(f"set {name} (see docs/OPERATIONS.md)")
    return v


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Encrypted backups, restore test, deletion register.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("backup")
    rt = sub.add_parser("restore-test")
    rt.add_argument("--dump", help="dump file (default: the latest in BACKUP_DIR)")
    rd = sub.add_parser("reapply-deletions")
    rd.add_argument("--register", required=True)
    args = ap.parse_args(argv)
    backup_dir = Path(os.environ.get("BACKUP_DIR") or "~/investments-backups")
    if args.cmd == "backup":
        from app.config import get_settings

        check = os.environ.get("BACKUP_CHECK_EMAIL") or (get_settings().admin_emails.split(",")[0].strip() or None)
        res = backup(_env("BACKUP_DATABASE_URL"), backup_dir, _env("BACKUP_GPG_RECIPIENT"), check)
        print(f"backup written: {res['dump']} ({res['tables']} tables, {res['rows']} rows; encrypted, mode 600)")
        keep = os.environ.get("BACKUP_KEEP_DAYS")
        if keep:
            gone = prune(backup_dir, int(keep))
            print(f"retention: kept {keep} days; removed {len(gone)} older dump(s)")
        else:
            print("retention: BACKUP_KEEP_DAYS is not set. Old dumps still contain people who have since asked to be "
                  "deleted; set it to the retention stated on the Terms page (docs/OPERATIONS.md).")
        print("Run `make restore-test` now and then to prove the dumps restore.")
        return 0
    if args.cmd == "restore-test":
        dump = Path(args.dump).expanduser() if args.dump else latest_dump(backup_dir)
        return restore_test(outside_repo(dump))
    if args.cmd == "reapply-deletions":
        url = os.environ.get("REAPPLY_DATABASE_URL") or _env("DATABASE_URL")
        reapply_deletions(url, Path(args.register))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
