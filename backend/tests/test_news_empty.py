"""When the News page shows 0 items, say why."""

from app.calc.news import empty_explanation


def src(name, ok=True, fetched=0, matched=0, message="ok"):
    return {"source": name, "ok": ok, "items_fetched": fetched if ok else None, "items_matched": matched if ok else None,
            "message": message}


def test_never_fetched():
    e = empty_explanation([], tracked=3, untracked=0, days=30)
    assert e["kind"] == "NOT_FETCHED" and "Refresh" in e["message"]


def test_items_fetched_but_no_tracked_holdings():
    e = empty_explanation([src("NSE: Online announcements", fetched=120), src("Livemint markets", fetched=35)],
                          tracked=0, untracked=14, days=30)
    assert e["kind"] == "NO_TRACKED_HOLDINGS"
    assert e["message"].startswith("155 items fetched, none matched because no holdings are tracked")
    assert "confirm ISINs on Mappings" in e["message"] and "14" in e["message"]


def test_all_sources_failed():
    e = empty_explanation([src("NSE: Online announcements", ok=False, message="Source unavailable (x: ReadTimeout after 2 attempts, timeout 25s)"),
                           src("Livemint markets", ok=False, message="Source unavailable (HTTP 403; not retried)")],
                          tracked=5, untracked=0, days=30)
    assert e["kind"] == "SOURCES_FAILED"
    assert e["message"].startswith("All 2 sources failed")
    assert [f["source"] for f in e["failed"]] == ["NSE: Online announcements", "Livemint markets"]


def test_fetched_but_nothing_mentions_tracked_companies_with_some_failures():
    e = empty_explanation([src("NSE: Online announcements", fetched=80), src("Livemint markets", ok=False, message="down")],
                          tracked=5, untracked=0, days=30)
    assert e["kind"] == "NO_MATCHES"
    assert e["message"] == ("80 items fetched from 1 source; none were about your 5 tracked companies in the last 30 days. "
                            "1 source failed (see below).")


def test_tracked_but_zero_fetched():
    e = empty_explanation([src("NSE: Online announcements", fetched=0)], tracked=5, untracked=0, days=30)
    assert e["kind"] == "NO_ITEMS" and e["message"].startswith("Sources answered but returned 0 items")


def test_feed_api_carries_the_explanation(tmp_path, monkeypatch):
    import httpx
    from fastapi.testclient import TestClient

    from app import db
    from app.main import app
    from app.net import polite

    db.configure(f"sqlite:///{tmp_path / 'n.db'}")

    def boom(req):
        raise httpx.ConnectError("down", request=req)

    monkeypatch.setattr(polite, "_default", polite.PoliteClient(transport=httpx.MockTransport(boom), min_interval=0,
                                                                sleep=lambda _s: None))
    with TestClient(app) as c:
        assert c.get("/api/news").json()["empty"]["kind"] == "NOT_FETCHED"
        c.post("/api/news/refresh")
        body = c.get("/api/news").json()
        assert body["items"] == [] and body["empty"]["kind"] == "SOURCES_FAILED"


def test_filtered_empty_view_says_so(session, workbook):
    from app.services.news import feed

    assert feed(session, category="results")["empty"]["kind"] == "FILTERED"


def test_counts_unknown_from_before_they_were_recorded_are_not_zero():
    legacy = {"source": "ET Markets", "ok": True, "items_fetched": None, "items_matched": None, "message": "ok (50 items)"}
    e = empty_explanation([legacy], tracked=0, untracked=14, days=30)
    assert e["message"].startswith("Items fetched, none matched because no holdings are tracked")
    assert empty_explanation([legacy], tracked=5, untracked=0, days=30)["kind"] == "NO_MATCHES"
