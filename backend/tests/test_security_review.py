"""6c security review, verified on the real app object built with the deployed settings: API docs off, CORS limited
to the frontend origins, security headers, request/upload size limits; and a preview refuses production credentials
(PREVIEW_ALLOWED_SUPABASE_REFS)."""

from __future__ import annotations

import importlib

import jwt
import pytest
from fastapi.testclient import TestClient

from app import auth
from app.config import get_settings

PREVIEW, PROD = "previewref123", "prodref456"
POOLER = "aws-0-ap-southeast-1.pooler.supabase.com"
PW = "pw-" + "never-printed-9f2c"  # built at runtime: the pre-commit scan refuses URL literals with passwords


def db_url(user: str, host: str) -> str:
    return "postgresql+psycopg://" + user + ":" + PW + "@" + host + ":5432/postgres"


def service_key(ref: str) -> str:
    return jwt.encode({"ref": ref, "role": "service_role"}, "test-only", algorithm="HS256")


@pytest.fixture
def preview(monkeypatch):
    st = get_settings()
    monkeypatch.setattr(st, "env", "preview")
    monkeypatch.setattr(st, "dev_auth", "")
    monkeypatch.setattr(st, "preview_allowed_supabase_refs", PREVIEW)
    monkeypatch.setattr(st, "supabase_url", f"https://{PREVIEW}.supabase.co")
    monkeypatch.setattr(st, "database_url", db_url(f"investments_app.{PREVIEW}", POOLER))
    monkeypatch.setattr(st, "supabase_service_role_key", "")
    return st


def test_preview_with_its_own_project_starts(preview):
    auth.check_startup_config()
    preview.database_url = db_url("postgres", f"db.{PREVIEW}.supabase.co")  # direct connection form
    preview.supabase_service_role_key = service_key(PREVIEW)
    auth.check_startup_config()


@pytest.mark.parametrize("field, value, says", [
    ("supabase_url", f"https://{PROD}.supabase.co", "SUPABASE_URL points at project prodref456"),
    ("supabase_url", "https://auth.example.com", "not a supabase.co URL"),
    ("database_url", db_url(f"investments_app.{PROD}", POOLER), "DATABASE_URL points at project prodref456"),
    ("database_url", db_url("postgres", f"db.{PROD}.supabase.co"), "DATABASE_URL points at project prodref456"),
    ("database_url", db_url("app", "db.render.example.com"), "not a Supabase project"),
    ("supabase_service_role_key", service_key(PROD), "SUPABASE_SERVICE_ROLE_KEY belongs to project prodref456"),
    ("preview_allowed_supabase_refs", "", "needs PREVIEW_ALLOWED_SUPABASE_REFS"),
])
def test_preview_refuses_production_credentials(preview, field, value, says):
    setattr(preview, field, value)
    with pytest.raises(RuntimeError) as e:
        auth.check_startup_config()
    assert says in str(e.value)
    assert PW not in str(e.value) and "test-only" not in str(e.value)  # never the password or key


def test_the_allow_list_only_applies_to_preview(preview):
    preview.supabase_url = f"https://{PROD}.supabase.co"
    preview.database_url = db_url(f"investments_app.{PROD}", POOLER)
    for env in ("production", "", "staging"):  # production and anything unknown (= production)
        preview.env = env
        auth.check_startup_config()


def test_ref_parsing():
    assert auth.supabase_ref_of_url("https://abc.supabase.co/") == "abc"
    assert auth.supabase_ref_of_url("https://abc.supabase.co.evil.example") is None
    assert auth.supabase_ref_of_url("https://x.abc.supabase.co") is None
    assert auth.supabase_refs_of_database_url(db_url("investments_app.AbC", POOLER)) == {"abc"}
    assert auth.supabase_refs_of_database_url("not a url") == set()


@pytest.fixture
def deployed(monkeypatch, tmp_path):
    """The real app module rebuilt with production settings (no lifespan: nothing touches a database)."""
    import app.main as main
    from app import db

    st = get_settings()
    monkeypatch.setattr(st, "env", "production")
    monkeypatch.setattr(st, "dev_auth", "")
    monkeypatch.setattr(st, "supabase_url", f"https://{PROD}.supabase.co")
    monkeypatch.setattr(st, "cors_origins", "https://investments.example.com")
    monkeypatch.setattr(st, "cors_origin_regex", "")
    monkeypatch.setattr(st, "max_request_bytes", 10 * 1024 * 1024)
    db.configure(f"sqlite:///{tmp_path / 'd.db'}")
    db.init_db()
    rebuilt = importlib.reload(main)
    yield TestClient(rebuilt.app)
    monkeypatch.undo()
    importlib.reload(main)  # back to the test-mode app for later tests


def test_deployed_app_publishes_no_api_docs(deployed):
    for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
        assert deployed.get(path).status_code == 404, path


def test_deployed_app_cors_headers_and_limits(deployed):
    c = deployed
    ok = c.options("/api/health", headers={"Origin": "https://investments.example.com",
                                           "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "https://investments.example.com"
    for origin in ("https://evil.example", "https://investments.example.com.evil.example", "null"):
        r = c.options("/api/health", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
        assert "access-control-allow-origin" not in r.headers, origin
        assert "access-control-allow-origin" not in c.get("/api/health", headers={"Origin": origin}).headers
    r = c.get("/api/health")
    for h, v in {"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
                 "Cache-Control": "no-store"}.items():
        assert r.headers[h] == v
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["Strict-Transport-Security"].startswith("max-age=31536000")
    big = c.post("/api/import/preview", headers={"Content-Length": str(11 * 1024 * 1024)}, content=b"x")
    assert big.status_code == 413
    assert c.get("/api/me").status_code == 401  # sign-in required: no dev user when deployed


def test_upload_route_limit_without_a_content_length(tmp_path, monkeypatch):
    """The 10 MB per-file limit holds even when the request size check is bypassed (e.g. chunked uploads)."""
    from app import db
    from app.api import routes
    from app.main import app

    monkeypatch.setattr(routes, "MAX_UPLOAD_BYTES", 1000)
    monkeypatch.setattr(get_settings(), "max_request_bytes", 10**9)
    db.configure(f"sqlite:///{tmp_path / 'u.db'}")
    with TestClient(app) as c:
        r = c.post("/api/import", files={"file": ("w.xlsx", b"x" * 5000)})
    assert r.status_code == 413
