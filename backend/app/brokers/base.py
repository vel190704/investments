"""Read-only broker adapters. Normalised holdings keyed by ISIN. No order methods exist, by design."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


class BrokerError(Exception):
    """Broker not configured / unreachable / rejected. Message is safe to show (never contains secrets)."""


@dataclass(frozen=True)
class BrokerHolding:
    isin: str
    symbol: str | None
    quantity: Decimal
    avg_price: Decimal | None  # rupees per unit


class BrokerAdapter(Protocol):
    name: str

    def holdings(self) -> list[BrokerHolding]: ...
