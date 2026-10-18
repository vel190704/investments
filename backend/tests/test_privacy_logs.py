"""No financial figures, Excel contents, thesis text, keys or emails in app logs (which are also Render's log stream:
the console output) or in Sentry events."""

from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

from app import db
from app.logging_config import KeyValueFormatter
from tests.conftest import base_txn_rows, write_workbook

AMOUNT = "987654.32"
FAKE_KEY = "sk-ant-" + "api03-PRIVACYTEST"  # built at runtime: the pre-commit scanner rejects key literals
SECRETS = {
    "amount": ["987654", "9,87,654"],
    "excel name": ["Zirconia Unique Holdings"],
    "excel note": ["excel-note-7c1d"],
    "thesis": ["thesis-text-5e2b"],
    "qualitative": ["moat-note-9a4f"],
    "key": [FAKE_KEY],
    "email": ["@example.com"],
}


from sentry_sdk.transport import Transport  # noqa: E402


class CaptureTransport(Transport):
    """A Sentry transport that keeps envelopes in memory instead of sending them."""

    def __init__(self, options=None):
        super().__init__(options)
        self.envelopes = []

    def capture_envelope(self, envelope):
        self.envelopes.append(envelope)


def _envelope_text(env) -> str:
    return "\n".join(item.get_bytes().decode("utf-8", "replace") for item in env.items)


def test_sentry_scrubs_a_synthetic_event(monkeypatch):
    import sentry_sdk
    from fastapi import FastAPI

    from app.api.middleware import install
    from app.config import get_settings
    from app.observability import init_sentry

    transport = CaptureTransport()
    monkeypatch.setattr(get_settings(), "sentry_dsn", "https://public@o0.ingest.sentry.io/0")
    assert init_sentry(transport=transport)
    try:
        a = FastAPI()
        install(a)

        @a.post("/api/boom/{iid}")
        def boom(iid: int):
            raise ValueError(f"import failed for 'Zirconia Unique Holdings' (alice@example.com): amount ₹{AMOUNT} "
                             f"9,87,654 note 'excel-note-7c1d' thesis \"thesis-text-5e2b\" key {FAKE_KEY}")

        c = TestClient(a, raise_server_exceptions=False)
        r = c.post("/api/boom/42?amount=987654", headers={"Authorization": f"Bearer {FAKE_KEY}",
                                                           "Cookie": "session=alice@example.com"},
                   json={"note": "moat-note-9a4f", "value": AMOUNT})
        assert r.status_code == 500
        logging.getLogger("app.test").error("thesis-text-5e2b %s", AMOUNT)  # logs must not become events
        sentry_sdk.flush()
        events = [e for e in transport.envelopes if any(i.headers.get("type") == "event" for i in e.items)]
        assert len(events) == 1, "exactly one event: the exception (the log line is not sent)"
        text = "\n".join(_envelope_text(e) for e in transport.envelopes)  # every envelope, not just the event
        found = {k: v for k, vs in SECRETS.items() for v in vs if v in text}
        assert found == {}, found
        event = json.loads(next(i.get_bytes() for i in events[0].items if i.headers.get("type") == "event"))
        assert event["request"] == {"method": "POST"} and "breadcrumbs" not in event
        value = event["exception"]["values"][-1]["value"]
        assert "<email>" in value and "<n>" in value and "'<text>'" in value and "sk-ant-***" in value
        assert all("vars" not in f for f in event["exception"]["values"][-1]["stacktrace"]["frames"])
    finally:
        sentry_sdk.init(dsn=None)


def test_a_full_user_flow_logs_none_of_the_private_values(tmp_path, monkeypatch, caplog):
    from cryptography.fernet import Fernet

    import app.api.routes as routes
    from app.config import get_settings
    from app.main import app

    monkeypatch.setattr(routes, "resolve_identifiers", lambda s: {"summary": "skipped"})
    monkeypatch.setattr(get_settings(), "field_encryption_key", Fernet.generate_key().decode())
    caplog.set_level(logging.DEBUG)
    db.configure(f"sqlite:///{tmp_path / 'p.db'}")
    rows = base_txn_rows() + [["2026-10-03", "OPENING", "STOCK", "Zirconia Unique Holdings", "ZRCUNQ", None, None,
                               1, AMOUNT, AMOUNT, 0, "Groww", "excel-note-7c1d"]]
    book = write_workbook(tmp_path / "w.xlsx", txn_rows=rows)
    A = {"X-Dev-User": "alice@example.com"}
    with TestClient(app) as c:
        assert c.post("/api/import", headers=A, files={"file": ("w.xlsx", book.read_bytes())}).json()["report"]["ok"]
        iid = next(t["instrument_id"] for t in c.get("/api/transactions", headers=A).json() if t["name"].startswith("Zirconia"))
        c.post(f"/api/journal/{iid}", headers=A, json={"why": "thesis-text-5e2b", "change_view": "x", "horizon": "5y"})
        c.post(f"/api/qualitative/{iid}", headers=A, json={"moat_type": "brand", "moat_note": "moat-note-9a4f",
                                                           "capital_allocation_note": "x", "source_note": "x",
                                                           "as_of": "2026-10-01"})
        c.put("/api/me/ai-key", headers=A, json={"key": FAKE_KEY + "x" * 30})
        c.post("/api/transactions", headers=A, json={"date": "bad", "type": "BUY", "amount": AMOUNT,
                                                     "notes": "excel-note-7c1d"})  # 422 with private values in it
        c.post("/api/admin/invites", json={"email": "friend@example.com", "send_email": False})  # dev user = admin
        c.delete("/api/admin/invites/friend@example.com")
        c.get("/api/admin/users")
        c.get("/api/export.xlsx", headers=A)
        c.get(f"/api/valuation/{iid + 999}", headers=A)  # 404
        c.request("DELETE", "/api/me", headers=A, json={"confirm": "alice@example.com"})
    lines = [KeyValueFormatter().format(r) for r in caplog.records]
    found = sorted({f"{k}: {v!r} in {line[:140]}" for line in lines for k, vs in SECRETS.items() for v in vs
                    if v in line})
    assert len(lines) > 20 and found == [], found
