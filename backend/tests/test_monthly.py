from datetime import UTC, date, datetime, timedelta

from app.calc.monthly import checklist, month_bounds

TODAY = date(2026, 10, 17)
NOW = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)
FUNDS = [{"instrument_id": 1, "name": "HDFC Mid Cap", "monthly_amount_paise": 150000},
         {"instrument_id": 2, "name": "ICICI Nifty 50", "monthly_amount_paise": 150000}]


def test_month_bounds():
    assert month_bounds(date(2026, 2, 10)) == (date(2026, 2, 1), date(2026, 2, 28))
    assert month_bounds(date(2026, 12, 31)) == (date(2026, 12, 1), date(2026, 12, 31))


def test_missing_sip_warns_and_ticks_follow_data():
    txns = [{"instrument_id": 1, "asset_type": "MF", "type": "SIP", "date": date(2026, 10, 5)}]
    out = checklist(TODAY, NOW, FUNDS, txns, None, None, False)
    items = {i["key"]: i for i in out["items"]}
    assert not items["sip_rows"]["done"] and "ICICI Nifty 50" in items["sip_rows"]["detail"]
    assert out["warnings"] == ["ICICI Nifty 50: no SIP row dated October 2026 yet."]
    assert out["done"] == 0


def test_everything_done():
    txns = [{"instrument_id": 1, "asset_type": "MF", "type": "SIP", "date": date(2026, 10, 5)},
            {"instrument_id": 2, "asset_type": "MF", "type": "SIP", "date": date(2026, 10, 5)},
            {"instrument_id": 9, "asset_type": "STOCK", "type": "BUY", "date": date(2026, 10, 7)}]
    out = checklist(TODAY, NOW, FUNDS, txns, {"ok": True, "date": date(2026, 10, 16)}, NOW - timedelta(hours=2), True)
    assert out["done"] == out["total"] == 5 and out["warnings"] == []


def test_stale_import_and_prices():
    out = checklist(TODAY, NOW, FUNDS, [], {"ok": True, "date": date(2026, 9, 30)}, NOW - timedelta(hours=30), False)
    items = {i["key"]: i["done"] for i in out["items"]}
    assert items == {"sip_rows": False, "stock_buys": False, "import": False, "prices": False, "snapshot": False}


def test_service_with_db(session, workbook):
    from app.importer.run import import_workbook
    from app.services.monthly import monthly_update

    import_workbook(session, workbook)
    out = monthly_update(session)
    assert len(out["plan"]) == 3 and len(out["warnings"]) in (0, 3)  # OPENING rows are not SIPs
