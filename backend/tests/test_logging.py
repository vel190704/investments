"""Logging: request ids, redaction, structured outbound/LLM/job lines, nothing sensitive ever logged."""

import json
import logging
import logging.handlers
from datetime import date

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.api.middleware import install
from app.logging_config import (BACKUPS, MAX_BYTES, JsonFormatter, KeyValueFormatter, configure_logging, redact,
                                register_secret)

KEY = "sk-ant-api03-" + "Q" * 40


def lines(caplog, fmt=None):
    f = fmt or KeyValueFormatter()
    return [f.format(r) for r in caplog.records]


# ---- redaction ----
@pytest.mark.parametrize("raw, leaked", [
    (f"key {KEY} rejected", KEY),
    ("Authorization: Bearer abc.def.ghi", "abc.def.ghi"),
    ('{"x-api-key": "plainsecret123"}', "plainsecret123"),
    ("GET https://example.com/q?symbol=LT&token=tok123&api_key=zzz999", "tok123"),
    ("ANTHROPIC_API_KEY=whatever-it-is", "whatever-it-is"),
])
def test_redact_patterns(raw, leaked):
    assert leaked not in redact(raw)


def test_registered_secret_is_redacted_everywhere_incl_tracebacks_and_json(caplog):
    register_secret("my-very-own-secret-value")
    log = logging.getLogger("app.test")
    with caplog.at_level(logging.INFO):
        log.info("plain my-very-own-secret-value", extra={"fields": {"header": "my-very-own-secret-value"}})
        try:
            raise RuntimeError(f"bad key {KEY}")
        except RuntimeError:
            log.exception("failed")
    for fmt in (KeyValueFormatter(), JsonFormatter()):
        out = "\n".join(lines(caplog, fmt))
        assert "my-very-own-secret-value" not in out and KEY not in out and "RuntimeError" in out


def test_configured_api_key_is_registered(monkeypatch, tmp_path):
    from app.config import get_settings
    from app.logging_config import _SECRETS

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-test-configured-key-1234")
    configure_logging(log_dir=tmp_path, console=False)
    assert "sk-test-configured-key-1234" in _SECRETS


# ---- configuration ----
def test_rotating_file_10mb_x5_and_quiet_alembic(tmp_path):
    path = configure_logging(log_dir=tmp_path, console=False)
    h = next(h for h in logging.getLogger().handlers if isinstance(h, logging.handlers.RotatingFileHandler))
    assert path == tmp_path / "app.log" and h.maxBytes == MAX_BYTES == 10 * 1024 * 1024 and h.backupCount == BACKUPS == 5
    assert logging.getLogger("alembic.runtime.plugins").getEffectiveLevel() >= logging.WARNING
    logging.getLogger("app.test").info("hello", extra={"fields": {"a": 1}})
    for hh in logging.getLogger().handlers:
        hh.flush()
    assert "msg=hello a=1" in path.read_text()


def test_json_format(tmp_path):
    path = configure_logging(log_dir=tmp_path, console=False, fmt="json")
    logging.getLogger("app.test").warning("w", extra={"fields": {"n": 2}})
    for hh in logging.getLogger().handlers:
        hh.flush()
    obj = json.loads(path.read_text().splitlines()[-1])
    assert obj["level"] == "WARNING" and obj["n"] == 2 and obj["rid"] == "-"
    configure_logging(log_dir=tmp_path, console=False)


# ---- request id middleware ----
def _app():
    a = FastAPI()
    install(a)

    class Body(BaseModel):
        amount: int

    @a.get("/api/ok")
    def ok():
        logging.getLogger("app.test").info("inside handler")
        return {"ok": True}

    @a.post("/api/validate")
    def validate(b: Body):
        return b

    @a.get("/api/boom")
    def boom():
        raise RuntimeError(f"exploded with {KEY}")

    @a.get("/api/conflict")
    def conflict():
        raise HTTPException(409, "Privacy toggle is off")
    return a


def test_request_id_header_and_on_every_line(caplog):
    c = TestClient(_app())
    with caplog.at_level(logging.DEBUG):
        r = c.get("/api/ok")
    rid = r.headers["X-Request-ID"]
    assert len(rid) == 12
    mine = [r for r in caplog.records if getattr(r, "request_id", None) == rid]
    assert {r.getMessage() for r in mine} >= {"inside handler", "http_request"}
    req = next(r for r in mine if r.getMessage() == "http_request")
    assert req.fields["method"] == "GET" and req.fields["path"] == "/api/ok" and req.fields["status"] == 200
    assert "duration_ms" in req.fields
    assert c.get("/api/ok", headers={"X-Request-ID": "abc-123"}).headers["X-Request-ID"] == "abc-123"
    assert c.get("/api/ok", headers={"X-Request-ID": "bad id\n"}).headers["X-Request-ID"] != "bad id\n"


def test_422_logs_validation_detail_without_submitted_values(caplog):
    c = TestClient(_app())
    with caplog.at_level(logging.INFO):
        r = c.post("/api/validate", json={"amount": "my private journal text"})
    assert r.status_code == 422 and r.json()["request_id"] == r.headers["X-Request-ID"]
    v = next(x for x in caplog.records if x.getMessage() == "validation_error")
    assert v.fields["errors"][0]["loc"] == "body.amount" and v.fields["errors"][0]["type"] == "int_parsing"
    assert "my private journal text" not in "\n".join(lines(caplog))


def test_4xx_http_error_detail_is_logged(caplog):
    c = TestClient(_app())
    with caplog.at_level(logging.INFO):
        r = c.get("/api/conflict")
    assert r.status_code == 409 and r.json() == {"detail": "Privacy toggle is off", "request_id": r.headers["X-Request-ID"]}
    e = next(x for x in caplog.records if x.getMessage() == "http_error")
    assert e.levelno == logging.WARNING and e.fields["detail"] == "Privacy toggle is off"


def test_500_logs_full_traceback_and_returns_request_id(caplog):
    c = TestClient(_app(), raise_server_exceptions=False)
    with caplog.at_level(logging.INFO):
        r = c.get("/api/boom")
    assert r.status_code == 500 and r.json()["request_id"] == r.headers["X-Request-ID"]
    out = "\n".join(lines(caplog))
    assert "Traceback" in out and "RuntimeError" in out and "status=500" in out and KEY not in out


def test_real_app_sets_request_id(tmp_path):
    from app import db
    from app.main import app

    db.configure(f"sqlite:///{tmp_path / 'l.db'}")
    with TestClient(app) as c:
        assert c.get("/api/health").headers.get("X-Request-ID")


# ---- outbound ----
def test_polite_fetch_logs_source_host_status_retries_but_not_the_url(caplog):
    from app.net.polite import PoliteClient

    n = {"feed": 0}

    def h(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="")
        n["feed"] += 1
        if n["feed"] == 1:
            raise httpx.ReadTimeout("slow", request=req)
        return httpx.Response(200, text="<rss/>")

    c = PoliteClient(transport=httpx.MockTransport(h), min_interval=0, sleep=lambda _s: None)
    with caplog.at_level(logging.INFO):
        c.get_text("https://feeds.example.com/private/path.xml?token=abc", "News feed: Example")
    rec = [r for r in caplog.records if r.getMessage() == "outbound" and r.fields["source"] == "News feed: Example"][-1]
    assert rec.fields["host"] == "feeds.example.com" and rec.fields["status"] == 200 and rec.fields["retries"] == 1
    assert rec.fields["outcome"] == "ok" and "duration_ms" in rec.fields
    out = "\n".join(lines(caplog))
    assert "/private/path.xml" not in out and "token=abc" not in out


def test_outbound_failure_logs_error_class(caplog):
    from app.net.outbound import outbound

    with caplog.at_level(logging.INFO), pytest.raises(ValueError):
        with outbound("yfinance macro", "finance.yahoo.com (yfinance)", ticker="^NSEI"):
            raise ValueError("no data returned")
    rec = caplog.records[-1]
    assert rec.levelno == logging.WARNING and rec.fields["error"] == "ValueError" and rec.fields["outcome"] == "error"


# ---- jobs ----
def test_run_job_logs_start_end_and_never_raises(caplog):
    from app.scheduler import run_job

    with caplog.at_level(logging.INFO):
        assert run_job("demo", lambda: {"ok_count": 3, "error_count": 0}) == {"ok_count": 3, "error_count": 0}
        assert run_job("broken", lambda: 1 / 0) is None
    ends = [r for r in caplog.records if r.getMessage() == "job_end"]
    assert [(e.fields["job"], e.fields["outcome"]) for e in ends] == [("demo", "ok"), ("broken", "failed")]
    assert ends[0].fields["ok_count"] == 3 and ends[0].request_id.startswith("job:demo-")
    assert "ZeroDivisionError" in "\n".join(lines(caplog))


# ---- LLM: never the prompt, input text or thesis ----
def test_llm_logs_counts_hash_and_reasons_but_never_thesis_or_prompt(session, workbook, monkeypatch, caplog):
    from tests.test_llm import FakeProvider, TODAY, enable, good_for, setup_book

    from app.llm.inputs import build_input
    from app.services import analysis as an
    from app.services.journal import add_entry, set_optin

    lt = setup_book(session, workbook)
    enable(session, monkeypatch)
    secret_thesis = "Zebra-unique moat thesis about cement kilns"
    add_entry(session, lt.id, secret_thesis, "Change-view zebra text", "5y", date(2027, 1, 1), [])
    set_optin(session, lt.id, True)
    inp = build_input(session, lt.id, TODAY)
    assert any(secret_thesis in json.dumps(v) for v in inp.values())  # it IS sent (opted in)...
    bad = json.dumps({"x": "invented 987654"})
    with caplog.at_level(logging.DEBUG):
        an.analyze(session, lt.id, provider=FakeProvider([bad, good_for(inp)]), today=TODAY)
    out = "\n".join(lines(caplog))
    assert secret_thesis not in out and "Change-view zebra" not in out  # ...but never logged
    calls = [r for r in caplog.records if r.getMessage() == "llm_call"]
    assert [c.fields["outcome"] for c in calls] == ["rejected", "ok"]
    assert calls[0].fields["rejection_reasons"] and calls[1].fields["input_tokens"] >= 0
    assert len(calls[1].fields["input_hash"]) == 16 and "latency_ms" in calls[1].fields
