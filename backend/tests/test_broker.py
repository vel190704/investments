import inspect
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import httpx
import pytest
from sqlalchemy import func, select

from app.brokers.base import BrokerError, BrokerHolding
from app.brokers.fake import FakeAdapter
from app.brokers.groww import ALLOWED, GrowwAdapter
from app.brokers.kite import KiteMFAdapter
from app.brokers.totp import totp
from app.calc.reconcile import DbPosition, reconcile
from app.importer.run import import_workbook
from app.models import Instrument, Transaction
from app.services import broker as svc

ORDER_WORDS = ("order", "modify", "cancel", "place", "trade", "buy", "sell", "gtt", "exit")


@pytest.mark.parametrize("cls", [GrowwAdapter, FakeAdapter, KiteMFAdapter])
def test_adapters_expose_no_order_methods(cls):
    names = [n.lower() for n, _ in inspect.getmembers(cls) if not n.startswith("__")]
    assert not [n for n in names if any(w in n for w in ORDER_WORDS)], names


def test_rfc6238_vectors():
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # ASCII "12345678901234567890"
    assert totp(secret, 59, digits=8) == "94287082"
    assert totp(secret, 1111111109, digits=8) == "07081804"
    assert totp(secret, 2000000000, digits=8) == "69279037"


def groww_transport(log, expiry):
    def handler(req: httpx.Request):
        log.append((req.method, req.url.path, dict(req.headers)))
        if (req.method, req.url.path) == ("POST", "/v1/token/api/access"):
            return httpx.Response(200, json={"token": "tok-123", "expiry": expiry, "isActive": True})
        if (req.method, req.url.path) == ("GET", "/v1/holdings/user"):
            return httpx.Response(200, json={"status": "SUCCESS", "payload": {"holdings": [
                {"isin": "INE018A01030", "trading_symbol": "LT", "quantity": 2, "average_price": 3730.7},
                {"isin": "INE009A01021", "trading_symbol": "INFY", "quantity": 3, "average_price": 1500}]}})
        return httpx.Response(500)
    return httpx.MockTransport(handler)


def test_groww_only_calls_allowed_read_only_endpoints():
    log = []
    exp = (datetime.now(timezone.utc) + timedelta(hours=10)).isoformat()
    g = GrowwAdapter("api-key", "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", transport=groww_transport(log, exp))
    hs = g.holdings()
    assert [(m, p) for m, p, _ in log] == [("POST", "/v1/token/api/access"), ("GET", "/v1/holdings/user")]
    assert log[1][2]["authorization"] == "Bearer tok-123" and log[1][2]["x-api-version"] == "1.0"
    assert hs[0] == BrokerHolding("INE018A01030", "LT", D("2"), D("3730.7"))
    g.holdings()  # token reused until expiry
    assert [p for _, p, _ in log].count("/v1/token/api/access") == 1
    assert all("order" not in p for _, p, _ in log)
    for method, path in [("POST", "/v1/order/create"), ("PUT", "/v1/order/modify"), ("POST", "/v1/order/cancel")]:
        with pytest.raises(BrokerError, match="not an allowed read-only endpoint"):
            g._request(method, path)
    assert len(log) == 3 and ALLOWED == {("POST", "/v1/token/api/access"), ("GET", "/v1/holdings/user")}
    assert "api-key" not in repr(g) and "tok-123" not in repr(g)


def test_groww_needs_totp_or_code():
    g = GrowwAdapter("k", None, transport=groww_transport([], "2099-01-01T00:00:00+00:00"))
    with pytest.raises(BrokerError, match="TOTP"):
        g.holdings()
    assert g.login("123456") is not None and g.token_valid


def test_reconcile_differences_only():
    db = [DbPosition(1, "INE018A01030", "LT", D(1), D("3768")), DbPosition(2, "INE154A01025", "ITC", D(1), D("266.40")),
          DbPosition(3, "INE062A01020", "SBIN", D(1), D("963.95"))]
    broker = [BrokerHolding("INE018A01030", "LT", D(2), D("3730.7")), BrokerHolding("INE154A01025", "ITC", D(1), D("266.5")),
              BrokerHolding("INE009A01021", "INFY", D(3), D(1500))]
    rows = {r["isin"]: r for r in reconcile(db, broker)}
    assert set(rows) == {"INE018A01030", "INE062A01020", "INE009A01021"}  # ITC matches within 0.5%: not listed
    assert rows["INE018A01030"]["kind"] == "QUANTITY+AVG_PRICE" and rows["INE018A01030"]["suggested"] == {
        "type": "BUY", "quantity": "1", "price": "3730.7"}
    assert rows["INE062A01020"]["kind"] == "MISSING_AT_BROKER"
    assert rows["INE009A01021"]["kind"] == "MISSING_IN_DB"
    price_only = reconcile([DbPosition(1, "X", "X", D(1), D(100))], [BrokerHolding("X", "X", D(1), D(102))])
    assert price_only[0]["kind"] == "AVG_PRICE" and price_only[0]["suggested"] is None


def test_reconciliation_never_writes(session, workbook):
    import_workbook(session, workbook)
    session.scalar(select(Instrument).where(Instrument.symbol == "LT")).isin = "INE018A01030"
    before = session.scalar(select(func.count()).select_from(Transaction))
    out = svc.reconcile_with(session, FakeAdapter([BrokerHolding("INE018A01030", "LT", D(5), D(3700))]))
    assert out["ok"] and out["differences"][0]["kind"].startswith("QUANTITY")
    assert len(out["not_compared"]) == 15  # stocks/ETFs without a confirmed ISIN are listed, not guessed
    assert session.scalar(select(func.count()).select_from(Transaction)) == before


def test_flag_off_means_no_adapter(monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(get_settings(), "groww_enabled", False)
    with pytest.raises(BrokerError, match="GROWW_ENABLED"):
        svc.groww_adapter()
    assert svc.status()["groww_enabled"] is False
