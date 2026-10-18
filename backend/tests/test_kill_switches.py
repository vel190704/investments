"""Kill switches: each takes effect on the very next request (no restart, no redeploy), admins are never locked out,
and every change is in the audit log (numeric ids, no emails)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import db
from app.auth import AuthError, resolve_user
from tests.conftest import make_user

ALICE, BOB, CAROL = "alice@example.com", "bob@example.com", "carol@example.com"
A, B, C = ({"X-Dev-User": e} for e in (ALICE, BOB, CAROL))


@pytest.fixture
def client(tmp_path):
    from app.main import app

    db.configure(f"sqlite:///{tmp_path / 'k.db'}")
    with TestClient(app) as c:
        for h in (A, B):
            assert c.get("/api/me", headers=h).status_code == 200  # Alice and Bob have accounts
        yield c


def _actions(c) -> list[str]:
    return [a["action"] for a in c.get("/api/admin/ops").json()["audit"]][::-1]


def test_new_signins_off_blocks_only_first_sign_ins(client):
    c = client
    assert c.put("/api/admin/ops", headers=A, json={"new_signins_off": True}).status_code == 403  # admin only
    assert c.put("/api/admin/ops", json={"new_signins_off": True}).json()["switches"]["new_signins_off"] is True
    r = c.get("/api/me", headers=C)  # Carol has never signed in
    assert r.status_code == 403 and "New sign-ins are paused" in r.json()["detail"]
    assert c.get("/api/me", headers=A).status_code == 200  # existing accounts keep working
    assert c.get("/api/me").status_code == 200  # the admin too
    c.put("/api/admin/ops", json={"new_signins_off": False})
    assert c.get("/api/me", headers=C).status_code == 200
    assert _actions(c) == ["new_signins_off_on", "new_signins_off_off"]


def test_new_signins_off_also_blocks_the_first_real_sign_in_of_a_prepared_account(client, monkeypatch):
    """An account that exists (e.g. moved from SQLite) but has never signed in with Supabase counts as new."""
    from app.config import get_settings
    from app.models import AllowedEmail

    with db.session_scope(system=True) as s:
        s.add(AllowedEmail(email=BOB))
        from app.services import ops

        ops.set_switches(s, {"new_signins_off": True}, by_user_id=None)
    monkeypatch.setattr(get_settings(), "admin_emails", "")
    with pytest.raises(AuthError) as e:
        resolve_user(BOB, "supabase-subject-1")  # first sign-in: binds a subject
    assert e.value.status == 403
    with db.session_scope(system=True) as s:
        ops.set_switches(s, {"new_signins_off": False}, by_user_id=None)
    assert resolve_user(BOB, "supabase-subject-1").email == BOB
    with db.session_scope(system=True) as s:
        ops.set_switches(s, {"new_signins_off": True}, by_user_id=None)
    assert resolve_user(BOB, "supabase-subject-1").email == BOB  # already signed in once: unaffected


def test_members_paused_refuses_every_member_request_but_not_the_admin(client):
    c = client
    c.put("/api/admin/ops", json={"members_paused": True})
    for path in ("/api/me", "/api/holdings", "/api/transactions"):
        r = c.get(path, headers=A)
        assert r.status_code == 503 and "paused by the admin" in r.json()["detail"], path
    assert c.post("/api/feedback", headers=B, json={"text": "hi"}).status_code == 503
    assert c.get("/api/holdings").status_code == 200 and c.get("/api/admin/users").status_code == 200
    assert c.get("/api/health").status_code == 200  # monitors still see the app as up
    c.put("/api/admin/ops", json={"members_paused": False})
    assert c.get("/api/holdings", headers=A).status_code == 200
    assert _actions(c) == ["members_paused_on", "members_paused_off"]


def test_ai_off_stops_every_ai_path_for_everyone(client, monkeypatch):
    import app.llm.provider as provider

    c = client
    c.put("/api/settings/llm", json={"outbound_enabled": True})
    c.put(f"/api/admin/users/{make_user(ALICE)}/ai", json={"ai_enabled": True})
    c.put("/api/admin/ops", json={"ai_off": True})

    def never(*a, **k):
        raise AssertionError("no AI provider may be created while AI is off")

    monkeypatch.setattr(provider.AnthropicProvider, "__init__", never)
    for h in ({}, A):  # the admin and a member with AI enabled
        assert c.get("/api/llm/status", headers=h).json()["gate"] == "AI analysis is switched off for everyone by the admin."
        r = c.post("/api/llm/test", headers=h, json={})
        assert r.status_code == 200 and r.json()["ok"] is False and "switched off for everyone" in r.json()["error"]
        assert c.post("/api/analysis/portfolio", headers=h).status_code in (409, 422)
    c.put("/api/admin/ops", json={"ai_off": False})
    assert c.get("/api/llm/status").json()["gate"] != "AI analysis is switched off for everyone by the admin."
    assert _actions(c)[-2:] == ["ai_off_on", "ai_off_off"]


def test_disable_one_user(client):
    c = client
    alice = make_user(ALICE)
    assert c.put(f"/api/admin/users/{alice}/disabled", headers=B, json={"disabled": True}).status_code == 403
    assert c.put(f"/api/admin/users/{alice}/disabled", json={"disabled": True}).json()["disabled_at"]
    r = c.get("/api/me", headers=A)
    assert r.status_code == 403 and "disabled by the admin" in r.json()["detail"]
    assert c.get("/api/me", headers=B).status_code == 200  # nobody else is affected
    users = {u["email"]: u for u in c.get("/api/admin/users").json()["users"]}
    assert users[ALICE]["disabled"] is True and users[BOB]["disabled"] is False
    assert users[ALICE]["rows"] is not None  # data kept
    me = c.get("/api/me").json()["id"]
    r = c.put(f"/api/admin/users/{me}/disabled", json={"disabled": True})
    assert r.status_code == 422 and "your own account" in r.json()["detail"]
    assert c.put("/api/admin/users/99999/disabled", json={"disabled": True}).status_code == 404
    c.put(f"/api/admin/users/{alice}/disabled", json={"disabled": False})
    assert c.get("/api/me", headers=A).status_code == 200
    audit = c.get("/api/admin/ops").json()["audit"]
    assert [(a["action"], a["target_user_id"]) for a in audit[:2]] == [("user_enabled", alice), ("user_disabled", alice)]
    assert all(a["admin_user_id"] == me for a in audit[:2])


def test_admin_actions_are_audited_without_emails(client):
    c = client
    bob = make_user(BOB)
    c.post("/api/admin/invites", json={"email": CAROL, "send_email": False})
    c.delete(f"/api/admin/invites/{CAROL}")
    c.put(f"/api/admin/users/{bob}/ai", json={"ai_enabled": True, "ai_monthly_cap": 5})
    c.request("DELETE", f"/api/admin/users/{bob}", json={"confirm": BOB})
    c.request("DELETE", "/api/me", headers=A, json={"confirm": ALICE})
    res = c.get("/api/admin/ops").json()
    assert _actions(c) == ["invite_added", "invite_removed", "user_ai_changed", "user_deleted", "account_self_deleted"]
    assert "@" not in str(res["audit"])
    refs = [a["details"].get("email_ref") for a in res["audit"] if a["action"].startswith("invite")]
    assert len(set(refs)) == 1 and len(refs[0]) == 12  # the same hash for the same address
    assert c.put("/api/admin/ops", json={"no_such_switch": True}).status_code == 422
    assert c.get("/api/admin/ops", headers=B).status_code == 403
