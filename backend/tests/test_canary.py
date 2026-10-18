"""Canary: user B's unique values (a symbol nobody else holds, a company name, note text) must never appear in any
response user A gets from any GET route or the export, nor in any log line written during the test.

Global jobs run first (price refresh failing on B's canary security, live polling, fundamentals, news,
classification), so shared tables and logs have had every chance to pick the canaries up."""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app import db
from app.logging_config import KeyValueFormatter
from app.main import app
from tests import test_isolation as iso
from tests.conftest import base_txn_rows
from tests.test_routes import flat_routes

SYMBOL, NAME, NOTE = "ZQXCANRY", "Zebra Quixotic Canary Industries", "canary-note-7f3a"
CANARIES = (SYMBOL, NAME, NOTE)


def bob_rows():
    rows = [[r[0], r[1], r[2], f"{iso.MARK} {r[3]}", *r[4:12], f"{iso.MARK} note"] for r in base_txn_rows()]
    rows.append(["2026-10-03", "OPENING", "STOCK", NAME, SYMBOL, None, None, 3, 111, 333, 0, "Groww", NOTE])
    return rows


class CanaryFailingProvider:
    """Prices everything except Bob's canary security, whose failure message names it (as real errors do), so the
    canary is the first and only failure everywhere it could be reported."""

    name = "Yahoo Finance via yfinance"

    def supports(self, ref):
        return ref.asset_type in ("STOCK", "ETF")

    def fetch(self, refs):
        from datetime import date
        from decimal import Decimal as D

        from app.market.base import FetchError, Quote

        return {r.security_id: (FetchError(f"{r.symbol}.NS: HTTPError 404 for {r.name}") if r.symbol == SYMBOL
                                else Quote(D("100"), date(2026, 10, 16), "test", r.symbol, D("99")))
                for r in refs}


def _run_global_jobs():
    from app.jobs import snapshot_all
    from app.market import service
    from app.services import classification, fundamentals, live, news
    from app.timeutil import IST
    from datetime import datetime

    with db.session_scope(system=True) as s:
        service.refresh_prices(s, trigger="scheduled", providers=[CanaryFailingProvider()])
    snapshot_all()
    with db.session_scope(system=True) as s:
        live.poll_cycle(s, datetime(2026, 10, 19, 11, 0, tzinfo=IST), manual=True,
                        fetch=lambda syms: {x: (f"no intraday data for {x}" if x == SYMBOL else []) for x in syms})
    for fn in (fundamentals.refresh_fundamentals, news.refresh_news, classification.refresh_classification):
        with db.session_scope(system=True) as s:
            try:
                fn(s)
            except Exception:  # offline in tests; the point is what they write and log
                pass


def test_bobs_canaries_never_reach_alice_or_the_logs(tmp_path, monkeypatch, caplog):
    db.configure(f"sqlite:///{tmp_path / 'canary.db'}")
    iso._offline(monkeypatch)
    caplog.set_level(logging.DEBUG)
    with TestClient(app) as c:
        a_book = iso.write_workbook(tmp_path / "alice.xlsx")
        b_book = iso.write_workbook(tmp_path / "bob.xlsx", txn_rows=bob_rows())
        for who, book in ((iso.ALICE, a_book), (iso.BOB, b_book)):
            r = c.post("/api/import", headers={"X-Dev-User": who}, files={"file": ("w.xlsx", book.read_bytes())})
            assert r.status_code == 200 and r.json()["report"]["ok"], r.text
        ids = iso._bob_objects(c, tmp_path, b_book)
        bob = c.get("/api/transactions", headers={"X-Dev-User": iso.BOB}).text
        assert SYMBOL in bob and NAME in bob and NOTE in bob  # the canaries really are in Bob's data
        _run_global_jobs()

        A = {"X-Dev-User": iso.ALICE}
        leaks, gets = [], 0
        for path, route in flat_routes(app.routes):
            if "GET" not in route.methods or path == "/api/health":
                continue
            gets += 1
            r = c.get(iso._url(path, ids), headers=A, **{k: v for k, v in iso._body("GET", path, ids, a_book).items()
                                                          if k == "params"})
            body = iso._text(r)
            leaks += [f"GET {path}: {x!r}" for x in CANARIES if x in body]
        export = iso._text(c.get("/api/export.xlsx", headers=A))
        assert "Larsen" in export  # Alice's own export works
        leaks += [f"export: {x!r}" for x in CANARIES if x in export]

    fmt = KeyValueFormatter()
    lines = [fmt.format(r) for r in caplog.records]
    in_logs = sorted({f"{x!r} in a {r.name} line: {line[:160]}" for r, line in zip(caplog.records, lines)
                      for x in CANARIES if x in line})
    print(f"\ncanary: {gets} GET routes + export checked, {len(lines)} log lines scanned")
    assert gets >= 45
    assert leaks == [], leaks
    assert in_logs == [], in_logs


def test_fetch_errors_that_quote_the_ticker_are_scrubbed_from_logs(monkeypatch, caplog):
    """Real yfinance exceptions often contain the ticker; outbound() logs them without it."""
    import sys
    import types

    from app.market.base import InstrumentRef
    from app.market.yfinance_provider import YFinanceProvider

    class Ticker:
        def __init__(self, t):
            self.t = t

        def history(self, **kw):
            raise RuntimeError(f"{self.t}: possibly delisted; no price data found (symbol {self.t[:-3]})")

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=Ticker))
    caplog.set_level(logging.DEBUG)
    out = YFinanceProvider().fetch([InstrumentRef(41, "STOCK", SYMBOL, None, SYMBOL)])
    assert SYMBOL in out[41].message  # the user still sees the reason on their own holding
    lines = [KeyValueFormatter().format(r) for r in caplog.records]
    assert any("security_id=41" in x and "<security>" in x for x in lines)
    assert not any(SYMBOL in x for x in lines), lines
