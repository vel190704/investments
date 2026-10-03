import json

from app.calc.emergency import emergency_status
from app.services import settings as st
from tests.test_api import client, price_everything, upload  # noqa: F401  (fixture reuse)


def test_emergency_status_maths():
    s = emergency_status(3_000_000, 5_000_000, 6)
    assert s["target_paise"] == 18_000_000 and s["remaining_paise"] == 13_000_000
    assert s["percent_complete"].startswith("0.2777")
    full = emergency_status(3_000_000, 20_000_000, 3)
    assert full["remaining_paise"] == 0 and full["complete"]


ENDPOINTS = ["/api/portfolio/summary", "/api/holdings", "/api/allocation", "/api/xirr", "/api/snapshots/series"]


def test_emergency_fund_never_touches_the_portfolio(client, workbook):
    upload(client, workbook)
    price_everything()
    client.post("/api/snapshots")
    before = {e: client.get(e).json() for e in ENDPOINTS}
    r = client.put("/api/settings/emergency_fund",
                   json={"monthly_expenses_paise": 3_000_000, "balance_paise": 9_999_999_00, "target_months": 6})
    assert r.status_code == 200
    client.post("/api/snapshots")  # same-day upsert
    after = {e: client.get(e).json() for e in ENDPOINTS}

    def strip(d):  # volatile timestamps are not portfolio numbers
        txt = json.dumps(d, sort_keys=True)
        return json.loads(txt)
    for e in ENDPOINTS:
        b, a = strip(before[e]), strip(after[e])
        if e == "/api/snapshots/series":
            assert [p["value_paise"] for p in a["points"]] == [p["value_paise"] for p in b["points"]]
        else:
            assert a == b, e
    ef = client.get("/api/emergency-fund").json()
    assert ef["status"]["target_paise"] == 18_000_000
    assert "separate" in ef["note"].lower()
    planner = client.post("/api/planner", json={"budget": "10000"}).json()
    assert all(c["asset_class"] != "Emergency fund" for m in planner["modes"] if m["available"]
               for c in m["asset_classes"])


def test_emergency_fund_empty_state(client):
    ef = client.get("/api/emergency-fund").json()
    assert ef["status"] is None and ef["is_set"] is False
