"""Glue: DB rows -> pure calc functions -> API-ready dicts.

Money in *_paise ints; prices/quantities/weights as decimal strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app import repository as repo
from app.calc.allocation import (
    ASSET_CLASS_ORDER, asset_class_of, display_pct, weights,
)
from app.calc.concentration import company_concentration
from app.calc.positions import OversellError, Position, TxnInput, replay
from app.calc.simulator import SimHolding
from app.calc.xirr import group_xirr, position_xirr
from app.models import Instrument, PriceQuote
from app.money import value_paise
from app.timeutil import as_utc, today_ist

UNAVAILABLE = "Data unavailable"


def s(d: Decimal | None, places: int | None = None) -> str | None:
    if d is None:
        return None
    if places is not None:
        d = d.quantize(Decimal(1).scaleb(-places))
    return format(d, "f")


@dataclass
class HoldingRow:
    inst: Instrument
    pos: Position
    quote: PriceQuote | None
    unavailable_reason: str | None
    asset_class: str

    @property
    def value_paise(self) -> int | None:
        return value_paise(self.pos.quantity, self.quote.price) if self.quote else None


def _last_errors(session: Session) -> dict[int, str]:
    runs = repo.refresh_runs(session, 1)
    if not runs:
        return {}
    return {r["instrument_id"]: r["error"] for r in runs[0].results if not r.get("ok")}


def load_rows(session: Session) -> tuple[list[HoldingRow], dict]:
    instruments = {i.id: i for i in repo.all_instruments(session)}
    txns: dict[int, list[TxnInput]] = {}
    for t in repo.all_transactions(session):
        txns.setdefault(t.instrument_id, []).append(
            TxnInput(t.date, t.type, t.quantity, t.amount_paise, t.charges_paise, t.source_row or t.id))
    for f in repo.used_fallbacks(session):
        txns.setdefault(f.instrument_id, []).append(
            TxnInput(f.as_of_date, "OPENING", f.quantity, f.invested_paise, 0, 0))
    quotes = repo.latest_quotes(session)
    errors = _last_errors(session)
    rows, closed = [], {"realised_paise": Decimal(0), "dividends_paise": 0, "positions": []}
    for iid, items in txns.items():
        inst = instruments[iid]
        try:
            pos = replay(items)
        except OversellError as e:  # inconsistent history must not break every page
            closed.setdefault("inconsistent", []).append(f"{inst.symbol or inst.name}: {e}")
            continue
        if not pos.is_open:
            closed["realised_paise"] += pos.realised_paise
            closed["dividends_paise"] += pos.dividends_paise
            closed["positions"].append((inst, pos))  # still part of class/portfolio XIRR
            continue
        q = quotes.get(iid)
        reason = None
        if q is None:
            if inst.asset_type == "MF" and not inst.scheme_code:
                reason = f"{UNAVAILABLE}: AMFI scheme code not confirmed (see Mappings)"
            else:
                reason = f"{UNAVAILABLE}" + (f": {errors[iid]}" if iid in errors else ": prices not fetched yet")
        rows.append(HoldingRow(inst, pos, q, reason, asset_class_of(inst.asset_type, inst.exposure)))
    rows.sort(key=lambda r: (-(r.value_paise or 0), r.inst.name))
    return rows, closed


def _xirr_items(rows: list[HoldingRow], closed: dict, asset_class: str | None = None):
    items = [(r.inst.symbol or r.inst.name, r.pos, r.quote.price if r.quote else None)
             for r in rows if asset_class is None or r.asset_class == asset_class]
    items += [(i.symbol or i.name, p, None) for i, p in closed["positions"]
              if asset_class is None or asset_class_of(i.asset_type, i.exposure) == asset_class]
    return items


def _x(res) -> dict:
    return {"rate": s(Decimal(repr(res.rate)), 6) if res.rate is not None else None, "note": res.note,
            "flows": res.flows}


def xirr_report(session: Session) -> dict:
    """XIRR per instrument, per asset class and for the whole portfolio (dated rows only)."""
    rows, closed = load_rows(session)
    today = today_ist()
    instruments = [{"instrument_id": r.inst.id, "name": r.inst.name, "short_name": r.inst.symbol or r.inst.name,
                    "asset_class": r.asset_class, "open": True,
                    **_x(position_xirr(r.pos, r.quote.price if r.quote else None, today))} for r in rows]
    instruments += [{"instrument_id": i.id, "name": i.name, "short_name": i.symbol or i.name,
                     "asset_class": asset_class_of(i.asset_type, i.exposure), "open": False,
                     **_x(position_xirr(p, None, today))} for i, p in closed["positions"]]
    classes = sorted({x["asset_class"] for x in instruments}, key=ASSET_CLASS_ORDER.index)
    return {
        "valuation_date": today.isoformat(),
        "method": "Dated BUY/SIP (outflows), SELL and DIVIDEND (inflows) plus today's value of the units bought "
                  "on those dates. OPENING balances and their units are excluded. Actual/365, Excel-compatible.",
        "portfolio": _x(group_xirr(_xirr_items(rows, closed), today)),
        "asset_classes": [{"asset_class": c, **_x(group_xirr(_xirr_items(rows, closed, c), today))} for c in classes],
        "instruments": instruments,
    }


def _holding_dict(r: HoldingRow, total_value: int, valuation_date: date) -> dict:
    i, p, q = r.inst, r.pos, r.quote
    v = r.value_paise
    invested = p.invested_paise
    pnl = v - invested if v is not None else None
    day = None
    if q is not None and q.previous_close is not None:
        day = value_paise(p.quantity, q.price) - value_paise(p.quantity, q.previous_close)
    x = position_xirr(p, q.price if q else None, valuation_date)
    return {
        "instrument_id": i.id, "name": i.name, "short_name": i.symbol or i.name, "symbol": i.symbol,
        "asset_type": i.asset_type, "asset_class": r.asset_class, "category": i.category, "exposure": i.exposure,
        "platform": i.platform, "isin": i.isin, "scheme_code": i.scheme_code,
        "quantity": s(p.quantity), "avg_cost": s(p.avg_cost, 4),
        "price": s(q.price) if q else None, "previous_close": s(q.previous_close) if q else None,
        "price_date": q.price_date.isoformat() if q else None,
        "previous_date": q.previous_date.isoformat() if q and q.previous_date else None,
        "price_source": q.source if q else None, "price_source_ref": q.source_ref if q else None,
        "price_fetched_at": as_utc(q.fetched_at).isoformat() if q else None,
        "unavailable_reason": r.unavailable_reason,
        "invested_paise": invested, "value_paise": v, "pnl_paise": pnl,
        "pnl_pct": s(Decimal(pnl) / invested, 6) if pnl is not None and invested else None,
        "day_change_paise": day,
        "weight": s(Decimal(v) / total_value, 8) if v is not None and total_value else None,
        "realised_paise": int(p.realised_paise.to_integral_value()), "dividends_paise": p.dividends_paise,
        "opening_only": not p.has_dated_buys,
        "xirr": {"rate": s(Decimal(repr(x.rate)), 6) if x.rate is not None else None, "note": x.note},
    }


def holdings(session: Session) -> dict:
    rows, _ = load_rows(session)
    total = sum(r.value_paise for r in rows if r.value_paise is not None)
    today = today_ist()
    items = [_holding_dict(r, total, today) for r in rows]
    return {
        "total_value_paise": total,
        "valuation_date": today.isoformat(),
        "equity": [h for h in items if h["asset_type"] in ("STOCK", "ETF")],
        "mutual_funds": [h for h in items if h["asset_type"] == "MF"],
    }


def plan(session: Session) -> dict:
    items = repo.plan_items(session)
    return {
        "monthly_total_paise": sum(p.monthly_amount_paise for p in items),
        "items": [{"name": p.name, "platform": p.platform, "asset_type": p.asset_type,
                   "monthly_amount_paise": p.monthly_amount_paise, "allocation_fraction": s(p.allocation_fraction),
                   "instrument_id": p.instrument_id, "is_bucket": p.is_bucket} for p in items],
        "source": "monthly_plan sheet of the imported workbook",
    }


def _asset_classes(rows: list[HoldingRow], total: int) -> list[dict]:
    vals = {c: 0 for c in ASSET_CLASS_ORDER}
    for r in rows:
        if r.value_paise is not None:
            vals[r.asset_class] += r.value_paise
    vals = {c: v for c, v in vals.items() if v > 0}
    w = weights(vals, total)
    return [{"name": c, "value_paise": v, "weight": s(w[c], 8), "display_pct": s(display_pct(w[c]))}
            for c, v in vals.items()]


def concentration(rows: list[HoldingRow], total: int) -> dict:
    comps = [(r.inst.symbol or r.inst.name, r.value_paise) for r in rows
             if r.inst.asset_type == "STOCK" and r.value_paise is not None]
    c = company_concentration(comps, total)
    def conv(d):
        if isinstance(d, Decimal):
            return s(d, 8)
        if isinstance(d, dict):
            return {k: conv(v) for k, v in d.items()}
        if isinstance(d, list):
            return [conv(v) for v in d]
        return d
    return conv(c)


def _as_of(rows: list[HoldingRow]) -> list[dict]:
    by: dict[str, dict] = {}
    for r in rows:
        if r.quote is None:
            continue
        e = by.setdefault(r.quote.source, {"source": r.quote.source, "price_dates": set(), "fetched_at": None})
        e["price_dates"].add(r.quote.price_date.isoformat())
        f = as_utc(r.quote.fetched_at)
        if e["fetched_at"] is None or f > e["fetched_at"]:
            e["fetched_at"] = f
    return [{"source": e["source"], "price_dates": sorted(e["price_dates"]),
             "fetched_at": e["fetched_at"].isoformat()} for e in by.values()]


def summary(session: Session) -> dict:
    rows, closed = load_rows(session)
    priced = [r for r in rows if r.value_paise is not None]
    unpriced = [r for r in rows if r.value_paise is None]
    total = sum(r.value_paise for r in priced)
    invested_all = sum(r.pos.invested_paise for r in rows)
    invested_priced = sum(r.pos.invested_paise for r in priced)
    pnl = total - invested_priced
    day_rows = [r for r in priced if r.quote.previous_close is not None]
    day = sum(value_paise(r.pos.quantity, r.quote.price) - value_paise(r.pos.quantity, r.quote.previous_close)
              for r in day_rows)
    prev_val = sum(value_paise(r.pos.quantity, r.quote.previous_close) for r in day_rows)
    today = today_ist()
    px = group_xirr(_xirr_items(rows, closed), today)
    top = sorted(priced, key=lambda r: -r.value_paise)[:5]
    return {
        "valuation_date": today.isoformat(),
        "has_data": bool(rows),
        "total_value_paise": total,
        "total_invested_paise": invested_all,
        "invested_in_priced_paise": invested_priced,
        "pnl_paise": pnl,
        "pnl_pct": s(Decimal(pnl) / invested_priced, 6) if invested_priced else None,
        "excluded_unpriced": [{"name": r.inst.name, "invested_paise": r.pos.invested_paise,
                               "reason": r.unavailable_reason} for r in unpriced],
        "realised_paise": int(sum(r.pos.realised_paise for r in rows) + closed["realised_paise"]),
        "dividends_paise": sum(r.pos.dividends_paise for r in rows) + closed["dividends_paise"],
        "today_change": {
            "paise": day if day_rows else None,
            "pct": s(Decimal(day) / prev_val, 6) if day_rows and prev_val else None,
            "covered": [r.inst.symbol or r.inst.name for r in day_rows],
            "not_covered": [{"name": r.inst.symbol or r.inst.name,
                             "reason": "no previous NAV cached yet (AMFI file has latest NAV only)"
                             if r.inst.asset_type == "MF" else "no previous close"} for r in priced
                            if r.quote.previous_close is None],
        },
        "monthly_plan": plan(session),
        "asset_classes": _asset_classes(rows, total),
        "top_holdings": [{"instrument_id": r.inst.id, "name": r.inst.name, "short_name": r.inst.symbol or r.inst.name,
                          "asset_class": r.asset_class, "value_paise": r.value_paise,
                          "weight": s(Decimal(r.value_paise) / total, 8)} for r in top],
        "concentration_flags": concentration(rows, total)["flags"],
        "xirr": _x(px),
        "data_as_of": _as_of(rows),
    }


def allocation(session: Session) -> dict:
    rows, _ = load_rows(session)
    total = sum(r.value_paise for r in rows if r.value_paise is not None)
    w_inst = weights({r.inst.id: r.value_paise for r in rows if r.value_paise is not None}, total)
    return {
        "total_value_paise": total,
        "basis": "Weight = current market value / total portfolio value (priced holdings only). "
                 "Percentages are rounded half-up, so they may not add to exactly 100.",
        "asset_classes": _asset_classes(rows, total),
        "instruments": [{"instrument_id": r.inst.id, "name": r.inst.name, "short_name": r.inst.symbol or r.inst.name,
                         "asset_class": r.asset_class, "value_paise": r.value_paise,
                         "weight": s(w_inst[r.inst.id], 8), "display_pct": s(display_pct(w_inst[r.inst.id], 2))}
                        for r in rows if r.value_paise is not None],
        "excluded_unpriced": [{"name": r.inst.name, "reason": r.unavailable_reason} for r in rows if r.value_paise is None],
        "concentration": concentration(rows, total),
        "data_as_of": _as_of(rows),
    }


def sim_holdings(session: Session) -> tuple[list[SimHolding], list[dict]]:
    rows, _ = load_rows(session)
    out, excluded = [], []
    for r in rows:
        if r.value_paise is None:
            excluded.append({"name": r.inst.name, "reason": r.unavailable_reason})
            continue
        out.append(SimHolding(r.inst.id, r.inst.name, r.inst.symbol or r.inst.name, r.inst.asset_type, r.asset_class,
                              r.inst.category or r.inst.name, r.quote.price, r.value_paise))
    return out, excluded


def plan_mf_fractions(session: Session) -> dict[int, Decimal]:
    return {p.instrument_id: p.allocation_fraction for p in repo.plan_items(session)
            if p.instrument_id and not p.is_bucket}
