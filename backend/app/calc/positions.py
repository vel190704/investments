"""Position replay using the average-cost method.

OPENING rows count toward quantity and invested amount but are tracked separately
(`opening_quantity`) so XIRR can exclude them together with the units they contributed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

TYPE_ORDER = {"OPENING": 0, "BUY": 1, "SIP": 1, "SELL": 2, "DIVIDEND": 3}
ACQUIRE_TYPES = {"OPENING", "BUY", "SIP"}
DATED_BUY_TYPES = {"BUY", "SIP"}
ZERO = Decimal(0)


@dataclass(frozen=True)
class TxnInput:
    date: date
    type: str
    quantity: Decimal | None
    amount_paise: int
    charges_paise: int = 0
    seq: int = 0  # stable tie-breaker (file row order)


class OversellError(ValueError):
    def __init__(self, txn: TxnInput, held: Decimal):
        super().__init__(f"SELL of {txn.quantity} on {txn.date} exceeds held quantity {held}")
        self.txn = txn
        self.held = held


@dataclass
class Position:
    quantity: Decimal = ZERO
    cost_paise: Decimal = ZERO  # cost basis of units still held (kept unrounded internally)
    realised_paise: Decimal = ZERO
    dividends_paise: int = 0
    opening_quantity: Decimal = ZERO
    dated_quantity: Decimal = ZERO
    has_dated_buys: bool = False
    last_dated_share: Decimal = ZERO  # dated units / all units, kept for dividends paid after a full sale
    # XIRR flows for the dated (non-OPENING) portion only; terminal value added later.
    xirr_flows: list[tuple[date, Decimal]] = field(default_factory=list)

    @property
    def invested_paise(self) -> int:
        from app.money import round_paise

        return round_paise(self.cost_paise)

    @property
    def avg_cost(self) -> Decimal | None:
        """Average cost per unit in rupees."""
        if self.quantity <= 0:
            return None
        return self.cost_paise / self.quantity / 100

    @property
    def is_open(self) -> bool:
        return self.quantity > 0


def sort_key(t: TxnInput):
    return (t.date, TYPE_ORDER.get(t.type, 9), t.seq)


def replay(txns: list[TxnInput]) -> Position:
    pos = Position()
    for t in sorted(txns, key=sort_key):
        if t.type in ACQUIRE_TYPES:
            q = t.quantity or ZERO
            pos.quantity += q
            pos.cost_paise += Decimal(t.amount_paise + t.charges_paise)
            if t.type == "OPENING":
                pos.opening_quantity += q
            else:
                pos.dated_quantity += q
                pos.has_dated_buys = True
                pos.xirr_flows.append((t.date, -Decimal(t.amount_paise + t.charges_paise)))
        elif t.type == "SELL":
            q = t.quantity or ZERO
            if q > pos.quantity:
                raise OversellError(t, pos.quantity)
            avg = pos.cost_paise / pos.quantity
            cost_removed = avg * q
            proceeds = Decimal(t.amount_paise - t.charges_paise)
            pos.realised_paise += proceeds - cost_removed
            dated_share = pos.dated_quantity / pos.quantity
            pos.dated_quantity -= q * dated_share
            pos.opening_quantity -= q * (1 - dated_share)
            pos.last_dated_share = dated_share
            pos.quantity -= q
            pos.cost_paise -= cost_removed
            if pos.quantity == 0:
                pos.cost_paise = ZERO
            if dated_share > 0:
                pos.xirr_flows.append((t.date, proceeds * dated_share))
        elif t.type == "DIVIDEND":
            pos.dividends_paise += t.amount_paise
            if pos.has_dated_buys:
                # a dividend can be paid after the units were sold (record date before the sale)
                dated_share = pos.dated_quantity / pos.quantity if pos.quantity > 0 else pos.last_dated_share
                if dated_share > 0:
                    pos.xirr_flows.append((t.date, Decimal(t.amount_paise) * dated_share))
        else:
            raise ValueError(f"Unknown transaction type {t.type!r}")
    return pos
