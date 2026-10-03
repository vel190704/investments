"""Pure matching logic: fund name -> ranked AMFI candidates. Never auto-applied."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.resolve.sources import AmfiScheme

GROWTH_WORDS = {"growth", "cumulative"}
NOISE = {"fund", "plan", "option", "direct", "regular", "growth", "cumulative", "idcw", "dividend", "the", "scheme"}


def _tokens(s: str) -> list[str]:
    s = s.lower().replace("midcap", "mid cap").replace("smallcap", "small cap").replace("largecap", "large cap")
    return re.findall(r"[a-z0-9]+", s)


def detect_plan(name: str) -> str | None:
    t = set(_tokens(name))
    return "direct" if "direct" in t else "regular" if "regular" in t else None


def detect_option(name: str) -> str | None:
    t = set(_tokens(name))
    if t & GROWTH_WORDS:
        return "growth"
    if t & {"idcw", "dividend"}:
        return "idcw"
    return None


def core(name: str) -> str:
    return " ".join(w for w in _tokens(name) if w not in NOISE)


def scheme_matches(name: str, schemes: dict[str, AmfiScheme], limit: int = 5) -> list[tuple[AmfiScheme, float]]:
    plan, option = detect_plan(name), detect_option(name)
    want = core(name)
    want_set = set(want.split())
    scored = []
    for s in schemes.values():
        full = s.name
        s_plan, s_opt = detect_plan(full), detect_option(full)
        if plan and s_plan != plan:
            continue
        if option and s_opt != option:
            continue
        have = core(s.base_name or full)
        have_set = set(have.split())
        if not want_set & have_set:
            continue
        jacc = len(want_set & have_set) / len(want_set | have_set)
        ratio = SequenceMatcher(None, want, have).ratio()
        score = round(0.6 * jacc + 0.4 * ratio, 4)
        if score >= 0.5:
            scored.append((s, score))
    scored.sort(key=lambda x: (-x[1], x[0].name))
    return scored[:limit]
