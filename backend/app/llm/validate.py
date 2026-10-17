"""Hard guardrails for LLM output. Pure. An output that fails any check is never shown as analysis.

(a) every number in the output text must appear in the input;
(b) no recommendation / prediction wording;
(c) every statement cites at least one id, and every cited id exists in the input;
(d) the JSON matches the schema (structure, enums, no extra keys).
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation

from app.llm.prompts import DIRECTIONS, OUTPUT_SCHEMA, SCENARIOS, STATEMENT_SECTIONS

NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
BANNED = [
    (r"\bbuy\b|\bbuying opportunity\b", "buy"),
    (r"\bsell\b", "sell"),
    (r"\bhold\b", "hold"),
    (r"\baccumulat(e|ing|ion)\b", "accumulate"),
    (r"\b(reduce|trim|cut) (your|the|this) (position|holding|stake|exposure)\b", "reduce position"),
    (r"\bexit (the|your|this) (position|stock|holding|investment)\b", "exit position"),
    (r"\badd (more|to (your|the|this) (position|holding))\b", "add more"),
    (r"\btarget price\b|\bprice target\b", "target price"),
    (r"\bfair (value|price)\b", "fair value"),
    (r"\b(upside|downside) (of|to|potential)\b", "upside/downside figure"),
    (r"\bwill (rise|fall|increase|decrease|go up|go down|climb|drop|surge|plunge|rally|crash|outperform|"
     r"underperform|double|recover)\b", "will rise/fall"),
    (r"\b(price|share|stock)s? (is|are) (likely|expected|set) to (rise|fall|increase|decrease|climb|drop)\b",
     "price prediction"),
    (r"\bmultibagger\b", "multibagger"),
    (r"\bguarantee(d|s)?\b", "guarantee"),
    (r"\brecommend(s|ed|ation)?\b", "recommendation"),
]


def collect_ids(obj) -> set[str]:
    ids = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "id" and isinstance(v, str):
                ids.add(v)
            else:
                ids |= collect_ids(v)
    elif isinstance(obj, list):
        for v in obj:
            ids |= collect_ids(v)
    return ids


def _norm(num: str) -> str | None:
    t = num.replace(",", "")
    try:
        d = Decimal(t)
    except InvalidOperation:
        return None
    return format(d.normalize(), "f") if d != 0 else "0"


def numbers_in(text: str) -> set[str]:
    return {n for n in (_norm(m.group(0)) for m in NUMBER_RE.finditer(text)) if n is not None}


def input_numbers(obj) -> set[str]:
    """Numbers in input values (ids and keys excluded)."""
    out: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k != "id":
                out |= input_numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            out |= input_numbers(v)
    elif isinstance(obj, bool) or obj is None:
        pass
    elif isinstance(obj, (int, float)):
        out |= numbers_in(str(obj))
    else:
        out |= numbers_in(str(obj))
    return out


def _schema_errors(data) -> list[str]:
    errs = []
    if not isinstance(data, dict):
        return ["output is not a JSON object"]
    want = set(OUTPUT_SCHEMA["required"])
    extra, missing = set(data) - want, want - set(data)
    if extra:
        errs.append(f"unexpected keys: {sorted(extra)}")
    if missing:
        errs.append(f"missing keys: {sorted(missing)}")
    for sec in STATEMENT_SECTIONS:
        items = data.get(sec, [])
        if not isinstance(items, list):
            errs.append(f"{sec} must be a list")
            continue
        for i, it in enumerate(items):
            if not isinstance(it, dict) or set(it) != {"text", "citations"}:
                errs.append(f"{sec}[{i}] must have exactly text and citations")
            elif not isinstance(it["text"], str) or not it["text"].strip() or not isinstance(it["citations"], list):
                errs.append(f"{sec}[{i}] has an empty text or non-list citations")
    sc = data.get("scenarios", [])
    if not isinstance(sc, list):
        errs.append("scenarios must be a list")
    else:
        for i, it in enumerate(sc):
            if not isinstance(it, dict) or set(it) != {"scenario", "direction", "because", "citations"}:
                errs.append(f"scenarios[{i}] has the wrong fields")
                continue
            if it["scenario"] not in SCENARIOS:
                errs.append(f"scenarios[{i}].scenario {it['scenario']!r} is not allowed")
            if it["direction"] not in DIRECTIONS:
                errs.append(f"scenarios[{i}].direction {it['direction']!r} is not allowed")
            if not isinstance(it["because"], str) or not it["because"].strip():
                errs.append(f"scenarios[{i}].because is empty")
    return errs


def validate(output_text: str, input_obj: dict) -> tuple[dict | None, list[str]]:
    try:
        data = json.loads(output_text)
    except (json.JSONDecodeError, TypeError) as e:
        return None, [f"(d) not valid JSON: {e}"]
    errors = [f"(d) schema: {e}" for e in _schema_errors(data)]
    if errors:
        return None, errors

    ids = collect_ids(input_obj)
    allowed_numbers = input_numbers(input_obj)
    statements = [(f"{sec}[{i}]", it["text"], it["citations"]) for sec in STATEMENT_SECTIONS
                  for i, it in enumerate(data[sec])]
    statements += [(f"scenarios[{i}]", it["because"], it["citations"]) for i, it in enumerate(data["scenarios"])]
    for where, text, cites in statements:
        if not cites:
            errors.append(f"(c) {where} has no citation")
        unknown = [c for c in cites if c not in ids]
        if unknown:
            errors.append(f"(c) {where} cites ids not in the input: {unknown}")
        invented = sorted(numbers_in(text) - allowed_numbers)
        if invented:
            errors.append(f"(a) {where} contains numbers not in the input: {invented}")
        low = text.lower()
        for pattern, label in BANNED:
            if re.search(pattern, low):
                errors.append(f"(b) {where} contains banned wording: {label}")
    return (data if not errors else None), errors
