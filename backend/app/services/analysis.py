"""Per-holding AI scenario analysis: gate (privacy toggle, key, cap), cache by input hash, guardrails."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import repository as repo
from app.llm import prompts
from app.llm.inputs import InputError, build_fund_input, build_input, build_portfolio_input, data_as_of, input_hash
from app.llm.provider import AnthropicProvider, LLMProvider, LLMUnavailable
from app.llm.validate import validate
from app.models import LlmAnalysis, LlmCall, NewsItem
from app.services import settings as st
from app.logging_config import event
from app.timeutil import IST, as_utc, today_ist, utcnow

log = logging.getLogger("app.llm")

MAX_ATTEMPTS = 2


def month_start_utc(now: datetime | None = None) -> datetime:
    n = (now or utcnow()).astimezone(IST)
    return n.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _user(s: Session):
    from app.models import User

    uid = s.info.get("user_id")
    return s.get(User, uid) if uid is not None else None


def global_calls_this_month() -> int:
    """Calls on the platform key this month, across all users (for the global cap)."""
    from app.db import session_scope

    with session_scope(system=True) as sys_s:
        return sys_s.scalar(select(func.count()).select_from(LlmCall).where(
            LlmCall.created_at >= month_start_utc(), LlmCall.own_key.is_(False))) or 0


def usage(s: Session) -> dict:
    """This user's AI usage this month. Caps: the user's own Settings cap, the admin's per-user cap and (for
    calls on the platform key) the global cap."""
    cfg = st.get(s, "llm")
    plat = st.get(s, "llm_platform")
    user = _user(s)
    q = select(func.count(), func.coalesce(func.sum(LlmCall.input_tokens), 0),
               func.coalesce(func.sum(LlmCall.output_tokens), 0)).where(LlmCall.created_at >= month_start_utc())
    calls, tin, tout = s.execute(q).one()
    pin, pout = plat.get("price_in_per_mtok"), plat.get("price_out_per_mtok")
    if pin is None or pout is None:
        cost, note = None, f"Token prices are not set (admin: Settings › AI platform). {st.PRICING_NOTE}"
    else:
        cost = str(((Decimal(tin) * Decimal(pin) + Decimal(tout) * Decimal(pout)) / 1_000_000).quantize(Decimal("0.0001")))
        note = f"Estimate = tokens × ${pin}/M input + ${pout}/M output (platform settings). {st.PRICING_NOTE}"
    admin_cap = user.ai_monthly_cap if user is not None else cfg["monthly_call_cap"]
    return {"calls_this_month": calls, "cap": min(cfg["monthly_call_cap"], admin_cap), "your_cap": cfg["monthly_call_cap"],
            "admin_cap": admin_cap, "input_tokens": tin, "output_tokens": tout,
            "estimated_cost_usd": cost, "pricing_note": note,
            "ai_enabled_by_admin": bool(user and (user.ai_enabled or user.role == "admin")),
            "own_key": bool(user and user.own_key_encrypted)}


def _api_key(s: Session) -> tuple[str | None, bool]:
    """(key, is_own): the user's own key if stored, else the platform key. Never logged or returned."""
    from app.config import get_settings

    user = _user(s)
    if user is not None and user.own_key_encrypted:
        from app.crypto import decrypt

        return decrypt(user.own_key_encrypted), True
    return get_settings().anthropic_api_key or None, False


def gate(s: Session) -> str | None:
    """Reason the LLM can't be called for this user, or None."""
    from app.services import ops

    if ops.switches(s)["ai_off"]:
        return ops.MESSAGES["ai_off"]
    cfg = st.get(s, "llm")
    user = _user(s)
    if user is not None and not (user.ai_enabled or user.role == "admin"):
        return "AI analysis is not enabled for your account (ask the admin)."
    if not cfg["outbound_enabled"]:
        return "Privacy toggle is off: outbound LLM calls are disabled (Settings › AI analysis)."
    try:
        key, own = _api_key(s)
    except Exception as e:  # stored key unreadable
        return str(e)
    if not key:
        return "No AI key configured on the server: AI analysis is disabled."
    u = usage(s)
    if u["calls_this_month"] >= u["cap"]:
        return f"Monthly call cap reached ({u['calls_this_month']}/{u['cap']})."
    if not own:
        g = global_calls_this_month()
        cap = st.get(s, "llm_platform")["global_monthly_cap"]
        if g >= cap:
            return f"The app's monthly AI budget is used up ({g}/{cap}); it resets on the 1st."
    return None


def default_provider(s: Session) -> LLMProvider:
    cfg = st.get(s, "llm")
    key, _own = _api_key(s)
    return AnthropicProvider(model=st.llm_model(s), effort=cfg["effort"], api_key=key,
                             refusal_fallback=cfg.get("refusal_fallback", False))


def test_connection(s: Session, model: str | None = None, api_key: str | None = None) -> dict:
    """Settings › Test connection. Sends a fixed ping (no portfolio data) even when the privacy toggle is off,
    because it carries nothing about you; it is logged like any call. Validates the model id for real."""

    from app.llm.provider import PING_PROMPT, AnthropicProvider, LLMUnavailable

    cfg = st.get(s, "llm")
    requested = (model or "").strip() or st.llm_model(s)
    fallback = bool(cfg.get("refusal_fallback", False))
    out = {"ok": False, "requested_model": requested, "model": None, "fallback_used": False,
           "refusal_fallback": fallback, "sent": PING_PROMPT, "input_tokens": 0, "output_tokens": 0,
           "latency_ms": None, "error": None, "reply": None}
    try:
        from app.services import ops

        if ops.switches(s)["ai_off"]:
            raise LLMUnavailable(ops.MESSAGES["ai_off"])
        user = _user(s)
        if user is not None and not (user.ai_enabled or user.role == "admin"):
            raise LLMUnavailable("AI analysis is not enabled for your account (ask the admin).")
        provider = AnthropicProvider(model=requested, effort=cfg["effort"], api_key=api_key or _api_key(s)[0],
                                     refusal_fallback=fallback)
    except LLMUnavailable as e:
        out["error"] = str(e)
        return out
    t0 = time.monotonic()
    try:
        p = provider.ping()
    except LLMUnavailable as e:
        out["latency_ms"] = round((time.monotonic() - t0) * 1000)
        out["error"] = str(e)
        event(log, "llm_connection_test", logging.WARNING, requested_model=requested, outcome="error",
              error=str(e)[:300], latency_ms=out["latency_ms"], refusal_fallback=fallback)
        _log(s, "connection test", requested, False, error=str(e))
        return out
    out.update(ok=True, model=p.model, fallback_used=p.model != requested, input_tokens=p.input_tokens,
               output_tokens=p.output_tokens, latency_ms=round((time.monotonic() - t0) * 1000), reply=p.text[:40],
               stop_reason=p.stop_reason)
    _log(s, "connection test", p.model, True, p.input_tokens, p.output_tokens)
    event(log, "llm_connection_test", requested_model=requested, model=p.model, outcome="ok",
          input_tokens=p.input_tokens, output_tokens=p.output_tokens, latency_ms=out["latency_ms"],
          refusal_fallback=fallback)
    return out


def _log(s: Session, purpose: str, model: str, ok: bool, tin: int = 0, tout: int = 0, error: str | None = None) -> None:
    from app.services.source_health import record

    try:
        own = _api_key(s)[1]
    except Exception:
        own = False
    s.add(LlmCall(purpose=purpose, model=model, ok=ok, input_tokens=tin, output_tokens=tout, error=error, own_key=own))
    s.flush()
    provider_ok = ok or (error is not None and not error.startswith(("Could not reach", "Anthropic API error",
                                                                      "Rate limited", "The Anthropic API key")))
    record(s, "LLM provider", provider_ok, f"{purpose} via {model}" + (f": {error[:300]}" if error else ""))


def _latest(s: Session, iid: int | None, kind: str = "stock") -> LlmAnalysis | None:
    q = select(LlmAnalysis).where(LlmAnalysis.kind == kind)
    q = q.where(LlmAnalysis.instrument_id.is_(None)) if iid is None else q.where(LlmAnalysis.instrument_id == iid)
    return s.scalar(q.order_by(LlmAnalysis.id.desc()).limit(1))


def card(a: LlmAnalysis | None, current_hash: str | None = None) -> dict | None:
    if a is None:
        return None
    out = {"id": a.id, "kind": a.kind, "status": a.status, "model": a.model, "requested_model": a.requested_model,
           "fallback_used": bool(a.requested_model and a.requested_model != a.model),
           "prompt_version": a.prompt_version,
           "created_at": as_utc(a.created_at).isoformat(), "data_as_of": a.data_as_of.isoformat() if a.data_as_of else None,
           "attempts": a.attempts, "input_tokens": a.input_tokens, "output_tokens": a.output_tokens,
           "stale": current_hash is not None and a.input_hash != current_hash, "errors": a.errors if a.status != "OK" else []}
    if a.status == "OK":
        o = a.output_json
        spec = prompts.KINDS[a.kind or "stock"]
        out["analysis"] = {k: o[k] for k in spec["sections"]}
        if spec["scenarios"]:
            out["analysis"]["scenarios"] = [{**x, "sentence": prompts.render_scenario(x)} for x in o["scenarios"]]
    return out


def _run(s: Session, kind: str, iid: int | None, inp: dict, refresh: bool, provider: LLMProvider | None) -> dict:
    spec = prompts.KINDS[kind]
    model = provider.model if provider else st.llm_model(s)
    h = input_hash({"kind": kind, **inp}, model, prompts.PROMPT_VERSION)
    q = select(LlmAnalysis).where(LlmAnalysis.kind == kind, LlmAnalysis.input_hash == h)
    q = q.where(LlmAnalysis.instrument_id.is_(None)) if iid is None else q.where(LlmAnalysis.instrument_id == iid)
    cached = s.scalar(q.order_by(LlmAnalysis.id.desc()).limit(1))
    if cached and not refresh:
        event(log, "llm_call", kind=kind, instrument_id=iid, model=model, input_hash=h[:16], outcome="cache_hit")
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
        t0 = time.perf_counter()
        # logged: ids, hash, counts, latency, outcome, validator reasons; never the prompt or input text
        base = {"kind": kind, "instrument_id": iid, "requested_model": provider.model, "input_hash": h[:16],
                "attempt": attempts}
        try:
            c = provider.complete_json(spec["system"], messages, spec["schema"])
        except LLMUnavailable as e:
            event(log, "llm_call", logging.WARNING, **base, outcome="provider_error", error=str(e)[:300],
                  latency_ms=round((time.perf_counter() - t0) * 1000))
            _log(s, kind, provider.model, False, error=str(e))
            errors = [str(e)]
            break
        tin, tout, served = tin + c.input_tokens, tout + c.output_tokens, c.model
        data, errors = validate(c.text, inp, kind)
        event(log, "llm_call", logging.INFO if data is not None else logging.WARNING, **base, model=c.model,
              input_tokens=c.input_tokens, output_tokens=c.output_tokens,
              latency_ms=round((time.perf_counter() - t0) * 1000), outcome="ok" if data is not None else "rejected",
              rejection_reasons=[e[:200] for e in errors][:10])
        _log(s, kind, c.model, data is not None, c.input_tokens, c.output_tokens,
             None if data else "; ".join(errors)[:2000])
        if data is not None:
            break
        messages = messages + [{"role": "assistant", "content": c.text},
                               {"role": "user", "content": "Your JSON failed validation:\n- " + "\n- ".join(errors)
                                + "\nReturn corrected JSON that follows every rule."}]
    a = LlmAnalysis(kind=kind, instrument_id=iid, input_hash=h, input_json=inp, output_json=data,
                    status="OK" if data else "FAILED", errors=errors if not data else [], model=served,
                    requested_model=provider.model, prompt_version=prompts.PROMPT_VERSION, data_as_of=data_as_of(inp),
                    attempts=attempts, input_tokens=tin, output_tokens=tout)
    s.add(a)
    s.flush()
    return {"cached": False, "card": card(a, h)}


def analyze(s: Session, iid: int, refresh: bool = False, provider: LLMProvider | None = None, today=None) -> dict:
    return _run(s, "stock", iid, build_input(s, iid, today or today_ist()), refresh, provider)


def analyze_fund(s: Session, iid: int, refresh: bool = False, provider: LLMProvider | None = None, today=None) -> dict:
    return _run(s, "fund", iid, build_fund_input(s, iid, today or today_ist()), refresh, provider)


def analyze_portfolio(s: Session, refresh: bool = False, provider: LLMProvider | None = None, today=None) -> dict:
    return _run(s, "portfolio", None, build_portfolio_input(s, today or today_ist()), refresh, provider)


def _builder(kind: str):
    return {"stock": lambda s, iid: build_input(s, iid, today_ist()),
            "fund": lambda s, iid: build_fund_input(s, iid, today_ist()),
            "portfolio": lambda s, iid: build_portfolio_input(s, today_ist())}[kind]


def preview(s: Session, iid: int | None, kind: str = "stock") -> dict:
    """Exactly what would be sent (system prompt + input), without calling anything."""
    inp = _builder(kind)(s, iid)
    model = st.llm_model(s)
    return {"kind": kind, "model": model, "prompt_version": prompts.PROMPT_VERSION, "system": prompts.KINDS[kind]["system"],
            "input": inp, "output_schema": prompts.KINDS[kind]["schema"],
            "input_hash": input_hash({"kind": kind, **inp}, model, prompts.PROMPT_VERSION)}


def _hash_now(s: Session, kind: str, iid: int | None) -> str | None:
    try:
        return input_hash({"kind": kind, **_builder(kind)(s, iid)}, st.llm_model(s), prompts.PROMPT_VERSION)
    except InputError:
        return None


def cards(s: Session) -> dict:
    from app.services.portfolio import load_rows

    rows, _ = load_rows(s)
    cfg = st.get(s, "llm")
    out, funds = [], []
    for r in rows:
        if r.inst.asset_type == "STOCK":
            out.append({"instrument_id": r.inst.id, "symbol": r.inst.symbol, "name": r.inst.name,
                        "card": card(_latest(s, r.inst.id, "stock"), _hash_now(s, "stock", r.inst.id))})
        elif r.inst.asset_type == "MF":
            funds.append({"instrument_id": r.inst.id, "symbol": None, "name": r.inst.name,
                          "card": card(_latest(s, r.inst.id, "fund"), _hash_now(s, "fund", r.inst.id))})
    portfolio = {"card": card(_latest(s, None, "portfolio"), _hash_now(s, "portfolio", None))}
    return {"holdings": out, "funds": funds, "portfolio": portfolio, "gate": gate(s), "settings": {**{k: cfg.get(k) for k in (
                "outbound_enabled", "effort", "monthly_call_cap", "weekly_job", "refusal_fallback")}, "model": st.llm_model(s)},
            "usage": usage(s), "funds_note": "Stock cards for direct stocks; fund cards for mutual funds; one optional portfolio summary."}


def suggest_categories(s: Session, provider: LLMProvider | None = None, limit: int = 20) -> dict:
    """Ask the LLM to suggest categories ONLY for items the rules left as 'other'. Only headlines are sent."""
    from app.calc.news import CATEGORIES

    from app.services.news import tracked_companies

    mine = [t.isin for t in tracked_companies(s)[0]]  # news is shared: only headlines about this user's companies
    items = list(s.scalars(select(NewsItem).where(NewsItem.category == "other", NewsItem.category_origin == "RULE",
                                                  NewsItem.isin.in_(mine or ["-"]))
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
