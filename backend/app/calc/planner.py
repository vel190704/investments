"""Monthly contribution planner (pure). Describes how a budget would be distributed and what the
resulting allocation would be. It never executes or suggests orders; flags are worded as
"Allocation consideration".

Mode "plan": the budget is split by monthly_plan fractions. The "Direct stocks & ETFs" bucket has no
instrument split in the plan: it goes equally to stocks/ETFs the user picks (whole units only), or,
with no picks, is attributed at class level to Indian stocks / International ETFs pro rata to their
current values.
Mode "targets": contribution-only rebalancing toward the user's targets:
  desired_c = target_c × (total + budget), gap_c = max(0, desired_c − current_c);
  if Σgap ≥ budget the budget is split pro rata to the gaps, else each gap is filled and the rest is
  split by target weights. Mutual-fund money follows the monthly_plan MF proportions.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from app.calc.allocation import ASSET_CLASS_INTL_ETF, ASSET_CLASS_MF, ASSET_CLASS_STOCKS
from app.calc.concentration import THRESHOLDS, Threshold, level_for
from app.calc.drift import drift, fold_classes
from app.calc.simulator import SimHolding
from app.money import format_inr, format_pct, value_paise

PRESET_BUDGETS_RUPEES = [6000, 8000, 10000, 15000, 20000]
THEMATIC_NOTES = {
    "MAFANG": "tracks the NYSE FANG+ index — 10 large US technology-oriented companies (thematic, concentrated)",
    "HNGSNGBEES": "tracks the Hang Seng index — large companies listed in Hong Kong (single market)",
}
ASSUMPTIONS = [
    "Prices/NAVs stay at the latest cached quote; no charges or taxes.",
    "Mutual-fund money is fully invested (fractional units). Picked stocks/ETFs get whole units only; "
    "any remainder is shown as uninvested.",
    "Without picks, the stocks/ETFs bucket is attributed to Indian stocks and International ETFs in "
    "proportion to their current values; it is not assigned to any company.",
    "Target mode only directs new money; it never assumes selling anything.",
    "Company weights cover direct stock holdings only (no mutual-fund look-through).",
]


@dataclass(frozen=True)
class PlanLine:
    label: str
    is_bucket: bool
    fraction: Decimal
    instrument_id: int | None = None


def split_paise(amount: int, weights: dict) -> dict:
    """Split paise by non-negative weights; rounding remainder goes to the largest weight. Exact sum."""
    total_w = sum(weights.values())
    if amount <= 0 or not weights or total_w <= 0:
        return {k: 0 for k in weights}
    parts = {k: int((Decimal(amount) * w / total_w).to_integral_value(rounding=ROUND_DOWN)) for k, w in weights.items()}
    rem = amount - sum(parts.values())
    biggest = max(weights, key=lambda k: weights[k])
    parts[biggest] += rem
    return parts


class _Book:
    """Accumulates where the budget goes and the projected values."""

    def __init__(self, holdings: list[SimHolding]):
        self.by_id = {h.instrument_id: h for h in holdings}
        self.inst_add: dict[int, int] = {}
        self.class_add: dict[str, int] = {}
        self.lines: list[dict] = []
        self.uninvested = 0

    def to_instrument(self, iid: int, amount: int, label_prefix: str = "") -> None:
        h = self.by_id[iid]
        if h.asset_type == "MF":
            units = (Decimal(amount) / 100 / h.price).quantize(Decimal("0.001"), rounding=ROUND_DOWN)
            spent = amount
        else:
            units = (Decimal(amount) / 100 / h.price).to_integral_value(rounding=ROUND_DOWN)
            spent = value_paise(units, h.price)
        self.inst_add[iid] = self.inst_add.get(iid, 0) + spent
        self.uninvested += amount - spent
        self.lines.append({"label": f"{label_prefix}{h.name}", "asset_class": h.asset_class, "instrument_id": iid,
                           "amount_paise": amount, "invested_paise": spent, "uninvested_paise": amount - spent,
                           "units": str(units), "whole_units_only": h.asset_type != "MF", "unit_price": str(h.price)})

    def to_class(self, cls: str, amount: int, note: str) -> None:
        if amount <= 0:
            return
        self.class_add[cls] = self.class_add.get(cls, 0) + amount
        self.lines.append({"label": f"{cls} (class level)", "asset_class": cls, "instrument_id": None,
                           "amount_paise": amount, "invested_paise": amount, "uninvested_paise": 0,
                           "units": None, "whole_units_only": False, "unit_price": None, "note": note})


def _bucket(book: _Book, amount: int, holdings: list[SimHolding], picks: list[int], classes: list[str]) -> None:
    """Stocks/ETFs money: equal split across picks (whole units), else class level pro rata."""
    eligible = [p for p in picks if p in book.by_id and book.by_id[p].asset_type != "MF"
                and book.by_id[p].asset_class in classes]
    if eligible:
        for iid, part in split_paise(amount, {i: Decimal(1) for i in eligible}).items():
            book.to_instrument(iid, part, "Stocks/ETFs bucket → ")
        return
    vals = {c: Decimal(sum(h.value_paise for h in holdings if h.asset_class == c)) for c in classes}
    if sum(vals.values()) == 0:
        vals = {classes[0]: Decimal(1)}
    for cls, part in split_paise(amount, vals).items():
        book.to_class(cls, part, "Not assigned to a specific company; pick stocks/ETFs to see whole-unit detail.")


def _mf_split(book: _Book, amount: int, mf_plan: dict[int, Decimal]) -> None:
    held = {k: v for k, v in mf_plan.items() if k in book.by_id and v > 0}
    if not held:
        book.to_class(ASSET_CLASS_MF, amount, "No fund in monthly_plan matches a priced holding.")
        return
    for iid, part in split_paise(amount, held).items():
        book.to_instrument(iid, part)


def _result(mode: str, label: str, book: _Book, holdings: list[SimHolding], budget: int, target_classes: list[str],
            targets: dict[str, Decimal] | None, tolerance_pp: Decimal, thresholds: dict[str, Threshold]) -> dict:
    total_before = sum(h.value_paise for h in holdings)
    cls_before: dict[str, int] = {}
    for h in holdings:
        cls_before[h.asset_class] = cls_before.get(h.asset_class, 0) + h.value_paise
    cls_add: dict[str, int] = dict(book.class_add)
    for iid, v in book.inst_add.items():
        c = book.by_id[iid].asset_class
        cls_add[c] = cls_add.get(c, 0) + v
    before_f = fold_classes(cls_before, target_classes)
    add_f = fold_classes(cls_add, target_classes)
    after_f = {c: before_f.get(c, 0) + add_f.get(c, 0) for c in before_f}
    total_after = total_before + sum(add_f.values())

    classes = []
    for c in target_classes:
        if not (before_f.get(c) or add_f.get(c) or (targets and targets.get(c))):
            continue
        classes.append({
            "asset_class": c, "held": before_f.get(c, 0) > 0,
            "current_paise": before_f.get(c, 0), "add_paise": add_f.get(c, 0), "projected_paise": after_f.get(c, 0),
            "current": str(Decimal(before_f.get(c, 0)) / total_before) if total_before else "0",
            "projected": str(Decimal(after_f.get(c, 0)) / total_after) if total_after else "0",
            "target": str(targets[c]) if targets else None,
        })

    mf = [h for h in holdings if h.asset_type == "MF"]
    mf_before = sum(h.value_paise for h in mf)
    mf_after = mf_before + sum(v for i, v in book.inst_add.items() if book.by_id[i].asset_type == "MF")
    mf_rows = [{"instrument_id": h.instrument_id, "name": h.name, "category": h.category,
                "add_paise": book.inst_add.get(h.instrument_id, 0),
                "current": str(Decimal(h.value_paise) / mf_before) if mf_before else "0",
                "projected": str(Decimal(h.value_paise + book.inst_add.get(h.instrument_id, 0)) / mf_after)
                if mf_after else "0"} for h in mf]

    considerations = []
    if targets:
        for row in drift(after_f, total_after, targets, tolerance_pp):
            if row["status"] != "WITHIN BAND":
                dev = Decimal(row["deviation_pp"])
                side = "above" if dev > 0 else "below"
                considerations.append({
                    "kind": row["status"], "title": f"{row['asset_class']} would be {row['status'].lower()}",
                    "text": f"Allocation consideration: after this contribution, {row['asset_class']} would be "
                            f"{format_pct(Decimal(row['current']))} of the portfolio vs a target of "
                            f"{format_pct(Decimal(row['target']))} — {abs(dev):.1f} pp {side}, outside the "
                            f"±{tolerance_pp} pp band.",
                    "calculation": row["calculation"]})
    stocks = [h for h in holdings if h.asset_type == "STOCK"]
    if stocks and total_after:
        top = max(stocks, key=lambda h: h.value_paise + book.inst_add.get(h.instrument_id, 0))
        v = top.value_paise + book.inst_add.get(top.instrument_id, 0)
        share = Decimal(v) / total_after
        th = thresholds["largest_company_of_portfolio"]
        lvl = level_for(share, th)
        if lvl != "LOW":
            considerations.append({
                "kind": "CONCENTRATION", "level": lvl,
                "title": f"Single-company weight: {lvl}",
                "text": f"Allocation consideration: {top.short_name} would be {format_pct(share)} of the portfolio "
                        f"after this contribution ({lvl}; thresholds {format_pct(th.low, 0)} / {format_pct(th.high, 0)}).",
                "calculation": f"{format_inr(v)} / {format_inr(total_after)} = {format_pct(share)}"})
    intl = [h for h in holdings if h.asset_class == ASSET_CLASS_INTL_ETF]
    if intl and total_after:
        v = sum(h.value_paise + book.inst_add.get(h.instrument_id, 0) for h in intl) + book.class_add.get(ASSET_CLASS_INTL_ETF, 0)
        share = Decimal(v) / total_after
        notes = "; ".join(f"{h.short_name} {THEMATIC_NOTES[h.short_name]}" for h in intl if h.short_name in THEMATIC_NOTES)
        considerations.append({
            "kind": "INTERNATIONAL", "title": "International / thematic exposure",
            "text": f"Allocation consideration: international ETFs would be {format_pct(share)} of the portfolio. "
                    f"{notes}. These carry currency and single-market or theme concentration.",
            "calculation": f"{format_inr(v)} / {format_inr(total_after)} = {format_pct(share)}"})

    return {
        "mode": mode, "label": label, "available": True, "budget_paise": budget,
        "invested_paise": budget - book.uninvested, "uninvested_paise": book.uninvested,
        "total_before_paise": total_before, "total_after_paise": total_after,
        "lines": book.lines, "asset_classes": classes, "mutual_funds": mf_rows, "considerations": considerations,
    }


def plan_mode(holdings: list[SimHolding], budget: int, plan: list[PlanLine], picks: list[int],
              target_classes: list[str], targets: dict[str, Decimal] | None, tolerance_pp: Decimal,
              thresholds: dict[str, Threshold] = THRESHOLDS) -> dict:
    book = _Book(holdings)
    parts = split_paise(budget, {i: line.fraction for i, line in enumerate(plan)})
    mf_amount = 0
    mf_weights: dict[int, Decimal] = {}
    for i, line in enumerate(plan):
        if line.is_bucket:
            _bucket(book, parts[i], holdings, picks, [ASSET_CLASS_STOCKS, ASSET_CLASS_INTL_ETF])
        elif line.instrument_id in book.by_id:
            book.to_instrument(line.instrument_id, parts[i])
        else:
            mf_amount += parts[i]
            mf_weights[i] = line.fraction
    if mf_amount:
        book.to_class(ASSET_CLASS_MF, mf_amount, "Fund in monthly_plan has no priced holding.")
    pct = " / ".join(f"{line.label.split(' - ')[0]} {format_pct(line.fraction, 0)}" for line in plan)
    return _result("plan", f"Current monthly_plan proportions ({pct})", book, holdings, budget, target_classes,
                   targets, tolerance_pp, thresholds)


def targets_mode(holdings: list[SimHolding], budget: int, plan: list[PlanLine], picks: list[int],
                 target_classes: list[str], targets: dict[str, Decimal] | None, tolerance_pp: Decimal,
                 thresholds: dict[str, Threshold] = THRESHOLDS) -> dict:
    if not targets:
        return {"mode": "targets", "label": "Toward your target allocation", "available": False,
                "reason": "Set your targets in Settings to see this distribution."}
    book = _Book(holdings)
    cur: dict[str, int] = {}
    for h in holdings:
        cur[h.asset_class] = cur.get(h.asset_class, 0) + h.value_paise
    cur = fold_classes(cur, target_classes)
    total_after = sum(cur.values()) + budget
    gaps = {c: max(Decimal(0), targets[c] * total_after - cur.get(c, 0)) for c in target_classes}
    gap_sum = sum(gaps.values())
    if gap_sum >= budget:
        alloc = split_paise(budget, gaps)
    else:
        filled = {c: int(g) for c, g in gaps.items()}
        rest = split_paise(budget - sum(filled.values()), {c: targets[c] for c in target_classes})
        alloc = {c: filled[c] + rest[c] for c in target_classes}
    mf_plan = {line.instrument_id: line.fraction for line in plan if not line.is_bucket and line.instrument_id}
    for cls in target_classes:
        amount = alloc.get(cls, 0)
        if amount <= 0:
            continue
        if cls == ASSET_CLASS_MF:
            _mf_split(book, amount, mf_plan)
        elif cls in (ASSET_CLASS_STOCKS, ASSET_CLASS_INTL_ETF):
            _bucket(book, amount, holdings, picks, [cls])
        else:
            book.to_class(cls, amount, f"You hold no {cls} instrument; amount shown at class level only.")
    return _result("targets", "Toward your target allocation (new money only, no selling)", book, holdings, budget,
                   target_classes, targets, tolerance_pp, thresholds)
