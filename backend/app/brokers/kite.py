"""Kite Connect (Zerodha Coin mutual funds) — NOT IMPLEMENTED (documented stub).

A future read-only adapter would use Kite Connect's mutual-fund holdings endpoint with a daily
request-token login, return BrokerHolding rows keyed by ISIN, and expose no order methods.
"""

from __future__ import annotations

from app.brokers.base import BrokerHolding


class KiteMFAdapter:
    name = "kite-mf"

    def holdings(self) -> list[BrokerHolding]:
        raise NotImplementedError("The Kite MF adapter is not built (see app/brokers/kite.py)")
