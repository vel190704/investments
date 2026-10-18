"""Feedback: limits, rate limit per user, admin list/filter/mark done, deletion with the account, and the text never
reaching logs or Sentry (also when storing fails with an error that quotes it)."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import db
from app.logging_config import KeyValueFormatter
from app.services import feedback as fbs
from app.timeutil import utcnow
from tests.conftest import make_user
from tests.test_privacy_logs import CaptureTransport, _envelope_text

ALICE, BOB = "alice@example.com", "bob@example.com"
A, B = {"X-Dev-User": ALICE}, {"X-Dev-User": BOB}
SECRET = "feedback-canary-3b9e my folio 12345678 lost"


@pytest.fixture
def client(tmp_path):
    db.configure(f"sqlite:///{tmp_path / 'f.db'}")
    with TestClient(__import__("app.main", fromlist=["app"]).app) as c:
        yield c


def test_send_feedback_and_the_admin_lists_filters_and_marks_it_done(client):
    assert client.post("/api/feedback", headers=A, json={"text": " The chart is blank ", "page": "/holdings?x=1#y"}
                       ).status_code == 201
    assert client.post("/api/feedback", headers=B, json={"text": "Typo on allocation", "page": "/allocation"}
                       ).status_code == 201
    info = client.get("/api/feedback/info", headers=A).json()
    assert info["max_chars"] == 2000 and "account numbers" in info["note"]
    assert client.get("/api/admin/feedback", headers=A).status_code == 403  # members can't read anyone's
    res = client.get("/api/admin/feedback").json()  # the dev user is the admin
    assert res["open"] == 2 and res["pages"] == ["/allocation", "/holdings"]
    first = next(i for i in res["items"] if i["page"] == "/holdings")
    assert first["text"] == "The chart is blank" and first["user_id"] == make_user(ALICE)
    assert [i["page"] for i in client.get("/api/admin/feedback", params={"page": "/allocation"}).json()["items"]] \
        == ["/allocation"]
    today = utcnow().date().isoformat()
    assert len(client.get("/api/admin/feedback", params={"since": today, "until": today}).json()["items"]) == 2
    assert client.get("/api/admin/feedback", params={"until": "2020-01-01"}).json()["items"] == []
    assert client.get("/api/admin/feedback", params={"since": "x"}).status_code == 422
    assert client.put(f"/api/admin/feedback/{first['id']}/done", headers=A, json={"done": True}).status_code == 403
    assert client.put(f"/api/admin/feedback/{first['id']}/done", json={"done": True}).json()["done_at"]
    assert [i["page"] for i in client.get("/api/admin/feedback").json()["items"]] == ["/allocation"]
    assert [i["page"] for i in client.get("/api/admin/feedback", params={"status": "done"}).json()["items"]] \
        == ["/holdings"]
    assert client.put(f"/api/admin/feedback/{first['id']}/done", json={"done": False}).json()["done_at"] is None
    assert client.put("/api/admin/feedback/99999/done", json={"done": True}).status_code == 404


def test_length_limit_and_empty_text(client):
    assert client.post("/api/feedback", headers=A, json={"text": "x" * 2000}).status_code == 201
    r = client.post("/api/feedback", headers=A, json={"text": "x" * 2001})
    assert r.status_code == 422 and "2,000" in r.json()["detail"]
    assert client.post("/api/feedback", headers=A, json={"text": "   "}).status_code == 422


def test_rate_limited_per_user(client):
    for i in range(fbs.RATE_PER_HOUR):
        assert client.post("/api/feedback", headers=A, json={"text": f"note {i}"}).status_code == 201
    assert client.post("/api/feedback", headers=A, json={"text": "one more"}).status_code == 429
    assert client.post("/api/feedback", headers=B, json={"text": "Bob is not limited by Alice"}).status_code == 201


def test_daily_limit(tmp_path):
    db.configure(f"sqlite:///{tmp_path / 'd.db'}")
    db.init_db()
    uid = make_user(ALICE)
    now = utcnow()
    with db.session_scope(user_id=uid) as s:
        for i in range(fbs.RATE_PER_DAY):  # spread over the day: never 5 in one hour
            fbs.submit(s, uid, "/", f"n{i}", now=now - timedelta(hours=23) + timedelta(minutes=70 * i))
    with db.session_scope(user_id=uid) as s, pytest.raises(fbs.FeedbackError, match="a day"):
        fbs.submit(s, uid, "/", "again", now=now + timedelta(hours=1))


def test_page_is_cleaned():
    assert fbs.clean_page("/holdings?symbol=LT") == "/holdings"
    assert fbs.clean_page("/analysis/12#card") == "/analysis/12"
    assert fbs.clean_page("https://evil.example/x") == "/"
    assert fbs.clean_page("/a b<script>") == "/"
    assert fbs.clean_page(None) == "/"


def test_feedback_is_deleted_with_the_account(client):
    from app.models import Feedback

    client.post("/api/feedback", headers=A, json={"text": "bye"})
    client.post("/api/feedback", headers=B, json={"text": "stay"})
    assert client.request("DELETE", "/api/me", headers=A, json={"confirm": ALICE}).status_code == 200
    with db.session_scope(system=True) as s:
        assert s.scalars(select(Feedback.text)).all() == ["stay"]
        assert s.scalar(select(func.count()).select_from(Feedback)) == 1


def test_feedback_text_never_reaches_logs_or_sentry(client, monkeypatch, caplog):
    import sentry_sdk
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    from app.config import get_settings
    from app.observability import init_sentry

    transport = CaptureTransport()
    monkeypatch.setattr(get_settings(), "sentry_dsn", "https://public@o0.ingest.sentry.io/0")
    assert init_sentry(transport=transport)
    caplog.set_level(logging.DEBUG)
    try:
        assert client.post("/api/feedback", headers=A, json={"text": SECRET, "page": "/holdings"}).status_code == 201
        assert client.post("/api/feedback", headers=A, json={"text": SECRET * 60}).status_code == 422  # too long
        assert client.post("/api/feedback", headers=A, json={"text": 5}).status_code == 422  # wrong type
        assert client.get("/api/admin/feedback").status_code == 200
        real_flush = Session.flush

        def failing_flush(self, *a, **k):  # what a real DB error looks like: it quotes the parameters
            if any(getattr(o, "text", None) == SECRET for o in self.new):
                raise IntegrityError("INSERT INTO feedback ...", {"text": SECRET}, Exception(f"bad row '{SECRET}'"))
            return real_flush(self, *a, **k)

        monkeypatch.setattr(Session, "flush", failing_flush)
        r = client.post("/api/feedback", headers=B, json={"text": SECRET})
        assert r.status_code == 503 and SECRET not in r.text
        monkeypatch.setattr(Session, "flush", real_flush)

        def failing_commit(self):
            if self.info.get("user_id") is not None:  # the route's own session (sign-in uses a system session)
                raise IntegrityError("COMMIT", {"text": SECRET}, Exception(SECRET))
            return real_commit(self)

        real_commit = Session.commit
        monkeypatch.setattr(Session, "commit", failing_commit)
        assert client.post("/api/feedback", headers=B, json={"text": SECRET}).status_code == 503
        monkeypatch.setattr(Session, "commit", real_commit)
        for _ in range(fbs.RATE_PER_HOUR):
            client.post("/api/feedback", headers=A, json={"text": SECRET})
        assert client.post("/api/feedback", headers=A, json={"text": SECRET}).status_code == 429
        sentry_sdk.flush()
        sent = "\n".join(_envelope_text(e) for e in transport.envelopes)
    finally:
        sentry_sdk.init(dsn=None)
    lines = [KeyValueFormatter().format(r) for r in caplog.records]
    assert any("feedback_received" in line for line in lines) and any("feedback_store_failed" in line for line in lines)
    for needle in ("feedback-canary-3b9e", "12345678"):
        assert not [line for line in lines if needle in line]
        assert needle not in sent
