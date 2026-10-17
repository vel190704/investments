from datetime import date
from decimal import Decimal as D

import pytest

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
    row = session.get(__import__("app.models", fromlist=["SectorSensitivity"]).SectorSensitivity, "Construction")
    assert row.origin == "STARTER" and "review and edit" in row.note
    mc.set_tags(session, "Construction", ["rate-sensitive"])
    mc.ensure_starter(session, ["Construction"])
    assert row.origin == "USER" and row.tags == ["rate-sensitive"]
    with pytest.raises(mc.MacroError):
        mc.set_tags(session, "Construction", ["bullish"])
