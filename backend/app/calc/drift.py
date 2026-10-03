"""Allocation drift: current % vs target % per asset class, with a tolerance band.

Status: OVERWEIGHT if deviation > +tolerance, UNDERWEIGHT if deviation < -tolerance, else WITHIN BAND
(a deviation exactly at the band edge counts as within). Deviation is in percentage points.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.money import format_inr, format_pct, round_paise


def _pp(d: Decimal) -> str:
    v = d.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{'+' if v > 0 else ''}{v} pp"


def fold_classes(values: dict[str, int], target_classes: list[str]) -> dict[str, int]:
    """Map held asset classes onto target classes ('Indian ETFs' are counted with Indian stocks)."""
    out = {c: 0 for c in target_classes}
    for cls, v in values.items():
        key = "Indian stocks" if cls == "Indian ETFs" else cls
        out[key] = out.get(key, 0) + v
    return out


def status_for(deviation_pp: Decimal, tolerance_pp: Decimal) -> str:
    if deviation_pp > tolerance_pp:
        return "OVERWEIGHT"
    if deviation_pp < -tolerance_pp:
        return "UNDERWEIGHT"
    return "WITHIN BAND"


def drift(values: dict[str, int], total_paise: int, targets: dict[str, Decimal], tolerance_pp: Decimal) -> list[dict]:
    """values: paise per target class; targets: fractions summing to 1."""
    rows = []
    t = Decimal(total_paise)
    for cls, target in targets.items():
        v = values.get(cls, 0)
        cur = Decimal(v) / t if total_paise else Decimal(0)
        dev = (cur - target) * 100
        st = status_for(dev, tolerance_pp)
        gap = v - round_paise(target * t)
        if st == "WITHIN BAND":
            reason = (f"{cls} is {format_pct(cur)} vs target {format_pct(target)} "
                      f"({_pp(dev)}), inside the ±{tolerance_pp} pp band.")
        else:
            side = "above" if dev > 0 else "below"
            reason = (f"{cls} is {format_pct(cur)} vs target {format_pct(target)}: "
                      f"{_pp(abs(dev)).lstrip('+')} {side}, outside the ±{tolerance_pp} pp band.")
        rule = {"OVERWEIGHT": f"OVERWEIGHT because > +{tolerance_pp} pp",
                "UNDERWEIGHT": f"UNDERWEIGHT because < −{tolerance_pp} pp",
                "WITHIN BAND": f"WITHIN BAND because within ±{tolerance_pp} pp"}[st]
        rows.append({
            "asset_class": cls, "value_paise": v, "current": str(cur), "target": str(target),
            "deviation_pp": str(dev), "value_vs_target_paise": gap, "status": st, "held": v > 0,
            "reason": reason,
            "calculation": f"{format_inr(v)} / {format_inr(total_paise)} = {format_pct(cur)}; "
                           f"{format_pct(cur)} − {format_pct(target)} = {_pp(dev)}; {rule}.",
        })
    return rows
