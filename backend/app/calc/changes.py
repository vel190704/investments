"""Pure diff functions for the change log and the snapshot compare view."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.money import format_inr, format_pct

AVG_COST_EPS = Decimal("0.0001")  # rupees per unit
ALLOCATION_MIN_PP = Decimal("0.1")  # ignore allocation moves smaller than 0.1 percentage points


@dataclass(frozen=True)
class PosState:
    name: str
    quantity: Decimal
    avg_cost: Decimal | None  # rupees per unit


def _q(d: Decimal) -> str:
    return format(d.normalize(), "f") if d == d.to_integral_value() or d.as_tuple().exponent >= -6 else f"{d:.6f}"


def diff_positions(before: dict[int, PosState], after: dict[int, PosState]) -> list[dict]:
    """QTY_CHANGED / AVG_COST_CHANGED entries for every instrument whose position moved."""
    out = []
    for iid in sorted(set(before) | set(after)):
        b, a = before.get(iid), after.get(iid)
        name = (a or b).name
        bq = b.quantity if b else Decimal(0)
        aq = a.quantity if a else Decimal(0)
        if bq != aq:
            out.append({"kind": "QTY_CHANGED", "instrument_id": iid,
                        "summary": f"{name}: quantity {_q(bq)} → {_q(aq)}",
                        "details": {"before": str(bq), "after": str(aq)}})
        bc = b.avg_cost if b and b.quantity > 0 else None
        ac = a.avg_cost if a and a.quantity > 0 else None
        if bc is not None and ac is not None and abs(bc - ac) > AVG_COST_EPS:
            out.append({"kind": "AVG_COST_CHANGED", "instrument_id": iid,
                        "summary": f"{name}: average cost ₹{bc:.2f} → ₹{ac:.2f}",
                        "details": {"before": str(bc), "after": str(ac)}})
    return out


def diff_allocation(before: dict[str, Decimal], after: dict[str, Decimal],
                    min_pp: Decimal = ALLOCATION_MIN_PP) -> list[dict]:
    """ALLOCATION_CHANGED entries for asset classes whose weight moved by >= min_pp."""
    out = []
    for cls in sorted(set(before) | set(after)):
        b, a = before.get(cls, Decimal(0)), after.get(cls, Decimal(0))
        if abs(a - b) * 100 >= min_pp:
            out.append({"kind": "ALLOCATION_CHANGED", "instrument_id": None,
                        "summary": f"{cls}: {format_pct(b)} → {format_pct(a)} of portfolio",
                        "details": {"asset_class": cls, "before": str(b), "after": str(a)}})
    return out


@dataclass(frozen=True)
class HoldingView:
    instrument_id: int
    name: str
    asset_class: str
    quantity: Decimal
    avg_cost: Decimal | None
    invested_paise: int
    value_paise: int | None


def compare(a: list[HoldingView], b: list[HoldingView]) -> dict:
    """Instrument-level and asset-class-level differences between two portfolio states."""
    am = {h.instrument_id: h for h in a}
    bm = {h.instrument_id: h for h in b}
    ta = sum(h.value_paise or 0 for h in a)
    tb = sum(h.value_paise or 0 for h in b)

    def w(h: HoldingView | None, total: int) -> Decimal | None:
        if h is None:
            return Decimal(0)
        if h.value_paise is None or not total:
            return None
        return Decimal(h.value_paise) / total

    rows = []
    for iid in sorted(set(am) | set(bm), key=lambda i: (bm.get(i) or am.get(i)).name):
        ha, hb = am.get(iid), bm.get(iid)
        ref = hb or ha
        status = "added" if ha is None else "removed" if hb is None else (
            "changed" if (ha.quantity != hb.quantity or ha.avg_cost != hb.avg_cost) else "unchanged")
        wa, wb = w(ha, ta), w(hb, tb)
        rows.append({
            "instrument_id": iid, "name": ref.name, "asset_class": ref.asset_class, "status": status,
            "quantity_a": str(ha.quantity) if ha else "0", "quantity_b": str(hb.quantity) if hb else "0",
            "avg_cost_a": str(ha.avg_cost) if ha and ha.avg_cost is not None else None,
            "avg_cost_b": str(hb.avg_cost) if hb and hb.avg_cost is not None else None,
            "value_a_paise": ha.value_paise if ha else 0, "value_b_paise": hb.value_paise if hb else 0,
            "weight_a": str(wa) if wa is not None else None, "weight_b": str(wb) if wb is not None else None,
            "value_change_paise": ((hb.value_paise if hb else 0) - (ha.value_paise if ha else 0))
            if (hb is None or hb.value_paise is not None) and (ha is None or ha.value_paise is not None) else None,
        })

    classes: dict[str, dict] = {}
    for side, hs, total in (("a", a, ta), ("b", b, tb)):
        for h in hs:
            c = classes.setdefault(h.asset_class, {"asset_class": h.asset_class, "value_a_paise": 0, "value_b_paise": 0})
            c[f"value_{side}_paise"] += h.value_paise or 0
    for c in classes.values():
        c["weight_a"] = str(Decimal(c["value_a_paise"]) / ta) if ta else None
        c["weight_b"] = str(Decimal(c["value_b_paise"]) / tb) if tb else None
        c["value_change_paise"] = c["value_b_paise"] - c["value_a_paise"]
    return {
        "total_a_paise": ta, "total_b_paise": tb, "total_change_paise": tb - ta,
        "total_change_text": format_inr(tb - ta),
        "instruments": rows,
        "asset_classes": sorted(classes.values(), key=lambda c: c["asset_class"]),
    }
