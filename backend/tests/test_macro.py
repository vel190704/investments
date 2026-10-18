from datetime import date
from decimal import Decimal as D

import pytest

from tests.conftest import make_user
from app.calc.scenarios import STARTER, exposure_by_tag
from app.importer.run import import_workbook
from app.services import macro as mc


def test_auto_values_and_na_on_failure(session):
    def fetch(ticker):
        if ticker == "BZ=F":
            raise ConnectionError("offline")
        return {"INR=X": (D("94.96"), date(2026, 10, 17)), "^NSEI": (D("23146.15"), date(2026, 10, 16))}[ticker]
    rep = mc.refresh_macro(session, fetch)
    assert rep["usd_inr"] == "ok" and rep["brent_usd"].startswith("unavailable")
    snap = {r["key"]: r for r in mc.snapshot(session)}
    assert snap["usd_inr"]["display"] == "94.96" and snap["usd_inr"]["as_of"] == "2026-10-17"
    assert "yfinance (INR=X)" in snap["usd_inr"]["source"]
    assert snap["brent_usd"]["value"] is None and snap["brent_usd"]["display"] == "N/A (source unavailable)"
    assert snap["repo_rate"]["display"] == "N/A (enter it manually with a source)"  # never filled from memory
    assert snap["cpi_inflation"]["value"] is None


def test_failure_after_success_does_not_keep_stale_value(session):
    mc.refresh_macro(session, lambda t: (D("100"), date(2026, 10, 16)))
    def down(t):
        raise TimeoutError("x")
    mc.refresh_macro(session, down)
    assert all(r["value"] is None for r in mc.snapshot(session) if r["origin"] == "AUTO")


def test_manual_entry_requires_source_and_date(session):
    mc.set_manual(session, "repo_rate", None, "5.5", None, "RBI MPC statement 2026-10-01", date(2026, 10, 1))
    r = next(r for r in mc.snapshot(session) if r["key"] == "repo_rate")
    assert r["display"] == "5.5" and r["source"] == "manual: RBI MPC statement 2026-10-01" and r["unit"] == "% p.a."
    with pytest.raises(mc.MacroError, match="source note"):
        mc.set_manual(session, "cpi_inflation", None, "3.1", None, "", date(2026, 9, 30))
    with pytest.raises(mc.MacroError, match="future"):
        mc.set_manual(session, "cpi_inflation", None, "3.1", None, "MoSPI", date(2027, 1, 1))
    with pytest.raises(mc.MacroError, match="automated"):
        mc.set_manual(session, "usd_inr", None, "90", None, "x", date(2026, 10, 1))


def test_exposure_by_tag_sums_lookthrough_sector_weights():
    rows = [{"sector": "Financial Services", "pct": "0.12"}, {"sector": "Construction", "pct": "0.21"},
            {"sector": "Information Technology", "pct": "0.04"}, {"sector": "Debt, cash & other inside funds", "pct": "0.2"}]
    sens = {k: v for k, v in STARTER.items()}
    out = {s["scenario"]: s for s in exposure_by_tag(rows, sens, [("LT", "Construction"), ("SBIN", "Financial Services"),
                                                                   ("KPITTECH", "Information Technology")])}
    rate = out["rate_cut"]["tags"][0]
    assert rate["tag"] == "rate-sensitive" and D(rate["weight"]) == D("0.33") and rate["holdings"] == ["LT", "SBIN"]
    fx = {t["tag"]: t for t in out["weaker_rupee"]["tags"]}
    assert D(fx["export/currency-exposed"]["weight"]) == D("0.04")
    assert D(fx["import/currency-exposed"]["weight"]) == D("0")


def test_starter_tags_are_labelled_and_user_edits_win(session, workbook):
    import_workbook(session, workbook)
    mc.ensure_starter(session, ["Construction", "Unknown sector"])
    from sqlalchemy import select as _select

    from app.models import SectorSensitivity as _SS

    row = session.scalar(_select(_SS).where(_SS.sector == "Construction"))
    assert row.origin == "STARTER" and "review and edit" in row.note
    mc.set_tags(session, "Construction", ["rate-sensitive"])
    mc.ensure_starter(session, ["Construction"])
    assert row.origin == "USER" and row.tags == ["rate-sensitive"]
    with pytest.raises(mc.MacroError):
        mc.set_tags(session, "Construction", ["bullish"])


def test_sensitivity_table_lists_only_real_sectors(session, workbook):
    from tests.test_api import PRICES
    from app.market.base import Quote
    from app.market.service import store_quote
    from app.models import Instrument
    from sqlalchemy import select

    import_workbook(session, workbook)
    for i in session.scalars(select(Instrument)):
        if i.symbol:
            store_quote(session, i.id, Quote(D(PRICES[i.symbol]), date(2026, 10, 16), "t", i.symbol))
        else:
            i.scheme_code = "1"
            store_quote(session, i.id, Quote(D("100"), date(2026, 10, 16), "t", "1"))
    session.flush()
    from app.services.classification import set_overrides
    set_overrides(session, session.scalar(select(Instrument).where(Instrument.symbol == "LT")).id, sector="Construction")
    set_overrides(session, session.scalar(select(Instrument).where(Instrument.symbol == "SBIN")).id, sector="Financial Services")
    page = mc.sensitivity_page(session)
    names = [r["sector"] for r in page["table"]]
    assert set(names) == {"Construction", "Financial Services"} and not any(n.startswith(("Not looked through", "Unclassified", "Debt, cash")) for n in names)


def _race(tmp_path, monkeypatch, fn, fresh: bool = True):
    """Run fn(session) in two threads that both finish reading before either writes."""
    import threading

    from app import db
    from app.models import SectorSensitivity

    if fresh:
        db.configure(f"sqlite:///{tmp_path / 'race.db'}")
        db.init_db()
    uid = make_user()  # the account exists before the workers race on the seed itself
    barrier = threading.Barrier(2, timeout=2)


    from sqlalchemy.orm import Session

    real_flush = Session.flush

    def gated_flush(self, *a, **kw):  # both workers have done their existence check before either writes
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        return real_flush(self, *a, **kw)

    monkeypatch.setattr(Session, "flush", gated_flush)
    errors: list[BaseException] = []

    def worker():
        try:
            with db.session_scope(user_id=uid) as s:
                fn(s)
        except BaseException as e:  # noqa: BLE001 - collected for the assertion
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(15)
    monkeypatch.undo()
    with db.session_scope(user_id=make_user()) as s:
        rows = list(s.scalars(__import__("sqlalchemy").select(SectorSensitivity)))
    return errors, rows


def test_concurrent_starter_seeding_is_idempotent(tmp_path, monkeypatch):
    errors, rows = _race(tmp_path, monkeypatch, lambda s: mc.ensure_starter(s, ["Construction", "Financial Services"]))
    assert errors == []
    assert sorted(r.sector for r in rows) == ["Construction", "Financial Services"]
    assert all(r.origin == "STARTER" for r in rows)


def test_starter_seeding_never_overwrites_user_tags_even_when_racing(tmp_path, monkeypatch):
    from app import db

    db.configure(f"sqlite:///{tmp_path / 'race2.db'}")
    db.init_db()
    with db.session_scope(user_id=make_user()) as s:
        mc.set_tags(s, "Construction", ["rate-sensitive"])
    errors, rows = _race(tmp_path, monkeypatch, lambda s: mc.ensure_starter(s, ["Construction"]), fresh=False)
    assert errors == [] and [(r.origin, r.tags) for r in rows] == [("USER", ["rate-sensitive"])]


def test_get_macro_concurrently_never_500s(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from fastapi.testclient import TestClient

    from app import db
    from app.main import app

    db.configure(f"sqlite:///{tmp_path / 'm.db'}")
    with TestClient(app) as c:
        with ThreadPoolExecutor(8) as ex:
            codes = list(ex.map(lambda _: c.get("/api/macro").status_code, range(16)))
    assert set(codes) == {200}
