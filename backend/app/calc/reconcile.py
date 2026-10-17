"""Broker vs database reconciliation by ISIN (pure). Returns differences only."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.brokers.base import BrokerHolding

AVG_PRICE_TOLERANCE = Decimal("0.005")  # 0.5%


@dataclass(frozen=True)
class DbPosition:
    instrument_id: int
    isin: str
    name: str
    quantity: Decimal
    avg_cost: Decimal | None


def reconcile(db: list[DbPosition], broker: list[BrokerHolding], tol: Decimal = AVG_PRICE_TOLERANCE) -> list[dict]:
    dbm = {p.isin: p for p in db}
    bm: dict[str, BrokerHolding] = {}
    for h in broker:  # aggregate duplicate ISIN rows, if any
        prev = bm.get(h.isin)
        bm[h.isin] = h if prev is None else BrokerHolding(h.isin, h.symbol, prev.quantity + h.quantity, h.avg_price)
    rows = []
    for isin in sorted(set(dbm) | set(bm)):
        d, b = dbm.get(isin), bm.get(isin)
        if d is None:
            rows.append({"isin": isin, "name": b.symbol or isin, "kind": "MISSING_IN_DB",
                         "broker_quantity": str(b.quantity), "db_quantity": "0",
                         "broker_avg_price": str(b.avg_price) if b.avg_price is not None else None, "db_avg_cost": None,
                         "suggested": {"type": "BUY", "quantity": str(b.quantity),
                                       "price": str(b.avg_price) if b.avg_price is not None else None}})
            continue
        if b is None:
            rows.append({"isin": isin, "name": d.name, "instrument_id": d.instrument_id, "kind": "MISSING_AT_BROKER",
                         "broker_quantity": "0", "db_quantity": str(d.quantity), "broker_avg_price": None,
                         "db_avg_cost": str(d.avg_cost) if d.avg_cost is not None else None,
                         "suggested": {"type": "SELL", "quantity": str(d.quantity), "price": None}})
            continue
        diffs = []
        if d.quantity != b.quantity:
            diffs.append("QUANTITY")
        if d.avg_cost is not None and b.avg_price is not None and d.avg_cost > 0 and \
                abs(b.avg_price - d.avg_cost) / d.avg_cost > tol:
            diffs.append("AVG_PRICE")
        if diffs:
            delta = b.quantity - d.quantity
            rows.append({"isin": isin, "name": d.name, "instrument_id": d.instrument_id, "kind": "+".join(diffs),
                         "broker_quantity": str(b.quantity), "db_quantity": str(d.quantity),
                         "broker_avg_price": str(b.avg_price) if b.avg_price is not None else None,
                         "db_avg_cost": str(d.avg_cost.quantize(Decimal("0.01"))) if d.avg_cost is not None else None,
                         "suggested": ({"type": "BUY" if delta > 0 else "SELL", "quantity": str(abs(delta)),
                                        "price": str(b.avg_price) if (delta > 0 and b.avg_price is not None) else None}
                                       if delta else None)})
    return rows
