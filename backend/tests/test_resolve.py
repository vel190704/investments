from datetime import date
from decimal import Decimal as D

from sqlalchemy import select

from app.importer.run import import_workbook
from app.models import IdentifierCandidate, Instrument
from app.resolve import service
from app.resolve.matching import scheme_matches
from app.resolve.sources import NseSecurity, parse_amfi, parse_nse_etf

AMFI = """Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Plan;Option;Net Asset Value;Date

Open Ended Schemes(Index Funds)

ICICI Prudential Mutual Fund
101349;INF109K01PI0;-;ICICI Prudential Nifty 50 Index Fund;Regular Plan;Cumulative;227.2683;01-Oct-2026
120620;INF109K012M7;-;ICICI Prudential Nifty 50 Index Fund;Direct Plan;Cumulative;237.3337;01-Oct-2026
135391;INF109KB1NL1;INF109KB1NM9;ICICI Prudential Nifty 50 Index Fund;Direct Plan;IDCW;31.9161;01-Oct-2026
120684;INF109K01Z14;-;ICICI Prudential Nifty Next 50 Index Fund;Direct Plan;Growth;60.1;01-Oct-2026
HDFC Mutual Fund
118989;INF179K01XQ0;-;HDFC Mid Cap Fund;Direct Plan;Growth Option;219.441;01-Oct-2026
105758;INF179K01CR2;-;HDFC Mid Cap Fund;Regular Plan;Growth Option;197.82;01-Oct-2026
Kotak Mahindra Mutual Fund
148745;INF174KA1GA9;-;Kotak Nifty Next 50 Index Fund;Direct Plan;Growth;20.2442;01-Oct-2026
148978;INF174KA1HS9;-;Kotak Nifty 50 Index Fund;Direct Plan;Growth;15.1;01-Oct-2026
"""

LEGACY = """Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
118989;INF179K01XQ0;-;HDFC Mid-Cap Opportunities Fund - Growth Option - Direct Plan;219.441;01-Oct-2026
"""


def test_parse_amfi_8_column():
    s = parse_amfi(AMFI)
    assert s["120620"].nav == D("237.3337") and s["120620"].nav_date == date(2026, 10, 1)
    assert s["120620"].isin_growth == "INF109K012M7" and s["135391"].isin_reinvest == "INF109KB1NM9"
    assert s["118989"].fund_house == "HDFC Mutual Fund"


def test_parse_amfi_legacy_6_column():
    s = parse_amfi(LEGACY)
    assert s["118989"].nav == D("219.441")


def test_matching_respects_plan_and_growth_equals_cumulative():
    s = parse_amfi(AMFI)
    m = scheme_matches("ICICI Prudential Nifty 50 Index Fund - Direct - Growth", s)
    assert m[0][0].scheme_code == "120620"  # Direct + Cumulative
    codes = [x[0].scheme_code for x in m]
    assert "101349" not in codes and "135391" not in codes  # regular / IDCW filtered out
    assert scheme_matches("Kotak Nifty Next 50 Index Fund - Direct - Growth", s)[0][0].scheme_code == "148745"
    assert scheme_matches("HDFC Mid Cap Fund - Direct - Growth", s)[0][0].scheme_code == "118989"


def test_parse_nse_etf():
    text = ("Symbol,Underlying Asset,SecurityName,DateofListing,MarketLot,ISINNumber,FaceValue,ETF Underlying,Underlying Key\n"
            "MAFANG,NYSE FANG+ Total Return Index,MIRAEAMC-MAFANG,14-May-21,1,INF769K01HF4,40,GLOBAL INDICES,GLOBAL INDICES\n")
    assert parse_nse_etf(text)["MAFANG"].isin == "INF769K01HF4"


def test_resolution_creates_pending_and_confirm_applies(session, workbook, monkeypatch):
    import_workbook(session, workbook)
    nse = {"LT": NseSecurity("LT", "Larsen & Toubro Limited", "INE018A01030", "EQUITY")}
    monkeypatch.setattr(service, "nse_securities", lambda: (nse, __import__("datetime").datetime.now()))
    monkeypatch.setattr(service, "amfi_schemes", lambda: (parse_amfi(AMFI), __import__("datetime").datetime.now()))
    res = service.resolve_identifiers(session)
    assert res["created"] > 0 and any("not found in NSE" in e for e in res["errors"])
    lt = session.scalar(select(Instrument).where(Instrument.symbol == "LT"))
    assert lt.isin is None  # never applied silently
    c = session.scalar(select(IdentifierCandidate).where(IdentifierCandidate.instrument_id == lt.id))
    assert c.status == "PENDING"
    service.decide(session, c.id, True)
    assert lt.isin == "INE018A01030"

    icici = session.scalar(select(Instrument).where(Instrument.name.like("ICICI%")))
    cands = session.scalars(select(IdentifierCandidate).where(IdentifierCandidate.instrument_id == icici.id)
                            .order_by(IdentifierCandidate.score.desc())).all()
    service.decide(session, cands[0].id, True)
    assert icici.scheme_code == "120620" and icici.isin == "INF109K012M7"
    assert all(c.status == "REJECTED" for c in cands[1:])
    # re-running resolution does not create candidates for confirmed instruments
    again = service.resolve_identifiers(session)
    assert icici.scheme_code == "120620" and again["created"] == 0
