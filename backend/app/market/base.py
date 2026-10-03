"""PriceProvider interface. Every quote carries its source and as-of date."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class InstrumentRef:
    instrument_id: int
    asset_type: str
    symbol: str | None
    scheme_code: str | None
    name: str


@dataclass(frozen=True)
class Quote:
    price: Decimal
    price_date: date
    source: str
    source_ref: str
    previous_close: Decimal | None = None
    previous_date: date | None = None
    currency: str = "INR"
    fetched_at: datetime | None = None


@dataclass(frozen=True)
class FetchError:
    message: str


class PriceProvider(Protocol):
    name: str

    def supports(self, ref: InstrumentRef) -> bool: ...

    def fetch(self, refs: list[InstrumentRef]) -> dict[int, Quote | FetchError]: ...
