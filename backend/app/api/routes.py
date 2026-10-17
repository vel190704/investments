"""All HTTP endpoints under /api. Read-only analytics; nothing here places orders."""

from __future__ import annotations

import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
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
        try:
            from app.services.classification import refresh_classification

            refresh_classification(session)
            session.commit()
        except Exception:
            session.rollback()
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


@router.get("/xirr")
def xirr(session: Session = Depends(get_session)):
    return pf.xirr_report(session)


@router.get("/plan")
def plan(session: Session = Depends(get_session)):
    return pf.plan(session)


@router.get("/transactions")
def transactions(session: Session = Depends(get_session)):
    inst = {i.id: i for i in repo.all_instruments(session)}
    rows = sorted(repo.all_transactions(session), key=lambda t: (t.date, t.id), reverse=True)
    return [{"id": t.id, "date": t.date.isoformat(), "type": t.type, "instrument_id": t.instrument_id,
             "name": inst[t.instrument_id].name, "symbol": inst[t.instrument_id].symbol,
             "asset_type": inst[t.instrument_id].asset_type, "quantity": pf.s(t.quantity), "price": pf.s(t.price),
             "amount_paise": t.amount_paise, "charges_paise": t.charges_paise, "platform": t.platform,
             "notes": t.notes, "source": t.source, "source_row": t.source_row} for t in rows]


class TxnIn(BaseModel):
    date: str
    type: str
    instrument_id: int | None = None
    asset_type: str | None = None
    name: str | None = None
    symbol: str | None = None
    quantity: str | None = None
    price: str | None = None
    amount: str | None = None
    charges: str | None = None
    platform: str | None = None
    notes: str | None = None


@router.post("/transactions", status_code=201)
def add_transaction(body: TxnIn, session: Session = Depends(get_session)):
    from app.services.transactions import TxnValidationError, add_ui_transaction

    try:
        return add_ui_transaction(session, body.model_dump())
    except TxnValidationError as e:
        raise HTTPException(422, {"errors": e.errors}) from None


@router.delete("/transactions/{txn_id}")
def delete_transaction(txn_id: int, session: Session = Depends(get_session)):
    from app.services.transactions import TxnValidationError, delete_ui_transaction

    try:
        delete_ui_transaction(session, txn_id)
    except KeyError:
        raise HTTPException(404, "transaction not found") from None
    except TxnValidationError as e:
        raise HTTPException(409, str(e)) from None
    return {"deleted": txn_id}


@router.get("/instruments")
def instruments(session: Session = Depends(get_session)):
    return [{"instrument_id": i.id, "name": i.name, "symbol": i.symbol, "asset_type": i.asset_type,
             "platform": i.platform, "scheme_code": i.scheme_code} for i in repo.all_instruments(session)]


@router.get("/export.xlsx")
def export_xlsx(session: Session = Depends(get_session)):
    from app.services.export import build_workbook
    from app.timeutil import today_ist

    name = f"investment_tracker_export_{today_ist().isoformat()}.xlsx"
    return Response(build_workbook(session),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


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
    from app.services.lookthrough import simulator_context

    result = simulate(hs, amount_paise, [by_key[k] for k in keys], simulator_context(session))
    result["excluded"] = excluded
    return result


# ---------------- snapshots / history / change log
@router.get("/snapshots")
def snapshots(session: Session = Depends(get_session)):
    from app.services.snapshots import list_snapshots, snapshot_dict

    return [snapshot_dict(p) for p in reversed(list_snapshots(session))]


@router.post("/snapshots")
def take_snapshot_now(session: Session = Depends(get_session)):
    from app.services.snapshots import take_snapshot

    res = take_snapshot(session, trigger="manual")
    if res is None:
        raise HTTPException(409, "No holdings yet: import the workbook first")
    return res


@router.get("/snapshots/series")
def snapshot_series(session: Session = Depends(get_session)):
    from app.services.snapshots import series

    return series(session)


@router.get("/compare")
def compare_endpoint(a: str, b: str = "live", session: Session = Depends(get_session)):
    from app.services.snapshots import compare_states

    try:
        return compare_states(session, a, b)
    except KeyError as e:
        raise HTTPException(404, f"No snapshot for {e.args[0]}") from None
    except ValueError:
        raise HTTPException(422, "Dates must be YYYY-MM-DD or 'live'") from None


@router.get("/changes")
def changes(limit: int = 200, kind: str | None = None, session: Session = Depends(get_session)):
    from sqlalchemy import select

    from app.models import ChangeLogEntry

    q = select(ChangeLogEntry).order_by(ChangeLogEntry.occurred_at.desc(), ChangeLogEntry.id.desc()).limit(min(limit, 1000))
    if kind:
        q = q.where(ChangeLogEntry.kind == kind)
    return [{"id": e.id, "occurred_at": as_utc(e.occurred_at).isoformat(), "kind": e.kind, "cause": e.cause,
             "instrument_id": e.instrument_id, "snapshot_date": e.snapshot_date.isoformat() if e.snapshot_date else None,
             "summary": e.summary, "details": e.details} for e in session.scalars(q)]


# ---------------- settings
@router.get("/settings")
def get_settings_all(session: Session = Depends(get_session)):
    from app.services.settings import TARGET_CLASSES, all_settings

    return {"sections": all_settings(session), "target_classes": TARGET_CLASSES}


@router.put("/settings/{section}")
def put_setting(section: str, value: dict, session: Session = Depends(get_session)):
    from app.services.settings import SettingsError, put

    try:
        return {"section": section, "value": put(session, section, value)}
    except SettingsError as e:
        raise HTTPException(422, str(e)) from None


@router.delete("/settings/{section}")
def reset_setting(section: str, session: Session = Depends(get_session)):
    from app.services.settings import SettingsError, reset

    try:
        reset(session, section)
    except SettingsError as e:
        raise HTTPException(404, str(e)) from None
    return {"section": section, "reset": True}


# ---------------- planning
def _rupees_opt(v: str | None, field: str) -> int | None:
    if v is None or str(v).strip() == "":
        return None
    try:
        p = rupees_to_paise(v)
    except (InvalidOperation, ValueError):
        raise HTTPException(422, f"{field} must be a number of rupees") from None
    if p < 0:
        raise HTTPException(422, f"{field} must not be negative")
    return p


class PlannerIn(BaseModel):
    budget: str | None = None
    picks: list[int] = []


@router.post("/planner")
def planner(body: PlannerIn, session: Session = Depends(get_session)):
    from app.services.planning import planner as run

    budget = _rupees_opt(body.budget, "budget")
    if budget is not None and (budget == 0 or budget > rupees_to_paise(Decimal("10000000"))):
        raise HTTPException(422, "budget must be between ₹0.01 and ₹1,00,00,000")
    return run(session, budget, body.picks)


class ProjectionIn(BaseModel):
    start: str | None = None
    monthly: str | None = None
    years: int | None = None
    step_up: str | None = None
    custom_rate: str | None = None


@router.post("/projection")
def projection(body: ProjectionIn, session: Session = Depends(get_session)):
    from app.services.planning import projection as run

    def dec(v, name, lo, hi):
        if v is None or str(v).strip() == "":
            return None
        try:
            d = Decimal(str(v))
        except InvalidOperation:
            raise HTTPException(422, f"{name} must be a number") from None
        if not (lo <= d <= hi):
            raise HTTPException(422, f"{name} must be between {lo} and {hi}")
        return d

    if body.years is not None and not 1 <= body.years <= 50:
        raise HTTPException(422, "years must be between 1 and 50")
    return run(session, _rupees_opt(body.start, "start"), _rupees_opt(body.monthly, "monthly"), body.years,
               dec(body.step_up, "step-up", 0, 50), dec(body.custom_rate, "custom rate", -50, 50))


@router.get("/emergency-fund")
def emergency_fund(session: Session = Depends(get_session)):
    from app.services.planning import emergency_fund as run

    return run(session)


# ---------------- Phase 3: classification, sectors, fundamentals, disclosures, look-through, health
@router.get("/classification")
def classification(session: Session = Depends(get_session)):
    from app.calc.allocation import OVERRIDABLE_CLASSES
    from app.services.classification import sectors_by_instrument
    from app.services.portfolio import inst_class

    secs = sectors_by_instrument(session)
    return {
        "asset_classes": OVERRIDABLE_CLASSES,
        "instruments": [{
            "instrument_id": i.id, "name": i.name, "symbol": i.symbol, "asset_type": i.asset_type,
            "asset_class": inst_class(i), "asset_class_override": i.asset_class_override,
            "etf_underlying": i.etf_underlying, "etf_underlying_key": i.etf_underlying_key, "region": i.region,
            "sector": secs[i.id].sector, "sector_origin": secs[i.id].origin, "sector_manual": secs[i.id].manual,
            "sector_source": secs[i.id].source,
            "sector_as_of": secs[i.id].as_of.isoformat() if secs[i.id].as_of else None,
        } for i in repo.all_instruments(session)],
    }


class ClassificationIn(BaseModel):
    sector: str | None = None
    asset_class: str | None = None
    region: str | None = None
    note: str | None = None


@router.put("/instruments/{iid}/classification")
def set_classification(iid: int, body: ClassificationIn, session: Session = Depends(get_session)):
    from app.services.classification import ClassificationError, set_overrides

    try:
        set_overrides(session, iid, sector=body.sector, asset_class=body.asset_class, region=body.region, note=body.note)
    except KeyError:
        raise HTTPException(404, "instrument not found") from None
    except ClassificationError as e:
        raise HTTPException(422, str(e)) from None
    return {"ok": True}


@router.delete("/instruments/{iid}/classification/{field}")
def clear_classification(iid: int, field: str, session: Session = Depends(get_session)):
    from app.services.classification import ClassificationError, clear_override

    try:
        clear_override(session, iid, field)
    except KeyError:
        raise HTTPException(404, "instrument not found") from None
    except ClassificationError as e:
        raise HTTPException(422, str(e)) from None
    return {"ok": True}


@router.post("/sectors/refresh")
def sectors_refresh(session: Session = Depends(get_session)):
    from app.services.classification import refresh_classification

    return refresh_classification(session)


@router.get("/sectors")
def sectors(session: Session = Depends(get_session)):
    from app.services.lookthrough import sectors_page

    return sectors_page(session)


@router.get("/fundamentals")
def fundamentals(session: Session = Depends(get_session)):
    from app.services.fundamentals import report

    return report(session)


@router.post("/fundamentals/refresh")
def fundamentals_refresh(session: Session = Depends(get_session)):
    from app.services.fundamentals import refresh_fundamentals

    return refresh_fundamentals(session)


class FactIn(BaseModel):
    value: str
    source_note: str
    as_of: str


@router.put("/facts/{iid}/{metric}")
def put_fact(iid: int, metric: str, body: FactIn, session: Session = Depends(get_session)):
    from datetime import date as _date

    from app.calc.fundamentals import ManualEntryError
    from app.services.fundamentals import set_manual

    try:
        as_of = _date.fromisoformat(body.as_of)
    except ValueError:
        raise HTTPException(422, "as_of must be YYYY-MM-DD") from None
    try:
        set_manual(session, iid, metric, body.value, body.source_note, as_of)
    except KeyError:
        raise HTTPException(404, "instrument not found") from None
    except ManualEntryError as e:
        raise HTTPException(422, str(e)) from None
    return {"ok": True}


@router.delete("/facts/{iid}/{metric}")
def delete_fact(iid: int, metric: str, session: Session = Depends(get_session)):
    from app.services.fundamentals import delete_manual

    delete_manual(session, iid, metric)
    return {"ok": True}


@router.post("/disclosures")
async def upload_disclosure(file: UploadFile = File(...), instrument_id: int = 0, kind: str = "AMC_DISCLOSURE",
                            amc: str | None = None, as_of: str | None = None, index_name: str | None = None,
                            session: Session = Depends(get_session)):
    from datetime import date as _date

    from app.disclosures.engine import DisclosureFormatError
    from app.services.disclosures import upload

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large")
    try:
        d = _date.fromisoformat(as_of) if as_of else None
    except ValueError:
        raise HTTPException(422, "as_of must be YYYY-MM-DD") from None
    try:
        return upload(session, data, Path(file.filename or "upload").name, instrument_id, kind, amc or None, d,
                      index_name)
    except DisclosureFormatError as e:
        raise HTTPException(422, str(e)) from None


@router.get("/disclosures")
def disclosures(session: Session = Depends(get_session)):
    from app.disclosures.engine import LAYOUTS
    from app.services.disclosures import list_disclosures

    return {"disclosures": list_disclosures(session),
            "parsers": [{"key": k, "label": l.label} for k, l in LAYOUTS.items()]}


@router.delete("/disclosures/{did}")
def delete_disclosure(did: int, session: Session = Depends(get_session)):
    from app.services.disclosures import delete

    try:
        delete(session, did)
    except KeyError:
        raise HTTPException(404, "disclosure not found") from None
    return {"deleted": did}


@router.get("/lookthrough")
def lookthrough(session: Session = Depends(get_session)):
    from app.services.lookthrough import lookthrough as run

    return run(session)


@router.get("/overlap")
def overlap(session: Session = Depends(get_session)):
    from app.services.lookthrough import overlap as run

    return run(session)


@router.get("/health-check")
def portfolio_health(session: Session = Depends(get_session)):
    from app.services.health import health as run

    return run(session)


# ---------------- Phase 4: news, macro, AI analysis, journal, broker, alerts
@router.get("/news")
def news_feed(isin: str | None = None, category: str | None = None, days: int = 30,
              session: Session = Depends(get_session)):
    from app.services.news import feed

    return feed(session, isin or None, category or None, max(1, min(days, 90)))


@router.get("/news/recent")
def news_recent(session: Session = Depends(get_session)):
    from app.services.news import recent

    return recent(session)


@router.post("/news/refresh")
def news_refresh(session: Session = Depends(get_session)):
    from app.services.alerts import evaluate_alerts
    from app.services.news import refresh_news

    rep = refresh_news(session)
    try:
        rep["alerts_created"] = evaluate_alerts(session)["created"]
    except Exception:
        rep["alerts_created"] = 0
    return rep


@router.get("/macro")
def macro(session: Session = Depends(get_session)):
    from app.services.macro import sensitivity_page, snapshot

    return {"snapshot": snapshot(session), **sensitivity_page(session)}


@router.post("/macro/refresh")
def macro_refresh(session: Session = Depends(get_session)):
    from app.services.macro import refresh_macro

    return refresh_macro(session)


class MacroIn(BaseModel):
    value: str
    source_note: str
    as_of: str
    label: str | None = None
    unit: str | None = None


@router.put("/macro/{key}")
def macro_manual(key: str, body: MacroIn, session: Session = Depends(get_session)):
    from datetime import date as _date

    from app.services.macro import MacroError, set_manual

    try:
        as_of = _date.fromisoformat(body.as_of)
    except ValueError:
        raise HTTPException(422, "as_of must be YYYY-MM-DD") from None
    if not key.replace("_", "").isalnum() or len(key) > 50:
        raise HTTPException(422, "key must be letters, digits and underscores")
    try:
        set_manual(session, key, body.label, body.value, body.unit, body.source_note, as_of)
    except MacroError as e:
        raise HTTPException(422, str(e)) from None
    return {"ok": True}


@router.delete("/macro/{key}")
def macro_delete(key: str, session: Session = Depends(get_session)):
    from app.services.macro import delete_manual

    delete_manual(session, key)
    return {"ok": True}


class TagsIn(BaseModel):
    tags: list[str]
    note: str | None = None


@router.put("/sensitivities/{sector}")
def put_sensitivity(sector: str, body: TagsIn, session: Session = Depends(get_session)):
    from app.services.macro import MacroError, set_tags

    try:
        set_tags(session, sector, body.tags, body.note)
    except MacroError as e:
        raise HTTPException(422, str(e)) from None
    return {"ok": True}


@router.get("/analysis")
def analysis_cards(session: Session = Depends(get_session)):
    from app.services.analysis import cards

    return cards(session)


@router.post("/analysis/{iid}")
def analysis_run(iid: int, refresh: bool = False, session: Session = Depends(get_session)):
    from app.llm.inputs import InputError
    from app.llm.provider import LLMUnavailable
    from app.services.analysis import analyze

    try:
        return analyze(session, iid, refresh=refresh)
    except InputError as e:
        raise HTTPException(422, str(e)) from None
    except LLMUnavailable as e:
        session.commit()  # keep the call log even when the provider failed
        raise HTTPException(409, str(e)) from None


@router.get("/analysis/{iid}/preview")
def analysis_preview(iid: int, session: Session = Depends(get_session)):
    from app.llm.inputs import InputError
    from app.services.analysis import preview

    try:
        return preview(session, iid)
    except InputError as e:
        raise HTTPException(422, str(e)) from None


@router.get("/analysis/{iid}/sent/{aid}")
def analysis_sent(iid: int, aid: int, session: Session = Depends(get_session)):
    from app.llm.prompts import SYSTEM_PROMPT
    from app.models import LlmAnalysis

    a = session.get(LlmAnalysis, aid)
    if a is None or a.instrument_id != iid:
        raise HTTPException(404, "analysis not found")
    note = None if a.prompt_version else "prompt version unknown"
    return {"model": a.model, "prompt_version": a.prompt_version, "system": SYSTEM_PROMPT, "input": a.input_json,
            "note": note}


@router.post("/news/suggest-categories")
def news_suggest(session: Session = Depends(get_session)):
    from app.llm.provider import LLMUnavailable
    from app.services.analysis import suggest_categories

    try:
        return suggest_categories(session)
    except LLMUnavailable as e:
        raise HTTPException(409, str(e)) from None


@router.get("/llm/status")
def llm_status(session: Session = Depends(get_session)):
    from app.services.analysis import gate, usage

    return {"gate": gate(session), "usage": usage(session)}


@router.get("/journal")
def journal_page(session: Session = Depends(get_session)):
    from app.services.journal import journal

    return journal(session)


class ThesisIn(BaseModel):
    why: str
    change_view: str
    horizon: str
    review_date: str | None = None
    linked_txn_ids: list[int] = []
    linked_change_ids: list[int] = []


@router.post("/journal/{iid}", status_code=201)
def journal_add(iid: int, body: ThesisIn, session: Session = Depends(get_session)):
    from datetime import date as _date

    from app.services.journal import JournalError, add_entry

    try:
        rd = _date.fromisoformat(body.review_date) if body.review_date else None
    except ValueError:
        raise HTTPException(422, "review_date must be YYYY-MM-DD") from None
    try:
        return add_entry(session, iid, body.why, body.change_view, body.horizon, rd, body.linked_txn_ids,
                         body.linked_change_ids)
    except JournalError as e:
        raise HTTPException(422, str(e)) from None


@router.get("/journal/{iid}/history")
def journal_history(iid: int, session: Session = Depends(get_session)):
    from app.services.journal import history

    return history(session, iid)


class OptIn(BaseModel):
    send_to_llm: bool


@router.put("/journal/{iid}/optin")
def journal_optin(iid: int, body: OptIn, session: Session = Depends(get_session)):
    from app.services.journal import set_optin

    set_optin(session, iid, body.send_to_llm)
    return {"ok": True}


@router.get("/strategy")
def strategy_view(since: str, session: Session = Depends(get_session)):
    from datetime import date as _date

    from app.services.journal import strategy

    try:
        d = _date.fromisoformat(since)
    except ValueError:
        raise HTTPException(422, "since must be YYYY-MM-DD") from None
    return strategy(session, d)


@router.get("/broker/status")
def broker_status():
    from app.services.broker import status

    return status()


class TotpIn(BaseModel):
    totp: str | None = None


@router.post("/broker/groww/token")
def broker_token(body: TotpIn):
    from app.brokers.base import BrokerError
    from app.services.broker import groww_adapter

    try:
        exp = groww_adapter().login(body.totp or None)
    except BrokerError as e:
        raise HTTPException(409, str(e)) from None
    return {"ok": True, "expiry": exp.isoformat() if exp else None}


@router.get("/reconcile")
def reconcile_view(session: Session = Depends(get_session)):
    from app.brokers.base import BrokerError
    from app.services.broker import groww_adapter, reconcile_with

    try:
        adapter = groww_adapter()
    except BrokerError as e:
        return {"ok": False, "error": str(e), "differences": [], "not_compared": []}
    return reconcile_with(session, adapter)


@router.get("/alerts")
def alerts_list(unread_only: bool = False, session: Session = Depends(get_session)):
    from app.services.alerts import list_alerts

    return list_alerts(session, unread_only)


@router.post("/alerts/evaluate")
def alerts_evaluate(session: Session = Depends(get_session)):
    from app.services.alerts import evaluate_alerts

    return evaluate_alerts(session)


@router.post("/alerts/{aid}/read")
def alerts_read(aid: int, session: Session = Depends(get_session)):
    from app.services.alerts import mark_read

    try:
        mark_read(session, aid)
    except KeyError:
        raise HTTPException(404, "alert not found") from None
    return {"ok": True}
