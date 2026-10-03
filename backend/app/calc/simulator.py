"""Next-contribution simulator: BEFORE -> AFTER weights for hypothetical contributions.

Pure function, no market calls. Assumptions (returned with every result):
- prices stay at the latest cached quote; no brokerage, taxes or stamp duty;
- mutual-fund units are fractional, so the whole amount is invested;
- stocks/ETFs are bought in whole units only; any remainder stays uninvested.
Language is neutral by design: it describes how weights would move, never what to buy.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import ROUND_DOWN, Decimal

from app.calc.allocation import ASSET_CLASS_MF, ASSET_CLASS_ORDER
from app.money import format_inr, format_pct, value_paise

ASSUMPTIONS = [
    "Prices/NAVs stay at the latest cached quote shown on each holding.",
    "No brokerage, taxes, exit loads or stamp duty are included.",
    "Mutual-fund units are fractional: the full amount is invested.",
    "Stocks/ETFs are bought in whole units; any remainder is shown as uninvested.",
    "Company weights cover direct stock holdings only (no mutual-fund look-through).",
]

PRESET_AMOUNTS_RUPEES = [500, 1000, 2000, 4000, 10000]


@dataclass(frozen=True)
class SimHolding:
    instrument_id: int
    name: str
    short_name: str
    asset_type: str  # STOCK | ETF | MF
    asset_class: str
    category: str
    price: Decimal  # rupees
    value_paise: int


@dataclass(frozen=True)
class LookContext:
    """Inputs for look-through effects (optional)."""

    direct_meta: dict  # instrument_id -> (isin | None, sector label, asset_type) for stocks/ETFs
    fund_rows: dict  # fund instrument_id -> list[FundRow] (only funds with a disclosure)
    isin_sector: dict  # ISIN -> sector


def lookthrough_maps(holdings: list[SimHolding], ctx: LookContext) -> tuple[dict, dict, dict]:
    from app.calc.lookthrough import DirectHolding, FundLook, company_exposure, sector_lookthrough

    total = sum(h.value_paise for h in holdings)
    direct = [DirectHolding(h.instrument_id, h.short_name, ctx.direct_meta[h.instrument_id][0], h.value_paise,
                            h.asset_type, ctx.direct_meta[h.instrument_id][1])
              for h in holdings if h.asset_type != "MF" and h.instrument_id in ctx.direct_meta]
    funds = [FundLook(h.instrument_id, h.name, h.value_paise, ctx.fund_rows.get(h.instrument_id))
             for h in holdings if h.asset_type == "MF"]
    comp = company_exposure(direct, funds, total)["companies"]
    sect = sector_lookthrough(direct, funds, ctx.isin_sector, total)
    t = Decimal(total) if total else Decimal(1)
    return ({c["isin"]: Decimal(c["total_paise"]) / t for c in comp}, {c["isin"]: c["name"] for c in comp},
            {r["sector"]: Decimal(r["value_paise"]) / t for r in sect})


@dataclass(frozen=True)
class Scenario:
    key: str
    label: str
    allocations: dict[int, Decimal]  # instrument_id -> fraction of the amount (sums to 1)


def snapshot(holdings: list[SimHolding]) -> dict:
    total = sum(h.value_paise for h in holdings)
    t = Decimal(total) if total else Decimal(1)
    classes = {c: Decimal(0) for c in ASSET_CLASS_ORDER}
    for h in holdings:
        classes[h.asset_class] += Decimal(h.value_paise) / t
    mf = [h for h in holdings if h.asset_type == "MF"]
    mf_total = sum(h.value_paise for h in mf)
    mf_split = {h.instrument_id: (Decimal(h.value_paise) / mf_total if mf_total else Decimal(0)) for h in mf}
    companies = {h.instrument_id: Decimal(h.value_paise) / t for h in holdings if h.asset_type == "STOCK"}
    instruments = {h.instrument_id: Decimal(h.value_paise) / t for h in holdings}
    categories: dict[str, Decimal] = {}
    for h in holdings:
        if h.asset_type == "MF":
            categories[h.category] = categories.get(h.category, Decimal(0)) + Decimal(h.value_paise) / t
    return {
        "total_paise": total,
        "asset_classes": classes,
        "mf_split": mf_split,
        "companies": companies,
        "instruments": instruments,
        "mf_categories": categories,
    }


def _split_amount(amount_paise: int, allocations: dict[int, Decimal]) -> dict[int, int]:
    """Split paise by fractions; the last item absorbs rounding so parts sum exactly."""
    ids = list(allocations)
    parts: dict[int, int] = {}
    remaining = amount_paise
    for i, iid in enumerate(ids):
        if i == len(ids) - 1:
            parts[iid] = remaining
        else:
            p = int((Decimal(amount_paise) * allocations[iid]).to_integral_value(rounding=ROUND_DOWN))
            parts[iid] = p
            remaining -= p
    return parts


def _verb(before: Decimal, after: Decimal) -> str:
    b, a = before.quantize(Decimal("0.001")), after.quantize(Decimal("0.001"))
    if a > b:
        return "raise"
    if a < b:
        return "lower"
    return "leave unchanged"


def _move(subject: str, before: Decimal, after: Decimal) -> str:
    """'would raise <subject> from a% to b%' (subject is the object of the verb)."""
    verb = _verb(before, after)
    if verb == "leave unchanged":
        return f"would leave {subject} unchanged at {format_pct(before)}"
    return f"would {verb} {subject} from {format_pct(before)} to {format_pct(after)}"


def _goes(subject: str, before: Decimal, after: Decimal) -> str:
    """'<subject> would go from a% to b% of the portfolio' (subject is the sentence subject)."""
    if _verb(before, after) == "leave unchanged":
        return f"{subject} would stay at {format_pct(before)} of the portfolio"
    return f"{subject} would go from {format_pct(before)} to {format_pct(after)} of the portfolio"


def run_scenario(holdings: list[SimHolding], amount_paise: int, scenario: Scenario,
                 ctx: LookContext | None = None) -> dict:
    by_id = {h.instrument_id: h for h in holdings}
    before = snapshot(holdings)
    parts = _split_amount(amount_paise, scenario.allocations)

    after_holdings = list(holdings)
    legs = []
    invested = 0
    for iid, part in parts.items():
        h = by_id[iid]
        if h.asset_type == "MF":
            units = (Decimal(part) / 100 / h.price).quantize(Decimal("0.001"), rounding=ROUND_DOWN)
            spent = part
        else:
            units = (Decimal(part) / 100 / h.price).to_integral_value(rounding=ROUND_DOWN)
            spent = value_paise(units, h.price)
        invested += spent
        legs.append({
            "instrument_id": iid, "name": h.name, "amount_paise": part,
            "units": str(units), "invested_paise": spent, "uninvested_paise": part - spent,
            "unit_price": str(h.price), "whole_units_only": h.asset_type != "MF",
        })
        after_holdings = [replace(x, value_paise=x.value_paise + spent) if x.instrument_id == iid else x
                          for x in after_holdings]
    after = snapshot(after_holdings)

    def pairs(key: str) -> dict:
        return {k: {"before": str(before[key].get(k, Decimal(0))), "after": str(after[key].get(k, Decimal(0)))}
                for k in sorted(set(before[key]) | set(after[key]), key=str)}

    amount_txt = format_inr(amount_paise, decimals=False)
    sentences: list[str] = []
    if invested == 0:
        leg = legs[0]
        sentences.append(
            f"{amount_txt} is below the price of one unit of {leg['name']} "
            f"({format_inr(value_paise(Decimal(1), Decimal(leg['unit_price'])))}), so whole-unit "
            "investing would leave the portfolio unchanged in this scenario."
        )
    else:
        targets = [by_id[iid] for iid in parts]
        if len(targets) == 1:
            h = targets[0]
            if h.asset_type == "MF":
                subject = f"your {h.category} exposure"
                b = before["mf_categories"].get(h.category, Decimal(0))
                a = after["mf_categories"].get(h.category, Decimal(0))
            else:
                subject = f"{h.short_name}'s weight"
                b, a = before["instruments"][h.instrument_id], after["instruments"][h.instrument_id]
            sentences.append(f"Adding {format_inr(invested, decimals=False)} here {_move(subject, b, a)} of the portfolio.")
        else:
            sentences.append(f"Adding {format_inr(invested, decimals=False)} across {len(targets)} funds:")
            for h in targets:
                b = before["mf_categories"].get(h.category, Decimal(0))
                a = after["mf_categories"].get(h.category, Decimal(0))
                sentences.append(f"{h.category} exposure: {format_pct(b)} → {format_pct(a)} of the portfolio.")
        touched = {by_id[i].asset_class for i in parts}
        for cls in ASSET_CLASS_ORDER:
            if cls in touched:
                sentences.append(_goes(cls, before["asset_classes"][cls], after["asset_classes"][cls]) + ".")
        if before["companies"]:
            top_id = max(before["companies"], key=lambda k: before["companies"][k])
            top = by_id[top_id]
            sentences.append(_goes(f"{top.short_name} (your largest company holding)",
                                   before["companies"][top_id], after["companies"][top_id]) + ".")
        if invested < amount_paise:
            sentences.append(f"{format_inr(amount_paise - invested)} would remain uninvested (whole units only).")

    top_companies = sorted(after["companies"], key=lambda k: before["companies"].get(k, 0), reverse=True)[:5]

    look = None
    if ctx is not None and invested:
        cb, names, sb = lookthrough_maps(holdings, ctx)
        ca, names_a, sa = lookthrough_maps(after_holdings, ctx)
        names = {**names_a, **names}
        top_c = sorted(set(cb) | set(ca), key=lambda k: -max(cb.get(k, 0), ca.get(k, 0)))[:6]
        top_s = sorted(set(sb) | set(sa), key=lambda k: -max(sb.get(k, 0), sa.get(k, 0)))[:6]
        look = {
            "companies": [{"isin": k, "name": names[k], "before": str(cb.get(k, Decimal(0))),
                           "after": str(ca.get(k, Decimal(0)))} for k in top_c],
            "sectors": [{"name": k, "before": str(sb.get(k, Decimal(0))), "after": str(sa.get(k, Decimal(0)))}
                        for k in top_s],
            "funds_without_disclosure": [h.name for h in holdings if h.asset_type == "MF"
                                         and h.instrument_id not in ctx.fund_rows],
        }
        if top_c:
            k = top_c[0]
            sentences.append("Allocation consideration: " + _goes(
                f"{names[k]}'s total exposure (direct + through funds)", cb.get(k, Decimal(0)), ca.get(k, Decimal(0))) + ".")
    return {
        "key": scenario.key,
        "label": scenario.label,
        "amount_paise": amount_paise,
        "invested_paise": invested,
        "uninvested_paise": amount_paise - invested,
        "legs": legs,
        "total_before_paise": before["total_paise"],
        "total_after_paise": after["total_paise"],
        "asset_classes": [
            {"name": c, **pairs("asset_classes")[c]} for c in ASSET_CLASS_ORDER
            if before["asset_classes"][c] or after["asset_classes"][c]
        ],
        "mf_split": [
            {"instrument_id": k, "name": by_id[k].name, "category": by_id[k].category, **v}
            for k, v in pairs("mf_split").items()
        ],
        "top_companies": [
            {"instrument_id": k, "name": by_id[k].short_name,
             "before": str(before["companies"].get(k, Decimal(0))), "after": str(after["companies"][k])}
            for k in top_companies
        ],
        "sentences": sentences,
        "lookthrough": look,
    }


def default_scenarios(holdings: list[SimHolding], plan_mf: dict[int, Decimal]) -> list[Scenario]:
    """One scenario per held fund, plus a split in monthly_plan proportions (MF part only)."""
    scenarios = [
        Scenario(f"mf:{h.instrument_id}", f"Add to {h.name}", {h.instrument_id: Decimal(1)})
        for h in holdings if h.asset_type == "MF"
    ]
    held = {h.instrument_id for h in holdings}
    plan = {k: v for k, v in plan_mf.items() if k in held and v > 0}
    if len(plan) > 1:
        total = sum(plan.values())
        scenarios.append(Scenario(
            "mf_plan_split",
            "Split across funds as per monthly plan (" + " / ".join(format_pct(v / total, 1) for v in plan.values()) + ")",
            {k: v / total for k, v in plan.items()},
        ))
    return scenarios


def instrument_scenario(h: SimHolding) -> Scenario:
    return Scenario(f"inst:{h.instrument_id}", f"Add to {h.name}", {h.instrument_id: Decimal(1)})


def simulate(holdings: list[SimHolding], amount_paise: int, scenarios: list[Scenario],
             ctx: LookContext | None = None) -> dict:
    if amount_paise <= 0:
        raise ValueError("Amount must be positive")
    before = snapshot(holdings)
    return {
        "amount_paise": amount_paise,
        "assumptions": ASSUMPTIONS,
        "before": {
            "total_paise": before["total_paise"],
            "asset_classes": [{"name": c, "weight": str(before["asset_classes"][c])}
                              for c in ASSET_CLASS_ORDER if before["asset_classes"][c]],
            "mf_total_share": str(before["asset_classes"][ASSET_CLASS_MF]),
        },
        "scenarios": [run_scenario(holdings, amount_paise, s, ctx) for s in scenarios],
    }
