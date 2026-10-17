"""Per-holding AI scenario analysis: gate (privacy toggle, key, cap), cache by input hash, guardrails."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import repository as repo
from app.llm import prompts
from app.llm.inputs import InputError, build_input, data_as_of, input_hash
from app.llm.provider import AnthropicProvider, LLMProvider, LLMUnavailable
from app.llm.validate import validate
from app.models import LlmAnalysis, LlmCall, NewsItem
from app.services import settings as st
from app.timeutil import IST, as_utc, today_ist, utcnow

MAX_ATTEMPTS = 2


def month_start_utc(now: datetime | None = None) -> datetime:
    n = (now or utcnow()).astimezone(IST)
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def usage(s: Session) -> dict:
    cfg = st.get(s, "llm")
    q = select(func.count(), func.coalesce(func.sum(LlmCall.input_tokens), 0),
               func.coalesce(func.sum(LlmCall.output_tokens), 0)).where(LlmCall.created_at >= month_start_utc())
    calls, tin, tout = s.execute(q).one()
    cost = (Decimal(tin) * Decimal(cfg["price_in_per_mtok"]) + Decimal(tout) * Decimal(cfg["price_out_per_mtok"])) / 1_000_000
    return {"calls_this_month": calls, "cap": cfg["monthly_call_cap"], "input_tokens": tin, "output_tokens": tout,
            "estimated_cost_usd": str(cost.quantize(Decimal("0.0001"))),
            "pricing_note": f"Estimate = tokens × ${cfg['price_in_per_mtok']}/M input + ${cfg['price_out_per_mtok']}/M "
                            "output (edit in Settings); actual billing may differ."}


def gate(s: Session) -> str | None:
    """Reason the LLM can't be called, or None."""
    from app.config import get_settings

    cfg = st.get(s, "llm")
    if not cfg["outbound_enabled"]:
        return "Privacy toggle is off: outbound LLM calls are disabled (Settings › AI analysis)."
    if not get_settings().anthropic_api_key:
        return "No ANTHROPIC_API_KEY in .env: AI analysis is disabled."
    u = usage(s)
    if u["calls_this_month"] >= u["cap"]:
        return f"Monthly call cap reached ({u['calls_this_month']}/{u['cap']}); raise it in Settings or wait."
    return None


def default_provider(s: Session) -> LLMProvider:
    cfg = st.get(s, "llm")
    return AnthropicProvider(model=cfg["model"], effort=cfg["effort"])


def _log(s: Session, purpose: str, model: str, ok: bool, tin: int = 0, tout: int = 0, error: str | None = None) -> None:
    s.add(LlmCall(purpose=purpose, model=model, ok=ok, input_tokens=tin, output_tokens=tout, error=error))
    s.flush()


def _latest(s: Session, iid: int) -> LlmAnalysis | None:
    return s.scalar(select(LlmAnalysis).where(LlmAnalysis.instrument_id == iid).order_by(LlmAnalysis.id.desc()).limit(1))


def card(a: LlmAnalysis | None, current_hash: str | None = None) -> dict | None:
    if a is None:
        return None
    out = {"id": a.id, "status": a.status, "model": a.model, "prompt_version": a.prompt_version,
           "created_at": as_utc(a.created_at).isoformat(), "data_as_of": a.data_as_of.isoformat() if a.data_as_of else None,
           "attempts": a.attempts, "input_tokens": a.input_tokens, "output_tokens": a.output_tokens,
           "stale": current_hash is not None and a.input_hash != current_hash, "errors": a.errors if a.status != "OK" else []}
    if a.status == "OK":
        o = a.output_json
        out["analysis"] = {**{k: o[k] for k in prompts.STATEMENT_SECTIONS},
                           "scenarios": [{**x, "sentence": prompts.render_scenario(x)} for x in o["scenarios"]]}
    return out


def analyze(s: Session, iid: int, refresh: bool = False, provider: LLMProvider | None = None,
            today=None) -> dict:
    today = today or today_ist()
    cfg = st.get(s, "llm")
    inp = build_input(s, iid, today)
    model = provider.model if provider else cfg["model"]
    h = input_hash(inp, model, prompts.PROMPT_VERSION)
    cached = s.scalar(select(LlmAnalysis).where(LlmAnalysis.instrument_id == iid, LlmAnalysis.input_hash == h)
                      .order_by(LlmAnalysis.id.desc()).limit(1))
    if cached and not refresh:
        return {"cached": True, "card": card(cached, h)}
    reason = gate(s)
    if reason:
        raise LLMUnavailable(reason)
    provider = provider or default_provider(s)

    messages = [{"role": "user", "content": json.dumps(inp, ensure_ascii=False, indent=1)}]
    errors: list[str] = []
    tin = tout = 0
    served = provider.model
    data = None
    attempts = 0
    for attempts in range(1, MAX_ATTEMPTS + 1):
        if attempts > 1 and gate(s):
            break  # the cap may be hit between attempts
        try:
            c = provider.complete_json(prompts.SYSTEM_PROMPT, messages, prompts.OUTPUT_SCHEMA)
        except LLMUnavailable as e:
            _log(s, "analysis", provider.model, False, error=str(e))
            errors = [str(e)]
            break
        tin, tout, served = tin + c.input_tokens, tout + c.output_tokens, c.model
        data, errors = validate(c.text, inp)
        _log(s, "analysis", c.model, data is not None, c.input_tokens, c.output_tokens,
             None if data else "; ".join(errors)[:2000])
        if data is not None:
            break
        messages = messages + [{"role": "assistant", "content": c.text},
                               {"role": "user", "content": "Your JSON failed validation:\n- " + "\n- ".join(errors)
                                + "\nReturn corrected JSON that follows every rule."}]
    a = LlmAnalysis(instrument_id=iid, input_hash=h, input_json=inp, output_json=data, status="OK" if data else "FAILED",
                    errors=errors if not data else [], model=served, prompt_version=prompts.PROMPT_VERSION,
                    data_as_of=data_as_of(inp), attempts=attempts, input_tokens=tin, output_tokens=tout)
    s.add(a)
    s.flush()
    return {"cached": False, "card": card(a, h)}


def preview(s: Session, iid: int) -> dict:
    """Exactly what would be sent (system prompt + input), without calling anything."""
    cfg = st.get(s, "llm")
    inp = build_input(s, iid, today_ist())
    return {"model": cfg["model"], "prompt_version": prompts.PROMPT_VERSION, "system": prompts.SYSTEM_PROMPT,
            "input": inp, "output_schema": prompts.OUTPUT_SCHEMA,
            "input_hash": input_hash(inp, cfg["model"], prompts.PROMPT_VERSION)}


def cards(s: Session) -> dict:
    from app.services.portfolio import load_rows

    rows, _ = load_rows(s)
    cfg = st.get(s, "llm")
    out = []
    for r in rows:
        if r.inst.asset_type != "STOCK":
            continue
        try:
            h = input_hash(build_input(s, r.inst.id, today_ist()), cfg["model"], prompts.PROMPT_VERSION)
        except InputError:
            h = None
        latest = _latest(s, r.inst.id)
        out.append({"instrument_id": r.inst.id, "symbol": r.inst.symbol, "name": r.inst.name,
                    "card": card(latest, h)})
    return {"holdings": out, "gate": gate(s), "settings": {k: cfg[k] for k in ("outbound_enabled", "model", "effort",
                                                                           "monthly_call_cap", "weekly_job")},
            "usage": usage(s), "funds_note": "AI analysis covers direct stocks only."}


def suggest_categories(s: Session, provider: LLMProvider | None = None, limit: int = 20) -> dict:
    """Ask the LLM to suggest categories ONLY for items the rules left as 'other'. Only headlines are sent."""
    from app.calc.news import CATEGORIES

    items = list(s.scalars(select(NewsItem).where(NewsItem.category == "other", NewsItem.category_origin == "RULE")
                           .order_by(NewsItem.published_at.desc()).limit(limit)))
    if not items:
        return {"suggested": 0}
    reason = gate(s)
    if reason:
        raise LLMUnavailable(reason)
    provider = provider or default_provider(s)
    schema = {"type": "object", "properties": {"suggestions": {"type": "array", "items": {
        "type": "object", "properties": {"id": {"type": "string"}, "category": {"type": "string", "enum": CATEGORIES}},
        "required": ["id", "category"], "additionalProperties": False}}},
        "required": ["suggestions"], "additionalProperties": False}
    payload = {"allowed_categories": CATEGORIES, "headlines": [{"id": str(n.id), "headline": n.title} for n in items]}
    try:
        c = provider.complete_json(prompts.CATEGORY_SYSTEM, [{"role": "user", "content": json.dumps(payload)}], schema, 2000)
    except LLMUnavailable as e:
        _log(s, "category", provider.model, False, error=str(e))
        raise
    _log(s, "category", c.model, True, c.input_tokens, c.output_tokens)
    by_id = {str(n.id): n for n in items}
    n_set = 0
    try:
        suggestions = json.loads(c.text).get("suggestions", [])
    except json.JSONDecodeError:
        suggestions = []
    for sgg in suggestions:
        n = by_id.get(str(sgg.get("id")))
        if n and sgg.get("category") in CATEGORIES and sgg["category"] != "other":
            n.category, n.category_origin = sgg["category"], "MODEL"
            n_set += 1
    s.flush()
    return {"suggested": n_set}


def weekly_job(s: Session, provider: LLMProvider | None = None) -> dict:
    """Opt-in: refresh analyses only for holdings with news newer than their last analysis (within the cap)."""
    cfg = st.get(s, "llm")
    if not cfg["weekly_job"] or gate(s):
        return {"ran": 0, "skipped": gate(s) or "weekly job disabled"}
    ran = 0
    for r in repo.all_instruments(s):
        if r.asset_type != "STOCK" or not r.isin:
            continue
        last = _latest(s, r.id)
        newest = s.scalar(select(func.max(NewsItem.fetched_at)).where(NewsItem.isin == r.isin))
        if newest and (last is None or as_utc(newest) > as_utc(last.created_at)):
            try:
                analyze(s, r.id, provider=provider)
                ran += 1
            except (LLMUnavailable, InputError):
                break
    return {"ran": ran}
