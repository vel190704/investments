"""Settings › AI analysis › Test connection: minimal request, real provider error text, model shown."""

import types

import anthropic
import httpx
import pytest

from app.llm import provider as pv
from app.services import settings as st

calls: list[dict] = []


def _ok(kw, served=None):
    return types.SimpleNamespace(stop_reason="end_turn", model=served or kw["model"],
                                 content=[types.SimpleNamespace(type="text", text="ok")],
                                 usage=types.SimpleNamespace(input_tokens=12, output_tokens=2))


def _err(status, etype, message):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    body = {"type": "error", "error": {"type": etype, "message": message}}
    cls = {401: anthropic.AuthenticationError, 404: anthropic.NotFoundError, 400: anthropic.BadRequestError}[status]
    return cls(f"Error code: {status}", response=httpx.Response(status, request=req, json=body), body=body)


def fake_client(behaviour):
    class Msgs:
        def __init__(self, tag):
            self.tag = tag

        def create(self, **kw):
            calls.append({"tag": self.tag, **kw})
            return behaviour(kw)

    class Client:
        def __init__(self, **kw):
            self.messages = Msgs("plain")
            self.beta = types.SimpleNamespace(messages=Msgs("beta"))
    return Client


@pytest.fixture(autouse=True)
def _reset():
    calls.clear()


def test_ping_is_minimal_and_has_no_personal_data(monkeypatch, session):
    monkeypatch.setattr(anthropic, "Anthropic", fake_client(_ok))
    from app.services.analysis import test_connection

    out = test_connection(session, api_key="k")
    assert out["ok"] is True and out["requested_model"] == "claude-opus-5-5" and out["model"] == "claude-opus-5-5"
    assert out["refusal_fallback"] is False and out["input_tokens"] == 12 and out["latency_ms"] >= 0
    (c,) = calls
    assert c["tag"] == "plain" and c["max_tokens"] <= 16 and "system" not in c
    assert c["messages"] == [{"role": "user", "content": pv.PING_PROMPT}]
    assert "₹" not in str(c) and "LT" not in str(c["messages"])


def test_unknown_model_shows_the_providers_real_error(monkeypatch, session):
    monkeypatch.setattr(anthropic, "Anthropic", fake_client(lambda kw: (_ for _ in ()).throw(
        _err(404, "not_found_error", f"model: {kw['model']}"))))
    from app.services.analysis import test_connection

    out = test_connection(session, api_key="k", model="claude-nope-1")
    assert out["ok"] is False and out["requested_model"] == "claude-nope-1"
    assert out["error"] == "Anthropic API error 404 (not_found_error): model: claude-nope-1"


def test_rejected_key_error_text_is_the_providers(monkeypatch, session):
    monkeypatch.setattr(anthropic, "Anthropic", fake_client(lambda kw: (_ for _ in ()).throw(
        _err(401, "authentication_error", "invalid x-api-key"))))
    from app.services.analysis import test_connection

    out = test_connection(session, api_key="k")
    assert out["error"] == "Anthropic API error 401 (authentication_error): invalid x-api-key"


def test_fallback_state_is_reported_and_used(monkeypatch, session):
    monkeypatch.setattr(anthropic, "Anthropic", fake_client(lambda kw: _ok(kw, served="claude-opus-4-8")))
    st.put(session, "llm", {**st.get(session, "llm"), "refusal_fallback": True})
    from app.services.analysis import test_connection

    out = test_connection(session, api_key="k")
    assert out["refusal_fallback"] is True and calls[0]["tag"] == "beta" and calls[0]["fallbacks"] == "default"
    assert out["model"] == "claude-opus-4-8" and out["fallback_used"] is True


def test_no_key_is_reported_without_a_call(session):
    from app.services.analysis import test_connection

    out = test_connection(session)
    assert out["ok"] is False and "ANTHROPIC_API_KEY" in out["error"] and calls == []


def test_ping_is_logged_as_a_call(monkeypatch, session):
    monkeypatch.setattr(anthropic, "Anthropic", fake_client(_ok))
    from app.services.analysis import test_connection, usage

    test_connection(session, api_key="k")
    assert usage(session)["calls_this_month"] == 1


def test_analysis_errors_also_carry_the_real_text(monkeypatch):
    monkeypatch.setattr(anthropic, "Anthropic", fake_client(lambda kw: (_ for _ in ()).throw(
        _err(400, "invalid_request_error", "max_tokens: too large"))))
    with pytest.raises(pv.LLMUnavailable, match=r"400 \(invalid_request_error\): max_tokens: too large"):
        pv.AnthropicProvider(api_key="k").complete_json("s", [], {})


def test_route(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app import db
    from app.main import app

    db.configure(f"sqlite:///{tmp_path / 'c.db'}")
    monkeypatch.setattr(anthropic, "Anthropic", fake_client(_ok))
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "anthropic_api_key", "k")  # never the real .env (see conftest)
    with TestClient(app) as c:
        r = c.post("/api/llm/test", json={"model": "claude-sonnet-5"})
        assert r.status_code == 200 and r.json()["requested_model"] == "claude-sonnet-5" and r.json()["ok"]
