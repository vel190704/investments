"""The pre-commit scan (.githooks/scan.sh) refuses secrets, dumps, encrypted backups and deletion registers."""

import shutil
import subprocess
from pathlib import Path

import pytest

SCAN = Path(__file__).resolve().parents[2] / ".githooks" / "scan.sh"
pytestmark = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def staged(tmp_path, name: str, content: bytes) -> int:
    repo = tmp_path / "repo"
    if not repo.exists():
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
    p = repo / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content)
    subprocess.run(["git", "-C", str(repo), "add", name], check=True)
    r = subprocess.run(["bash", str(SCAN)], cwd=repo, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo), "rm", "-q", "--cached", name], check=True)
    return r.returncode


@pytest.mark.parametrize("name, content", [
    ("x.py", b'KEY = "sk-ant-' + b"api03-" + b'A' * 30 + b'"\n'),
    # sample URLs are assembled at runtime so this file itself doesn't trip the scan it tests
    ("config.txt", b"DATABASE_URL=postgresql+psycopg://investments_app.abc:" + b"S3cr3tPassw0rd" + b"@aws-0.pooler.supabase.com:5432/postgres\n"),
    ("notes.md", b"postgres://backup:" + b"hunter2hunter2" + b"@db.example.com/postgres\n"),
    ("investments-20261018.dump.gpg", b"\x85\x01binary"),
    ("prod.dump", b"anything"),
    ("data/deletions.csv", b"deleted_at,user_id,email\n"),
    ("frontend/.env.local", b"X=1\n"),
    ("misc/innocent.bin", b"PG" + b"DMP\x01\x0e\x00binary dump"),
    ("misc/schema.sql", b"--\n-- PostgreSQL " + b"database dump\n--\n"),
    ("keys/me.txt", b"-----BEGIN PGP " + b"PRIVATE KEY BLOCK-----\n"),
])
def test_refused(tmp_path, name, content):
    assert staged(tmp_path, name, content) == 1


@pytest.mark.parametrize("name, content", [
    ("Makefile", b"PG_TEST_URL ?= postgresql+psycopg://postgres:localtest@127.0.0.1:55432/postgres\n"),
    ("docs.md", b"DATABASE_URL=postgresql+psycopg://investments_app:<password>@<host>:5432/postgres\n"),
    ("tool.py", b'url = f"postgresql+psycopg://postgres:{pw}@127.0.0.1:{port}/restored"\n'),
    (".env.example", b"DATABASE_URL=\n"),
    ("tests/fixtures/data.csv", b"symbol,price\nLT,3768\n"),
])
def test_allowed(tmp_path, name, content):
    assert staged(tmp_path, name, content) == 0
