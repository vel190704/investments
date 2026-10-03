"""DB -> look-through inputs -> company exposure, sector exposure, overlap, sector page."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.calc import lookthrough as lt
from app.calc import sectors as sc
from app.services import settings as st
from app.services.classification import sectors_by_instrument
from app.services.disclosures import fund_rows, label, latest_by_fund
from app.services.portfolio import load_rows
from app.timeutil import today_ist


def nse_sector_by_isin(s: Session) -> dict[str, str]:
    """Sector names keyed by ISIN: NSE lists (cached file) + effective sectors of direct holdings."""
    out: dict[str, str] = {}
    try:
        from app.resolve.sources import NSE_INDEX_LISTS, parse_nse_index_list
        from app.config import get_settings

        for name, url in NSE_INDEX_LISTS.items():
            path = get_settings().cache_dir / url.rsplit("/", 1)[1]
            if path.exists():
                for r in parse_nse_index_list(path.read_text(encoding="utf-8"), name):
                    out.setdefault(r.isin, r.industry)
    except Exception:
        pass
    secs = sectors_by_instrument(s)
    for r in load_rows(s)[0]:
        if r.inst.isin and secs[r.inst.id].origin:
            out[r.inst.isin] = secs[r.inst.id].sector  # user overrides apply to look-through too
    return out


def inputs(s: Session):
    rows, _ = load_rows(s)
    priced = [r for r in rows if r.value_paise is not None]
    total = sum(r.value_paise for r in priced)
    secs = sectors_by_instrument(s)
    direct = [lt.DirectHolding(r.inst.id, r.inst.symbol or r.inst.name, r.inst.isin, r.value_paise, r.inst.asset_type,
                               secs[r.inst.id].sector) for r in priced if r.inst.asset_type != "MF"]
    latest = latest_by_fund(s)
    funds = []
    for r in priced:
        if r.inst.asset_type != "MF":
            continue
        d = latest.get(r.inst.id)
        funds.append(lt.FundLook(r.inst.id, r.inst.name, r.value_paise, fund_rows(d) if d else None,
                                 label(d) if d else None, d.as_of if d else None))
    return rows, priced, total, direct, funds


def stale_warnings(funds: list[lt.FundLook], today) -> list[dict]:
    return [{"fund": f.name, "as_of": f.as_of.isoformat(),
             "warning": f"{f.name}: holdings are as of {f.as_of.isoformat()}, more than {lt.STALE_MONTHS} months "
                        "old. Upload a newer disclosure."}
            for f in funds if f.rows and f.as_of and lt.is_stale(f.as_of, today)]


def health_thresholds(s: Session) -> dict:
    return st.health_thresholds(s)


def lookthrough(s: Session) -> dict:
    _, priced, total, direct, funds = inputs(s)
    th = health_thresholds(s)["company_lookthrough"]
    out = lt.company_exposure(direct, funds, total, (th.low, th.high))
    today = today_ist()
    out["stale"] = stale_warnings(funds, today)
    out["total_value_paise"] = total
    out["basis"] = ("Total exposure = direct value + Σ fund value × the company's weight in that fund. Companies are "
                    "matched by ISIN only. % are of total portfolio value (priced holdings).")
    return out


def overlap(s: Session) -> dict:
    _, _, _, _, funds = inputs(s)
    return {"pairs": lt.pairwise_overlap(funds),
            "not_looked_through": [f.name for f in funds if not f.rows],
            "basis": "Overlap(A, B) = Σ over common holdings (by ISIN) of min(weight in A, weight in B)."}


def sectors_page(s: Session) -> dict:
    rows, priced, total, direct, funds = inputs(s)
    isin_sector = nse_sector_by_isin(s)
    sector_rows = lt.sector_lookthrough(direct, funds, isin_sector, total)
    hth = health_thresholds(s)
    metrics = sc.sector_metrics(sector_rows, {"largest_sector": hth["sector_largest"], "sector_hhi": hth["sector_hhi"]})
    secs = sectors_by_instrument(s)
    from app.services.portfolio import inst_class

    region_vals = []
    for r in priced:
        cls = inst_class(r.inst)
        region = (r.inst.region or "International (region not classified)") if cls == "International ETFs" else "India"
        region_vals.append((region, r.value_paise))
    companies = lt.company_exposure(direct, funds, total)["companies"]
    return {
        "total_value_paise": total,
        "sectors": sector_rows,
        "metrics": metrics,
        "ranges": sc.range_checks(sector_rows, st.get(s, "sector_ranges")),
        "geography": sc.geography(region_vals, total),
        "themes": sc.theme_exposure(st.get(s, "themes"), companies, total),
        "direct": [{"instrument_id": r.inst.id, "name": r.inst.symbol or r.inst.name, "asset_type": r.inst.asset_type,
                    "sector": secs[r.inst.id].sector, "origin": secs[r.inst.id].origin, "manual": secs[r.inst.id].manual,
                    "source": secs[r.inst.id].source,
                    "as_of": secs[r.inst.id].as_of.isoformat() if secs[r.inst.id].as_of else None,
                    "value_paise": r.value_paise} for r in priced if r.inst.asset_type != "MF"],
        "funds_looked_through": [{"name": f.name, "label": f.label} for f in funds if f.rows],
        "funds_not_looked_through": [f.name for f in funds if not f.rows],
        "basis": "% of total portfolio value. Fund holdings are attributed to sectors by ISIN using NSE's "
                 "classification (or the AMC's industry label when the ISIN is not in NSE's lists).",
    }
