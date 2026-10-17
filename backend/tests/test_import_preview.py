from sqlalchemy import func, select

from app.importer.run import import_workbook, preview_workbook
from app.models import ImportRun, Instrument, Transaction
from tests.conftest import base_txn_rows, write_workbook


def count(s, m):
    return s.scalar(select(func.count()).select_from(m))


def test_preview_saves_nothing(session, workbook):
    r = preview_workbook(session, workbook)
    assert r["preview"] and r["ok"] and len(r["transactions"]["added_rows"]) == 19
    assert count(session, Transaction) == 0 and count(session, Instrument) == 0 and count(session, ImportRun) == 0


def test_preview_shows_adds_removes_and_errors(session, tmp_path, workbook):
    import_workbook(session, workbook)
    rows = base_txn_rows()[:-1] + [["2026-10-20", "SIP", "MF", "Kotak Nifty Next 50 Index Fund - Direct - Growth",
                                    None, None, None, 49.3, 20.28, 1000, 0, "Zerodha Coin", "Oct SIP"]]
    r = preview_workbook(session, write_workbook(tmp_path / "next.xlsx", txn_rows=rows))
    tr = r["transactions"]
    assert [a["type"] for a in tr["added_rows"]] == ["SIP"]
    assert [x["name"] for x in tr["removed_rows"]] == ["Kotak Nifty Next 50 Index Fund - Direct - Growth"]
    assert count(session, Transaction) == 19  # still unchanged
    bad = rows + [["2026-10-21", "HOLD", "STOCK", "X", "X", None, None, 1, 1, 1, 0, "Groww", None]]
    r2 = preview_workbook(session, write_workbook(tmp_path / "bad.xlsx", txn_rows=bad))
    assert r2["transactions"]["errors"] and r2["transactions"]["removed_rows"] == []  # no pruning when errors


def test_preview_then_confirm_api(tmp_path, workbook, monkeypatch):
    from fastapi.testclient import TestClient

    from app import db
    from app.config import get_settings
    from app.main import app
    import app.api.routes as routes

    db.configure(f"sqlite:///{tmp_path / 'p.db'}")
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    monkeypatch.setattr(routes, "resolve_identifiers", lambda s: {"summary": "skipped"})
    with TestClient(app) as c:
        with open(workbook, "rb") as f:
            p = c.post("/api/import/preview", files={"file": ("book.xlsx", f, "application/octet-stream")}).json()
        assert len(p["report"]["transactions"]["added_rows"]) == 19
        assert c.get("/api/transactions").json() == []  # nothing applied yet
        assert c.post("/api/import/confirm", json={"token": "0" * 64}).status_code == 404
        r = c.post("/api/import/confirm", json={"token": p["token"]}).json()
        assert r["report"]["transactions"]["inserted"] == 19
        assert len(c.get("/api/transactions").json()) == 19
        assert c.post("/api/import/confirm", json={"token": p["token"]}).status_code == 404  # one-shot
