"""Isolation: user A can never read, update, delete or export user B's rows, on EVERY endpoint.

Bob (victim) and Alice (attacker) import near-identical workbooks; every Bob row carries the marker BOBMARK. Alice
calls every route in the app with Bob's real ids (path, query and body), and:
- no response may contain BOBMARK or Bob's email (xlsx exports are opened and scanned too);
- no response may be a 5xx (a crash could hide a half-done write);
- a dump of all of Bob's per-user rows must be byte-identical before and after.
Route coverage is asserted: a new route without an isolation case fails this test.
"""

from __future__ import annotations

import io
import re
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import db
from app.main import app
from tests.conftest import base_txn_rows, make_user, write_workbook
from tests.test_routes import PARAM, flat_routes

ALICE, BOB = "alice@example.com", "bob@example.com"
MARK = "BOBMARK"
NOT_EXERCISED = {("GET", "/api/health")}  # public, no data


def bob_rows():
    rows = base_txn_rows()
    return [[r[0], r[1], r[2], f"{MARK} {r[3]}", *r[4:12], f"{MARK} note"] for r in rows]


@pytest.fixture
def world(tmp_path, monkeypatch):
    db.configure(f"sqlite:///{tmp_path / 'iso.db'}")
    _offline(monkeypatch)
    with TestClient(app) as c:
        a_book = write_workbook(tmp_path / "alice.xlsx")
        b_book = write_workbook(tmp_path / "bob.xlsx", txn_rows=bob_rows())
        for who, book in ((ALICE, a_book), (BOB, b_book)):
            r = c.post("/api/import", headers={"X-Dev-User": who}, files={"file": ("w.xlsx", book.read_bytes())})
            assert r.status_code == 200 and r.json()["report"]["ok"], r.text
        ids = _bob_objects(c, tmp_path, b_book)
        yield c, ids, a_book


def _offline(monkeypatch):
    """No network in this test: every outside source fails fast."""
    import httpx

    import app.api.routes as routes
    from app.market import intraday, service
    from app.net import polite
    from app.resolve import sources
    from app.services import fundamentals, macro, valuation

    def boom(*a, **k):
        raise RuntimeError("offline in tests")

    monkeypatch.setattr(routes, "resolve_identifiers", lambda s: {"summary": "skipped in tests"})
    monkeypatch.setattr(service, "default_providers", lambda: [])
    monkeypatch.setattr(sources, "download", boom)
    monkeypatch.setattr(fundamentals, "yfinance_info", boom)
    monkeypatch.setattr(valuation, "fetch_payload", boom)
    monkeypatch.setattr(macro, "yf_last_close", boom)
    monkeypatch.setattr(intraday, "yf_download", boom)
    monkeypatch.setattr(polite, "_default", polite.PoliteClient(
        transport=httpx.MockTransport(lambda req: (_ for _ in ()).throw(httpx.ConnectError("offline", request=req))),
        min_interval=0, sleep=lambda _s: None))


def _bob_objects(c, tmp_path, b_book) -> dict:
    """Create one of every kind of Bob object and return their ids."""
    from app.market.base import Quote
    from app.market.service import store_quote
    from app.models import (Alert, FundDisclosure, IdentifierCandidate, Instrument, LlmAnalysis, QualitativeEntry,
                            Transaction)
    from decimal import Decimal as D

    H = {"X-Dev-User": BOB}
    bob = make_user(BOB)
    with db.session_scope(user_id=bob) as s:
        lt = s.scalar(select(Instrument).where(Instrument.symbol == "LT"))
        fund = s.scalar(select(Instrument).where(Instrument.asset_type == "MF"))
        for i in s.scalars(select(Instrument).where(Instrument.symbol.is_not(None))):
            store_quote(s, i.id, Quote(D("100"), date(2026, 10, 1), "test", i.symbol))
        s.add(IdentifierCandidate(instrument_id=fund.id, kind="SCHEME_CODE", value="999", label=f"{MARK} cand",
                                  source="AMFI", score=0.9, details={}))
        d = FundDisclosure(instrument_id=fund.id, kind="AMC_DISCLOSURE", as_of=date(2026, 9, 30), parser="t",
                           source_file=f"{MARK}.xlsx", file_sha256="0" * 64, equity_weight=D("0.9"), rows=0)
        s.add(d)
        s.add(Alert(rule="announcement", dedupe_key=f"{MARK}-1", instrument_id=lt.id, title=f"{MARK} alert", detail="x"))
        s.add(LlmAnalysis(kind="stock", instrument_id=lt.id, input_hash="b" * 64, input_json={"x": MARK},
                          output_json={"y": MARK}, status="OK", model="m", prompt_version="v"))
        s.flush()
        ids = {"iid": lt.id, "fund": fund.id, "cid": s.scalar(select(IdentifierCandidate.id)), "did": d.id,
               "alert": s.scalar(select(Alert.id)), "analysis": s.scalar(select(LlmAnalysis.id))}
    r = c.post("/api/transactions", headers=H, json={"date": "2026-10-05", "type": "BUY", "instrument_id": ids["iid"],
                                                     "quantity": "1", "price": "100", "amount": "100",
                                                     "notes": f"{MARK} ui"})
    assert r.status_code in (200, 201), r.text
    with db.session_scope(user_id=bob) as s:
        ids["txn"] = s.scalar(select(Transaction.id).where(Transaction.source == "ui"))
    assert c.post(f"/api/journal/{ids['iid']}", headers=H,
                  json={"why": f"{MARK} thesis", "change_view": f"{MARK} c", "horizon": "5y"}).status_code == 201
    assert c.post(f"/api/qualitative/{ids['iid']}", headers=H, json={
        "moat_type": "brand", "moat_note": f"{MARK} moat", "capital_allocation_note": f"{MARK} cap",
        "source_note": f"{MARK} src", "as_of": "2026-10-01"}).status_code == 201
    assert c.put(f"/api/peers/{ids['iid']}", headers=H, json={"symbols": ["ABB"], "note": f"{MARK} peers"}).status_code == 200
    assert c.put(f"/api/facts/{ids['iid']}/roce", headers=H,
                 json={"value": "12", "source_note": f"{MARK} AR", "as_of": "2026-09-30"}).status_code == 200
    assert c.put(f"/api/instruments/{ids['iid']}/classification", headers=H, json={"sector": f"{MARK} sector"}).status_code == 200
    assert c.put("/api/settings/targets", headers=H, json={"Mutual funds": "20", "Indian stocks": "60",
                                                           "International ETFs": "10", "Gold": "5",
                                                           "Debt/Cash": "5"}).status_code == 200
    assert c.post("/api/snapshots", headers=H).status_code == 200
    r = c.post("/api/import/preview", headers=H, files={"file": ("w.xlsx", b_book.read_bytes())})
    ids["token"] = r.json()["token"]
    ids["user_id"] = bob
    return ids


def _dump_bob(bob_id: int) -> dict:
    from app.services.accounts import _user_tables

    out = {}
    with db.session_scope(system=True) as s:
        for t in _user_tables():
            rows = s.execute(select(t).where(t.c.user_id == bob_id).order_by(*t.primary_key.columns)).all()
            out[t.name] = [tuple(str(v) for v in r) for r in rows]
    return out


def _url(path: str, ids: dict) -> str:
    def sub(m):
        name = m.group(1)
        if "/analysis" in path and name == "aid":
            return str(ids["analysis"])
        if "/alerts" in path and name == "aid":
            return str(ids["alert"])
        table = {"iid": ids["iid"], "cid": ids["cid"], "txn_id": ids["txn"], "did": ids["did"],
                 "user_id": ids["user_id"], "section": "targets", "field": "sector", "metric": "roce",
                 "key": "repo_rate", "sector": "Construction", "email": BOB}
        if name not in table:
            raise AssertionError(f"add an isolation id for path parameter {name!r} ({path})")
        return str(table[name])
    url = PARAM.sub(sub, path)
    if "/analysis/fund/" in path:
        url = url.replace(f"/{ids['iid']}", f"/{ids['fund']}")
    return url


def _body(method: str, path: str, ids: dict, a_book):
    """Valid bodies that point at Bob's objects, so a missing ownership check would really act on them."""
    p, b = path, ids
    kw: dict = {}
    if p in ("/api/import", "/api/import/preview"):
        kw["files"] = {"file": ("w.xlsx", a_book.read_bytes())}
    elif p == "/api/disclosures":
        kw["files"] = {"file": ("d.xlsx", a_book.read_bytes())}
        kw["params"] = {"instrument_id": b["fund"], "kind": "INDEX_WEIGHTS", "as_of": "2026-09-30", "index_name": "X"}
    elif p == "/api/mappings/confirm-exact":
        kw["json"] = {"candidate_ids": [b["cid"]]}
    elif p == "/api/import/confirm":
        kw["json"] = {"token": b["token"]}
    elif p == "/api/transactions" and method == "POST":
        kw["json"] = {"date": "2026-10-06", "type": "BUY", "instrument_id": b["iid"], "quantity": "1", "price": "1",
                      "amount": "1"}
    elif p == "/api/simulator":
        kw["json"] = {"amount": "1000", "instrument_id": b["iid"]}
    elif p == "/api/planner":
        kw["json"] = {"budget": "1000", "picks": [b["iid"], b["fund"]]}
    elif p == "/api/projection":
        kw["json"] = {}
    elif p.startswith("/api/instruments/") and method == "PUT":
        kw["json"] = {"sector": "Hacked", "asset_class": "Gold", "region": "Hacked"}
    elif p.startswith("/api/facts/") and method == "PUT":
        kw["json"] = {"value": "1", "source_note": "hack", "as_of": "2026-10-01"}
    elif p.startswith("/api/settings/") and method == "PUT":
        kw["json"] = {"Mutual funds": "100", "Indian stocks": "0", "International ETFs": "0", "Gold": "0", "Debt/Cash": "0"}
    elif p.startswith("/api/macro/") and method == "PUT":
        kw["json"] = {"value": "6.5", "source_note": "x", "as_of": "2026-10-01"}
    elif p.startswith("/api/sensitivities/"):
        kw["json"] = {"tags": ["rate-sensitive"]}
    elif p.startswith("/api/journal/") and method == "POST":
        kw["json"] = {"why": "hack", "change_view": "hack", "horizon": "1y", "linked_txn_ids": [b["txn"]]}
    elif p.endswith("/optin"):
        kw["json"] = {"send_to_llm": True}
    elif p.startswith("/api/peers/") and method == "PUT":
        kw["json"] = {"symbols": ["SIEMENS"], "note": "hack"}
    elif p.startswith("/api/qualitative/") and method == "POST":
        kw["json"] = {"moat_type": "brand", "moat_note": "h", "capital_allocation_note": "h", "source_note": "h",
                      "as_of": "2026-10-01"}
    elif p == "/api/me" and method == "DELETE":
        kw["json"] = {"confirm": BOB}  # Bob's email: must not delete anyone
    elif p == "/api/me/ai-key":
        kw["json"] = {"key": None}
    elif p == "/api/admin/invites":
        kw["json"] = {"email": "mallory@example.com", "send_email": False}
    elif p.startswith("/api/admin/users/") and p.endswith("/ai"):
        kw["json"] = {"ai_enabled": True, "ai_monthly_cap": 999}
    elif p.startswith("/api/admin/users/") and method == "DELETE":
        kw["json"] = {"confirm": BOB}
    elif p == "/api/llm/test":
        kw["json"] = {}
    elif p == "/api/compare":
        kw["params"] = {"a": "2026-10-01", "b": "live"}
    return kw


def _text(resp) -> str:
    ctype = resp.headers.get("content-type", "")
    if "spreadsheetml" in ctype:
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(resp.content), read_only=True)
        return "\n".join(str(v) for ws in wb.worksheets for row in ws.iter_rows(values_only=True) for v in row if v)
    return resp.text


def _attack(c, ids, a_book) -> tuple[list[str], dict, set]:
    """Alice calls every route with Bob's ids. Returns (problems, Bob's changed tables, routes covered)."""
    before = _dump_bob(ids["user_id"])
    assert sum(len(v) for v in before.values()) > 50 and any(MARK in str(v) for v in before.values())
    A = {"X-Dev-User": ALICE}
    covered, problems = set(), []
    for path, route in flat_routes(app.routes):
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            if (method, path) in NOT_EXERCISED:
                continue
            covered.add((method, path))
            r = c.request(method, _url(path, ids), headers=A, **_body(method, path, ids, a_book))
            body = _text(r)
            if r.status_code >= 500:
                problems.append(f"{method} {path}: {r.status_code} {body[:200]}")
            if MARK in body or BOB in body:
                problems.append(f"{method} {path}: leaked Bob's data ({r.status_code})")
    after = _dump_bob(ids["user_id"])
    changed = {t: (len(before[t]), len(after[t])) for t in before if before[t] != after[t]}
    return problems, changed, covered


def test_alice_cannot_touch_bobs_data_on_any_route(world):
    c, ids, a_book = world
    problems, changed, covered = _attack(c, ids, a_book)
    assert problems == []
    assert changed == {}, f"Alice changed Bob's rows: {changed}"
    all_routes = {(m, p) for p, r in flat_routes(app.routes) for m in r.methods - {"HEAD", "OPTIONS"}}
    assert all_routes - NOT_EXERCISED == covered


def test_the_attack_detects_a_forgotten_filter(world, monkeypatch):
    """Self-check: with per-user filtering switched off (as if a query forgot it), the attack must find leaks."""
    from app import tenancy

    c, ids, a_book = world
    monkeypatch.setattr(tenancy, "is_system", lambda s: True)  # every session behaves like an unfiltered job
    problems, changed, _ = _attack(c, ids, a_book)
    leaks = [p for p in problems if "leaked" in p]
    assert len(leaks) >= 10, problems
    assert changed, "deleting/updating Bob's rows should have been possible without the filter"


def test_alice_still_sees_her_own_data(world):
    c, ids, _ = world
    A = {"X-Dev-User": ALICE}
    h = c.get("/api/holdings", headers=A).json()
    assert len(h["equity"]) == 16 and not any(MARK in x["name"] for x in h["equity"])
    names = [t["name"] for t in c.get("/api/transactions", headers=A).json()]
    assert names and not any(MARK in n for n in names)


def test_guessed_ids_and_tokens_are_not_found(world):
    c, ids, _ = world
    A = {"X-Dev-User": ALICE}
    assert c.get(f"/api/valuation/{ids['iid']}", headers=A).status_code == 404
    assert c.get(f"/api/journal/{ids['iid']}/history", headers=A).json() == []
    assert c.post("/api/import/confirm", headers=A, json={"token": ids["token"]}).status_code == 404
    assert c.delete(f"/api/transactions/{ids['txn']}", headers=A).status_code == 404
    assert c.get(f"/api/analysis/sent/{ids['analysis']}", headers=A).status_code == 404


def test_admin_routes_are_admin_only(world):
    c, ids, _ = world
    A = {"X-Dev-User": ALICE}
    assert c.get("/api/admin/users", headers=A).status_code == 403
    assert c.put(f"/api/admin/users/{ids['user_id']}/ai", headers=A, json={"ai_enabled": True}).status_code == 403
    assert c.put("/api/settings/news", headers=A, json={"feeds": []}).status_code == 403
    admin = c.get("/api/admin/users").json()  # the dev user (owner@localhost) is the admin
    emails = {u["email"] for u in admin["users"]}
    assert {ALICE, BOB} <= emails


def test_no_session_without_a_user_can_touch_user_tables(tmp_path):
    from app.models import Transaction
    from app.tenancy import TenantError

    db.configure(f"sqlite:///{tmp_path / 'fc.db'}")
    db.init_db()
    with pytest.raises(TenantError):
        with db.session_scope() as s:
            s.scalars(select(Transaction)).all()
    with pytest.raises(TenantError):
        with db.session_scope() as s:
            s.add(Transaction(instrument_id=1, date=date(2026, 1, 1), type="BUY", amount_paise=1, row_key="x"))
            s.flush()


def test_rows_are_stamped_and_cross_user_writes_refused(tmp_path):
    from app.models import AppSetting
    from app.tenancy import TenantError

    db.configure(f"sqlite:///{tmp_path / 'st.db'}")
    db.init_db()
    a, b = make_user(ALICE), make_user(BOB)
    with db.session_scope(user_id=a) as s:
        s.add(AppSetting(key="drift", value={"tolerance_pp": "3"}))
    with db.session_scope(system=True) as s:
        assert s.scalar(select(AppSetting.user_id)) == a
    with pytest.raises(TenantError):
        with db.session_scope(user_id=a) as s:
            s.add(AppSetting(key="themes", value={}, user_id=b))
            s.flush()


def test_every_table_with_user_id_is_scoped():
    from app.services.accounts import assert_user_owned_complete

    assert_user_owned_complete()
