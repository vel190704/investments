"""All HTTP endpoints under /api. Read-only analytics; nothing here places orders."""

from __future__ import annotations

import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import repository as repo
from app.calc.simulator import PRESET_AMOUNTS_RUPEES, ASSUMPTIONS, default_scenarios, instrument_scenario, simulate
from app.db import get_session
from app.importer.run import format_report, import_workbook
from app.market.service import refresh_prices
from app.money import rupees_to_paise
from app.resolve.service import decide, resolve_identifiers
from app.services import portfolio as pf
from app.timeutil import as_utc

router = APIRouter(prefix="/api")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@router.get("/health")
def health():
    return {"status": "ok"}


# ---------------- import
@router.post("/import")
async def upload(file: UploadFile = File(...), resolve: bool = True, session: Session = Depends(get_session)):
    if not (file.filename or "").lower().endswith(".xlsx"):
        raise HTTPException(400, "Please upload an .xlsx workbook")
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large")
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "upload.xlsx"
        p.write_bytes(data)
        report = import_workbook(session, p, file_name=Path(file.filename).name)
    session.commit()
    resolution = None
    if report["ok"] and resolve:
        try:
            resolution = resolve_identifiers(session)
            session.commit()
        except Exception as e:
            resolution = {"summary": f"Identifier matching skipped: {e}", "errors": [str(e)]}
    return {"report": report, "text": format_report(report), "resolution": resolution}


@router.get("/import/runs")
def import_runs(session: Session = Depends(get_session)):
    return [{"id": r.id, "started_at": as_utc(r.started_at).isoformat(), "file_name": r.file_name, "ok": r.ok,
             "rows_loaded": r.rows_loaded, "rows_skipped": r.rows_skipped, "rows_errors": r.rows_errors,
             "report": r.report} for r in repo.import_runs(session)]


# ---------------- mappings
@router.get("/mappings")
def mappings(session: Session = Depends(get_session)):
    cands = repo.candidates(session)
    out = []
    for i in repo.all_instruments(session):
        mine = [c for c in cands if c.instrument_id == i.id]
        kind = "SCHEME_CODE" if i.asset_type == "MF" else "ISIN"
        out.append({
            "instrument_id": i.id, "name": i.name, "symbol": i.symbol, "asset_type": i.asset_type,
            "exposure": i.exposure, "isin": i.isin, "scheme_code": i.scheme_code, "needed_kind": kind,
            "status": "CONFIRMED" if any(c.kind == kind and c.status == "CONFIRMED" for c in mine)
            else "PENDING" if any(c.kind == kind and c.status == "PENDING" for c in mine) else "NO_CANDIDATES",
            "candidates": [{"id": c.id, "kind": c.kind, "value": c.value, "label": c.label, "source": c.source,
                            "score": c.score, "status": c.status, "details": c.details,
                            "decided_at": as_utc(c.decided_at).isoformat() if c.decided_at else None} for c in mine],
        })
    return {"instruments": out,
            "pending": sum(1 for x in out if x["status"] != "CONFIRMED")}


@router.post("/mappings/resolve")
def mappings_resolve(session: Session = Depends(get_session)):
    return resolve_identifiers(session)


@router.post("/mappings/candidates/{cid}/confirm")
def confirm(cid: int, session: Session = Depends(get_session)):
    try:
        c = decide(session, cid, True)
    except KeyError:
        raise HTTPException(404, "candidate not found") from None
    return {"id": c.id, "status": c.status}


@router.post("/mappings/candidates/{cid}/reject")
def reject(cid: int, session: Session = Depends(get_session)):
    try:
        c = decide(session, cid, False)
    except KeyError:
        raise HTTPException(404, "candidate not found") from None
    return {"id": c.id, "status": c.status}


# ---------------- market data
@router.post("/market/refresh")
def market_refresh(session: Session = Depends(get_session)):
    return refresh_prices(session, trigger="manual")


@router.get("/market/status")
def market_status(session: Session = Depends(get_session)):
    runs = repo.refresh_runs(session, 5)
    return [{"id": r.id, "trigger": r.trigger, "started_at": as_utc(r.started_at).isoformat(),
             "finished_at": as_utc(r.finished_at).isoformat() if r.finished_at else None,
             "ok_count": r.ok_count, "error_count": r.error_count, "results": r.results} for r in runs]


# ---------------- portfolio
@router.get("/portfolio/summary")
def portfolio_summary(session: Session = Depends(get_session)):
    return pf.summary(session)


@router.get("/holdings")
def holdings(session: Session = Depends(get_session)):
    return pf.holdings(session)


@router.get("/allocation")
def allocation(session: Session = Depends(get_session)):
    return pf.allocation(session)


@router.get("/plan")
def plan(session: Session = Depends(get_session)):
    return pf.plan(session)


@router.get("/transactions")
def transactions(session: Session = Depends(get_session)):
    inst = {i.id: i for i in repo.all_instruments(session)}
    return [{"id": t.id, "date": t.date.isoformat(), "type": t.type, "name": inst[t.instrument_id].name,
             "symbol": inst[t.instrument_id].symbol, "asset_type": inst[t.instrument_id].asset_type,
             "quantity": pf.s(t.quantity), "price": pf.s(t.price), "amount_paise": t.amount_paise,
             "charges_paise": t.charges_paise, "platform": t.platform, "notes": t.notes, "source_row": t.source_row}
            for t in repo.all_transactions(session)]


# ---------------- simulator
@router.get("/simulator/options")
def simulator_options(session: Session = Depends(get_session)):
    hs, excluded = pf.sim_holdings(session)
    defaults = default_scenarios(hs, pf.plan_mf_fractions(session))
    return {
        "presets_rupees": PRESET_AMOUNTS_RUPEES,
        "assumptions": ASSUMPTIONS,
        "default_scenarios": [{"key": sc.key, "label": sc.label} for sc in defaults],
        "instruments": [{"instrument_id": h.instrument_id, "name": h.name, "short_name": h.short_name,
                         "asset_type": h.asset_type, "price": str(h.price)} for h in hs],
        "excluded": excluded,
    }


class SimRequest(BaseModel):
    amount: str  # rupees, e.g. "1000" or "1500.50"
    scenario_keys: list[str] | None = None  # e.g. ["mf:3", "mf_plan_split", "inst:1"]


@router.post("/simulator")
def simulator(req: SimRequest, session: Session = Depends(get_session)):
    try:
        amount_paise = rupees_to_paise(req.amount)
    except (InvalidOperation, ValueError):
        raise HTTPException(422, "amount must be a number of rupees") from None
    if amount_paise <= 0 or amount_paise > rupees_to_paise(Decimal("100000000")):
        raise HTTPException(422, "amount must be between ₹0.01 and ₹10,00,00,000")
    hs, excluded = pf.sim_holdings(session)
    if not hs:
        raise HTTPException(409, "No priced holdings yet: import the workbook and refresh prices first")
    by_key = {sc.key: sc for sc in default_scenarios(hs, pf.plan_mf_fractions(session))}
    by_key.update({f"inst:{h.instrument_id}": instrument_scenario(h) for h in hs})
    keys = req.scenario_keys or [k for k in by_key if k.startswith("mf") ]
    unknown = [k for k in keys if k not in by_key]
    if unknown:
        raise HTTPException(422, f"unknown scenario(s): {', '.join(unknown)}")
    result = simulate(hs, amount_paise, [by_key[k] for k in keys])
    result["excluded"] = excluded
    return result
