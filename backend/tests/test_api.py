from datetime import date
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import db
from app.main import app
from app.market.base import Quote
from app.market.service import store_quote
from app.models import Instrument

PRICES = {"LT": "3693.40", "RELIANCE": "1180", "SBIN": "950", "HDFCBANK": "700", "KPITTECH": "520",
          "HNGSNGBEES": "455.10", "COALINDIA": "420", "BEL": "400", "BIOCON": "390", "INDUSTOWER": "380",
          "TATAPOWER": "370", "ITC": "260", "MAFANG": "248.21", "MOSCHIP": "198.08", "TATASTEEL": "180",
          "ASHOKLEY": "160"}
NAVS = {"HDFC": "219.441", "ICICI": "237.3337", "Kotak": "20.2442"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    db.configure(f"sqlite:///{tmp_path / 'api.db'}")
    import app.api.routes as routes
    monkeypatch.setattr(routes, "resolve_identifiers", lambda s: {"summary": "skipped in tests"})
    with TestClient(app) as c:
        yield c


def price_everything():
    with db.session_scope() as s:
        for i in s.scalars(select(Instrument)):
            if i.symbol:
                store_quote(s, i.id, Quote(D(PRICES[i.symbol]), date(2026, 10, 1), "test", i.symbol, D(PRICES[i.symbol])))
            else:
                nav = next(v for k, v in NAVS.items() if i.name.startswith(k))
                i.scheme_code = "1"
                store_quote(s, i.id, Quote(D(nav), date(2026, 10, 1), "test", "1"))


def upload(client, path):
    with open(path, "rb") as f:
        return client.post("/api/import", files={"file": ("book.xlsx", f, "application/octet-stream")})


def test_upload_reupload_and_dashboard(client, workbook):
    r = upload(client, workbook).json()
    assert r["report"]["ok"] and r["report"]["transactions"]["loaded"] == 19
    r2 = upload(client, workbook).json()
    assert r2["report"]["transactions"]["inserted"] == 0
    assert len(client.get("/api/transactions").json()) == 19

    s = client.get("/api/portfolio/summary").json()
    assert s["total_value_paise"] == 0 and len(s["excluded_unpriced"]) == 19  # nothing fabricated

    price_everything()
    s = client.get("/api/portfolio/summary").json()
    assert s["total_invested_paise"] == 1865702 and s["excluded_unpriced"] == []
    assert s["pnl_paise"] == s["total_value_paise"] - s["total_invested_paise"]
    assert s["monthly_plan"]["monthly_total_paise"] == 1_000_000
    assert sum(D(a["weight"]) for a in s["asset_classes"]) == pytest.approx(D(1), abs=D("1e-6"))
    assert abs(sum(D(a["display_pct"]) for a in s["asset_classes"]) - 100) <= D("0.15")
    assert {a["name"] for a in s["asset_classes"]} == {"Mutual funds", "Indian stocks", "International ETFs"}
    assert s["xirr"]["note"] == "N/A (needs dated transactions)"
    assert s["today_change"]["not_covered"]  # MFs: no previous NAV, stated rather than guessed

    h = client.get("/api/holdings").json()
    assert len(h["equity"]) == 16 and len(h["mutual_funds"]) == 3
    assert sum(D(x["weight"]) for x in h["equity"] + h["mutual_funds"]) == pytest.approx(D(1), abs=D("1e-6"))
    lt = next(x for x in h["equity"] if x["symbol"] == "LT")
    assert lt["pnl_paise"] == 369340 - 376800 and lt["xirr"]["note"].startswith("N/A")

    a = client.get("/api/allocation").json()
    assert a["concentration"]["flags"][0]["reason"].startswith("LT is ")
    assert sum(D(x["weight"]) for x in a["instruments"]) == pytest.approx(D(1), abs=D("1e-6"))


def test_simulator_endpoint(client, workbook):
    upload(client, workbook)
    price_everything()
    opts = client.get("/api/simulator/options").json()
    assert opts["presets_rupees"] == [500, 1000, 2000, 4000, 10000]
    assert [o["key"].split(":")[0] for o in opts["default_scenarios"]] == ["mf", "mf", "mf", "mf_plan_split"]
    lt_id = next(i["instrument_id"] for i in opts["instruments"] if i["short_name"] == "LT")
    r = client.post("/api/simulator", json={"amount": "1000",
                                            "scenario_keys": [opts["default_scenarios"][1]["key"], f"inst:{lt_id}"]})
    assert r.status_code == 200
    sc = r.json()["scenarios"]
    assert sc[0]["invested_paise"] == 100000
    assert "below the price of one unit" in sc[1]["sentences"][0]
    assert client.post("/api/simulator", json={"amount": "-5"}).status_code == 422
    assert client.post("/api/simulator", json={"amount": "abc"}).status_code == 422


def test_upload_rejects_non_xlsx(client):
    r = client.post("/api/import", files={"file": ("x.csv", b"a,b", "text/csv")})
    assert r.status_code == 400


def test_xirr_endpoint_opening_only(client, workbook):
    upload(client, workbook)
    price_everything()
    x = client.get("/api/xirr").json()
    assert x["portfolio"]["note"] == "N/A (needs dated transactions)"
    assert {c["asset_class"] for c in x["asset_classes"]} == {"Mutual funds", "Indian stocks", "International ETFs"}
    assert all(c["note"] == "N/A (needs dated transactions)" for c in x["asset_classes"])
    assert len(x["instruments"]) == 19


TARGETS = {"Mutual funds": "50", "Indian stocks": "30", "International ETFs": "10", "Gold": "5", "Debt/Cash": "5"}


def test_drift_requires_targets_then_reports(client, workbook):
    upload(client, workbook)
    price_everything()
    d = client.get("/api/allocation").json()["drift"]
    assert not d["targets_set"] and d["message"] == "Set your targets in Settings to see drift."
    assert client.put("/api/settings/targets", json={**TARGETS, "Gold": "6"}).status_code == 422
    assert client.put("/api/settings/targets", json=TARGETS).status_code == 200
    a = client.get("/api/allocation").json()
    rows = {r["asset_class"]: r for r in a["drift"]["rows"]}
    assert set(rows) == set(TARGETS) and rows["Gold"]["status"] == "WITHIN BAND"  # 0 vs 5: at band edge
    assert {p["asset_class"] for p in a["not_held"]} == {"Gold", "Debt/Cash"}


def test_planner_endpoint(client, workbook):
    upload(client, workbook)
    price_everything()
    p = client.post("/api/planner", json={}).json()
    assert p["budget_paise"] == 1_000_000 and p["budget_source"] == "monthly_plan sheet"
    plan, targets = p["modes"]
    assert plan["available"] and plan["invested_paise"] == 1_000_000
    assert not targets["available"]
    client.put("/api/settings/targets", json=TARGETS)
    p = client.post("/api/planner", json={"budget": "15000", "picks": []}).json()
    assert p["budget_source"].startswith("temporary override") and all(m["available"] for m in p["modes"])
    assert sum(c["add_paise"] for c in p["modes"][1]["asset_classes"]) == 1_500_000
    assert client.post("/api/planner", json={"budget": "abc"}).status_code == 422


def test_projection_endpoint_defaults_and_wording(client, workbook):
    upload(client, workbook)
    price_everything()
    r = client.post("/api/projection", json={}).json()
    total = client.get("/api/portfolio/summary").json()["total_value_paise"]
    assert r["inputs"]["start_paise"] == total and r["inputs"]["monthly_paise"] == 1_000_000
    assert r["inputs"]["years"] == 10 and not r["rates_reviewed"] and "placeholders" in r["rates_note"]
    assert [s["name"] for s in r["scenarios"]] == ["Conservative", "Base", "Higher"]
    assert r["scenarios"][0]["ending_value_paise"] < r["scenarios"][2]["ending_value_paise"]
    assert abs(r["closed_form_check_paise"] - r["scenarios"][1]["ending_value_paise"]) <= 1
    assert r["scenarios"][1]["sentence"].startswith("If the portfolio averaged 9% annually")
    r = client.post("/api/projection", json={"years": 5, "step_up": "10", "custom_rate": "7.5", "monthly": "8000"}).json()
    assert [s["name"] for s in r["scenarios"]][-1] == "Custom" and r["inputs"]["step_up_pct"] == "10"
    assert client.post("/api/projection", json={"years": 99}).status_code == 422
