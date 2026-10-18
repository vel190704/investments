"""The post-deploy smoke tool (app/tools/smoke.py), exercised in-process: it must pass on a correct app, catch a
leaking app, refuse anything but preview, and sign in through Supabase's password grant."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app import db
from app.tools import smoke

A, B = {"X-Dev-User": "smoke-a@example.com"}, {"X-Dev-User": "smoke-b@example.com"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    from tests import test_isolation as iso

    db.configure(f"sqlite:///{tmp_path / 's.db'}")
    iso._offline(monkeypatch)
    from app.main import app

    with TestClient(app, base_url="http://testserver") as c:
        yield c


def test_smoke_passes_on_a_correct_app(client):
    lines = []
    rep = smoke.run("http://testserver", client, A, B, out=lines.append)
    assert rep["problems"] == [] and rep["checked"] > 45 and lines[0].endswith("PASS")
    assert "Smoke Canary" not in client.get("/api/transactions", headers=B).text  # cleaned up afterwards


def test_smoke_catches_a_leak(client, monkeypatch):
    from app import tenancy

    monkeypatch.setattr(tenancy, "is_system", lambda s: True)  # simulate a forgotten user filter
    rep = smoke.run("http://testserver", client, A, B, out=lambda _l: None)
    assert any("canary visible to A" in p for p in rep["problems"])


def test_refuses_without_preview_target_or_with_production_project(monkeypatch):
    for k in ("SMOKE_TARGET", "SMOKE_SUPABASE_URL", "SMOKE_PRODUCTION_SUPABASE_URL"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(SystemExit, match="SMOKE_TARGET=preview"):
        smoke.main(["--url", "https://example.invalid"])
    monkeypatch.setenv("SMOKE_TARGET", "preview")
    monkeypatch.setenv("SMOKE_SUPABASE_URL", "https://prod.supabase.co")
    monkeypatch.setenv("SMOKE_PRODUCTION_SUPABASE_URL", "https://prod.supabase.co/")
    with pytest.raises(SystemExit, match="production project"):
        smoke.main(["--url", "https://example.invalid"])


def test_password_grant_sign_in():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["apikey"] = str(req.url), req.headers["apikey"]
        ok = b'"secret-pw"' in req.content
        return httpx.Response(200 if ok else 400, json={"access_token": "tok"} if ok else {"error": "bad"})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    assert smoke.supabase_token("https://pv.supabase.co/", "anon", "a@example.com", "secret-pw", http) == "tok"
    assert seen["url"] == "https://pv.supabase.co/auth/v1/token?grant_type=password" and seen["apikey"] == "anon"
    with pytest.raises(SystemExit, match="sign-in failed"):
        smoke.supabase_token("https://pv.supabase.co", "anon", "a@example.com", "wrong", http)
