"""Internet-facing hardening: CORS, security headers, request size limit, rate limits, health check."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import db
from app.api.limits import LIMITER, Limiter
from app.config import get_settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    db.configure(f"sqlite:///{tmp_path / 'h.db'}")
    from app.main import app

    with TestClient(app) as c:
        yield c


def test_security_headers_and_request_id(client):
    r = client.get("/api/me")
    for h in ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy", "Content-Security-Policy"):
        assert h in r.headers
    assert r.headers["Cache-Control"] == "no-store" and r.headers["X-Request-ID"]
    assert "Strict-Transport-Security" not in r.headers  # not in development/test


def test_hsts_outside_development(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "env", "production")
    assert "max-age=31536000" in client.get("/api/health").headers["Strict-Transport-Security"]


def test_health_checks_the_database(client, monkeypatch):
    from app import db as dbm

    assert client.get("/api/health").json() == {"status": "ok", "database": dbm.get_engine().dialect.name}

    class Broken:
        def connect(self):
            raise RuntimeError("db down")

    monkeypatch.setattr(dbm, "get_engine", lambda: Broken())
    r = client.get("/api/health")
    assert r.status_code == 503 and r.json()["status"] == "unavailable"


def test_request_size_limit(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_request_bytes", 1000)
    r = client.post("/api/import/preview", files={"file": ("w.xlsx", b"x" * 5000)})
    assert r.status_code == 413 and "too large" in r.json()["detail"]


def test_upload_rate_limit_per_session(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "rate_limits_enabled", True)
    LIMITER.reset()
    codes = [client.post("/api/import/preview", files={"file": ("w.txt", b"x")}).status_code for _ in range(22)]
    assert codes[:20] == [400] * 20 and codes[20:] == [429, 429]  # 20 per 10 minutes, then refused
    r = client.post("/api/import/preview", files={"file": ("w.txt", b"x")})
    assert int(r.headers["Retry-After"]) > 0
    other = client.post("/api/import/preview", headers={"X-Dev-User": "other@example.com"}, files={"file": ("w.txt", b"x")})
    assert other.status_code == 400  # a different person has their own budget
    LIMITER.reset()


def test_failed_sign_ins_are_rate_limited_per_ip(client, monkeypatch):
    st = get_settings()
    monkeypatch.setattr(st, "rate_limits_enabled", True)
    monkeypatch.setattr(st, "dev_auth", "")  # real auth
    monkeypatch.setattr(st, "supabase_url", "https://proj.supabase.co")
    monkeypatch.setattr(st, "supabase_jwt_secret", "x" * 40)
    LIMITER.reset()
    codes = [client.get("/api/me", headers={"Authorization": "Bearer junk"}).status_code for _ in range(22)]
    assert codes[:20] == [401] * 20 and codes[20:] == [429, 429]
    assert client.get("/api/health").status_code == 200  # health stays reachable for uptime checks
    LIMITER.reset()


def test_limiter_window_slides():
    t = [0.0]
    lim = Limiter(clock=lambda: t[0])
    for _ in range(3):
        lim.hit("b", "k", 60)
    assert lim.blocked("b", "k", 3, 60) == 60
    t[0] = 61
    assert lim.blocked("b", "k", 3, 60) is None


def test_cors_allows_only_configured_origins(monkeypatch):
    from app.api.middleware import install_cors

    st = get_settings()
    monkeypatch.setattr(st, "cors_origins", "https://investments.example.com")
    monkeypatch.setattr(st, "cors_origin_regex", r"^https://investments-[a-z0-9-]+-me\.vercel\.app$")
    a = FastAPI()
    install_cors(a)
    a.get("/api/x")(lambda: {"ok": True})
    c = TestClient(a)

    def pre(origin):
        return c.options("/api/x", headers={"Origin": origin, "Access-Control-Request-Method": "GET",
                                            "Access-Control-Request-Headers": "Authorization"})
    ok = pre("https://investments.example.com")
    assert ok.headers["access-control-allow-origin"] == "https://investments.example.com"
    assert "access-control-allow-credentials" not in ok.headers
    assert pre("https://investments-git-feature-me.vercel.app").headers["access-control-allow-origin"]
    assert "access-control-allow-origin" not in pre("https://evil.example").headers
    assert "x-request-id" in c.get("/api/x", headers={"Origin": "https://investments.example.com"}).headers[
        "access-control-expose-headers"].lower()
    monkeypatch.setattr(st, "cors_origins", "*")
    with pytest.raises(RuntimeError, match="exact origins"):
        install_cors(FastAPI())


def test_api_docs_are_not_published_when_deployed(monkeypatch):
    import app.main as main

    monkeypatch.setattr(get_settings(), "env", "production")
    assert main._docs_enabled() is False
    monkeypatch.setattr(get_settings(), "env", "test")
    assert main._docs_enabled() is True  # the app object is built at import; the decision is what we test
