"""'Confirm all exact matches': only exact / high-confidence proposals are applied; the rest stay for review."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import db
from app.resolve.bulk import HIGH_SCORE, MIN_MARGIN, plan


def inst(iid, kind, cands, confirmed=False, name="X"):
    return {"instrument_id": iid, "name": name, "needed_kind": kind, "confirmed": confirmed,
            "candidates": [{"id": i, "kind": kind, "value": v, "label": v, "score": sc, "status": st, "details": d}
                           for i, v, sc, st, d in cands]}


def test_rules():
    p = plan([
        inst(1, "ISIN", [(11, "INE1", 1.0, "PENDING", {"exact_symbol_match": True})]),            # exact: apply
        inst(2, "ISIN", [(21, "INE2", 1.0, "PENDING", {})]),                                       # not exact
        inst(3, "ISIN", [(31, "INE3", 1.0, "PENDING", {"exact_symbol_match": True}),
                         (32, "INE4", 1.0, "PENDING", {"exact_symbol_match": True})]),            # two: ambiguous
        inst(4, "SCHEME_CODE", [(41, "100", 0.97, "PENDING", {}), (42, "101", 0.70, "PENDING", {})]),  # clear lead
        inst(5, "SCHEME_CODE", [(51, "200", 0.96, "PENDING", {}), (52, "201", 0.92, "PENDING", {})]),  # too close
        inst(6, "SCHEME_CODE", [(61, "300", 0.80, "PENDING", {})]),                                # below threshold
        inst(7, "SCHEME_CODE", [(71, "400", 0.99, "REJECTED", {}), (72, "401", 0.93, "PENDING", {})]),  # rejected ignored
        inst(8, "SCHEME_CODE", [(81, "500", 0.99, "CONFIRMED", {})], confirmed=True),             # already done
        inst(9, "SCHEME_CODE", []),
    ])
    assert [a["candidate_id"] for a in p["apply"]] == [11, 41, 72]
    reasons = {m["instrument_id"]: m["reason"] for m in p["manual"]}
    assert reasons == {2: "not an exact symbol match", 3: "2 candidates", 5: "ambiguous: 0.96 vs 0.92",
                       6: f"best score 0.80 is below {HIGH_SCORE:.2f}", 9: "no proposed match yet"}
    assert p["rules"] == {"high_score": HIGH_SCORE, "min_margin": MIN_MARGIN}


def test_endpoints_list_first_then_confirm_only_the_safe_ones(tmp_path, workbook, monkeypatch):
    import app.api.routes as routes
    from app.models import IdentifierCandidate, Instrument
    from tests.conftest import make_user

    monkeypatch.setattr(routes, "resolve_identifiers", lambda s: {"summary": "skipped"})
    db.configure(f"sqlite:///{tmp_path / 'b.db'}")
    from app.main import app

    with TestClient(app) as c:
        c.post("/api/import", files={"file": ("w.xlsx", workbook.read_bytes())})
        with db.session_scope(user_id=make_user()) as s:
            lt = s.scalar(select(Instrument).where(Instrument.symbol == "LT"))
            funds = list(s.scalars(select(Instrument).where(Instrument.asset_type == "MF").order_by(Instrument.id)))
            s.add_all([
                IdentifierCandidate(instrument_id=lt.id, kind="ISIN", value="INE018A01030", label="LT", source="NSE",
                                    score=1.0, details={"exact_symbol_match": True}),
                IdentifierCandidate(instrument_id=funds[0].id, kind="SCHEME_CODE", value="118989", label="a",
                                    source="AMFI", score=0.95, details={}),
                IdentifierCandidate(instrument_id=funds[1].id, kind="SCHEME_CODE", value="120716", label="b",
                                    source="AMFI", score=0.91, details={}),
                IdentifierCandidate(instrument_id=funds[1].id, kind="SCHEME_CODE", value="120717", label="c",
                                    source="AMFI", score=0.90, details={}),
            ])
        preview = c.get("/api/mappings/exact-matches").json()
        safe = [a["candidate_id"] for a in preview["apply"]]
        assert len(safe) == 2  # LT's exact ISIN and the clear fund match; nothing changed yet
        assert c.get("/api/mappings").json()["pending"] > 0
        manual_ids = [m["instrument_id"] for m in preview["manual"]]
        assert funds[1].id in manual_ids  # 0.91 vs 0.90: left for a person
        ambiguous = [cid for cid in range(1, 100) if cid not in safe][:1]
        r = c.post("/api/mappings/confirm-exact", json={"candidate_ids": safe + ambiguous}).json()
        assert sorted(r["confirmed"]) == sorted(safe) and [x["candidate_id"] for x in r["skipped"]] == ambiguous
        rows = {x["instrument_id"]: x for x in c.get("/api/mappings").json()["instruments"]}
        assert rows[lt.id]["status"] == "CONFIRMED" and rows[lt.id]["isin"] == "INE018A01030"
        assert rows[funds[0].id]["scheme_code"] == "118989" and rows[funds[1].id]["status"] == "PENDING"
        assert r["remaining"]["apply"] == []
