from __future__ import annotations

from app.brokers.base import BrokerHolding


class FakeAdapter:
    """In-memory adapter for tests and demos."""

    name = "fake"

    def __init__(self, holdings: list[BrokerHolding]):
        self._holdings = list(holdings)

    def holdings(self) -> list[BrokerHolding]:
        return list(self._holdings)
