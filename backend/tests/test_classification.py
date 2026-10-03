from datetime import date, datetime
from decimal import Decimal as D

import pytest
from sqlalchemy import select

from app.calc.allocation import classify, region_for_global_index
from app.calc.drift import fold_classes, untargeted
from app.importer.run import import_workbook
from app.models import Instrument, SectorAssignment
from app.resolve.sources import NseIndustry, NseSecurity
from app.services import classification as cl
from tests.conftest import write_workbook


def test_classify_etfs_by_what_they_hold():
    assert classify("ETF", "DOMESTIC", None, "COMMODITY", "GOLD") == "Gold"
    assert classify("ETF", "DOMESTIC", None, "COMMODITY", "SILVER") == "Other commodities"
    assert classify("ETF", "DOMESTIC", None, "DEBT", "Overnight ETFs and Liquid ETF") == "Debt/Cash"
    assert classify("ETF", "DOMESTIC", None, "GLOBAL INDICES", "GLOBAL INDICES") == "International ETFs"
    assert classify("ETF", "DOMESTIC", None, "EQUITY", "Nifty 50") == "Indian ETFs"
    assert classify("ETF", "INTERNATIONAL") == "International ETFs"  # Phase 1 data still classifies the same
    assert classify("STOCK", "DOMESTIC", "Debt/Cash") == "Debt/Cash"  # manual override wins


def test_regions_from_nse_index_names():
    assert region_for_global_index("Hang Seng Index") == "Hong Kong/China"
    assert region_for_global_index("NYSE FANG+ Total Return Index") == "US (technology-heavy)"
    assert region_for_global_index("Something Else") == "International (region not classified)"


def test_drift_folding_with_new_classes():
    v = {"Indian ETFs": 100, "Indian stocks": 50, "Gold": 30, "Other commodities": 20}
    t = ["Mutual funds", "Indian stocks", "International ETFs", "Gold", "Debt/Cash"]
    assert fold_classes(v, t)["Indian stocks"] == 150 and fold_classes(v, t)["Gold"] == 30
    assert untargeted(v, t) == {"Other commodities": 20}


def A(origin, sector):
    return SectorAssignment(instrument_id=1, origin=origin, sector=sector, source=origin, as_of=date(2026, 10, 3))


def test_effective_sector_priority():
    assert cl.effective_sector([A("NSE", "Construction")]).sector == "Construction"
    e = cl.effective_sector([A("NSE", "Construction"), A("EXCEL", "Infra"), A("MANUAL", "Capital Goods")])
    assert (e.sector, e.origin, e.manual) == ("Capital Goods", "MANUAL", True)
    assert cl.effective_sector([A("NSE", "Construction"), A("EXCEL", "Infra")]).origin == "EXCEL"
    assert cl.effective_sector([]).sector == "Unclassified"


def fake_sources(monkeypatch):
    import app.resolve.sources as src

    ind = {"INE018A01030": NseIndustry("LT", "INE018A01030", "Larsen & Toubro Ltd.", "Construction", "Nifty Total Market")}
    by_sym = {"LT": ind["INE018A01030"], "SBIN": NseIndustry("SBIN", "INE062A01020", "SBI", "Financial Services",
                                                             "Nifty Total Market")}
    monkeypatch.setattr(src, "nse_industries", lambda: (ind, by_sym, datetime(2026, 10, 3)))
    etfs = {"MAFANG": NseSecurity("MAFANG", "x", "INF769K01HF4", "ETF", "GLOBAL INDICES", "GLOBAL INDICES",
                                  "NYSE FANG+ Total Return Index"),
            "HNGSNGBEES": NseSecurity("HNGSNGBEES", "x", "INF204KB19I1", "ETF", "GLOBAL INDICES", "GLOBAL INDICES",
                                      "Hang Seng Index")}
    monkeypatch.setattr(src, "nse_securities", lambda: (etfs, datetime(2026, 10, 3)))
    monkeypatch.setattr(src, "amfi_schemes", lambda **k: ({}, datetime(2026, 10, 3)))


def test_refresh_assigns_nse_sectors_and_etf_regions(session, workbook, monkeypatch):
    import_workbook(session, workbook)
    fake_sources(monkeypatch)
    lt = session.scalar(select(Instrument).where(Instrument.symbol == "LT"))
    lt.isin = "INE018A01030"
    rep = cl.refresh_classification(session)
    secs = cl.sectors_by_instrument(session)
    assert secs[lt.id].sector == "Construction" and secs[lt.id].origin == "NSE"
    assert "MOSCHIP" in rep["stocks_unclassified"]
    mos = session.scalar(select(Instrument).where(Instrument.symbol == "MOSCHIP"))
    assert secs[mos.id].sector == "Unclassified"
    hk = session.scalar(select(Instrument).where(Instrument.symbol == "HNGSNGBEES"))
    assert hk.region == "Hong Kong/China" and secs[hk.id].sector == "International equity — Hong Kong/China"
    a = session.scalar(select(SectorAssignment).where(SectorAssignment.instrument_id == lt.id))
    assert a.note == "matched by ISIN" and a.as_of == date(2026, 10, 3)


def test_manual_override_wins_and_can_be_cleared(session, workbook, monkeypatch):
    import_workbook(session, workbook)
    fake_sources(monkeypatch)
    cl.refresh_classification(session)
    mos = session.scalar(select(Instrument).where(Instrument.symbol == "MOSCHIP"))
    cl.set_overrides(session, mos.id, sector="Information Technology", note="semiconductor design")
    e = cl.sectors_by_instrument(session)[mos.id]
    assert (e.sector, e.manual, e.source) == ("Information Technology", True, "manual (entered in the app)")
    cl.clear_override(session, mos.id, "sector")
    assert cl.sectors_by_instrument(session)[mos.id].sector == "Unclassified"
    with pytest.raises(cl.ClassificationError):
        cl.set_overrides(session, mos.id, asset_class="Crypto")
    cl.set_overrides(session, mos.id, asset_class="Gold")
    assert mos.asset_class_override == "Gold"


def test_excel_fallback_sector_is_an_override(session, tmp_path, monkeypatch):
    fb = [["2026-10-03", "Groww", "STOCK", "Larsen & Toubro", "LT", 1, 3768, None, "Infrastructure", None]]
    import_workbook(session, write_workbook(tmp_path / "b.xlsx", fallback_rows=fb))
    fake_sources(monkeypatch)
    cl.refresh_classification(session)
    lt = session.scalar(select(Instrument).where(Instrument.symbol == "LT"))
    e = cl.sectors_by_instrument(session)[lt.id]
    assert (e.sector, e.origin, e.manual) == ("Infrastructure", "EXCEL", True)
    # removing the sector from the workbook removes the Excel override on the next import
    fb[0][8] = None
    import_workbook(session, write_workbook(tmp_path / "c.xlsx", fallback_rows=fb))
    assert cl.sectors_by_instrument(session)[lt.id].origin == "NSE"


def test_gold_override_changes_portfolio_class(session, workbook):
    from app.services.portfolio import load_rows

    import_workbook(session, workbook)
    itc = session.scalar(select(Instrument).where(Instrument.symbol == "ITC"))
    cl.set_overrides(session, itc.id, asset_class="Gold")
    rows, _ = load_rows(session)
    assert next(r for r in rows if r.inst.id == itc.id).asset_class == "Gold"
