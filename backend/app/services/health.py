"""Assemble the Portfolio Health page from look-through, sectors, drift, overlap, settings."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calc import health as h
from app.calc import lookthrough as lt
from app.models import PriceQuote
from app.services import settings as st
from app.services.lookthrough import inputs, sectors_page, stale_warnings
from app.services.planning import emergency_fund
from app.services.portfolio import drift_block
from app.timeutil import today_ist


def price_history(s: Session, ids: list[int]) -> dict[int, list[Decimal]]:
    out: dict[int, list[Decimal]] = {i: [] for i in ids}
    for q in s.scalars(select(PriceQuote).where(PriceQuote.instrument_id.in_(ids)).order_by(PriceQuote.price_date)):
        out[q.instrument_id].append(q.price)
    return out


def health(s: Session) -> dict:
    rows, priced, total, direct, funds = inputs(s)
    th = st.health_thresholds(s)
    companies = lt.company_exposure(direct, funds, total, (th["company_lookthrough"].low,
                                                          th["company_lookthrough"].high))
    sp = sectors_page(s)
    d = drift_block(s, rows, total)
    pairs = lt.pairwise_overlap(funds)
    direct_v = sum(r.value_paise for r in priced if r.inst.asset_type != "MF")
    fund_v = sum(r.value_paise for r in priced if r.inst.asset_type == "MF")
    hist = price_history(s, [r.inst.id for r in priced])
    ef = emergency_fund(s)["status"]
    dims = [
        h.company_dimension(companies["companies"], any(f.rows for f in funds), th["company_lookthrough"]),
        h.sector_dimension(sp["metrics"]),
        h.drift_dimension(d["rows"] if d["targets_set"] else None, Decimal(d["tolerance_pp"]), th["drift_high_multiple"]),
        h.overlap_dimension(pairs, th["overlap"]),
        h.international_dimension(sp["geography"]),
        h.liquidity_dimension(direct_v, fund_v, total),
        h.volatility_dimension({r.inst.symbol or r.inst.name: (r.value_paise, hist[r.inst.id]) for r in priced}),
        h.emergency_dimension(ef, *th["emergency"]),
    ]
    return {
        "valuation_date": today_ist().isoformat(),
        "dimensions": dims,
        "stale": stale_warnings(funds, today_ist()),
        "not_looked_through": [f.name for f in funds if not f.rows],
        "note": "Each dimension stands alone. There is no overall score and no ranking of investments. "
                "Levels appear only where a threshold is defined (Settings › Health thresholds).",
    }
