""""Confirm all exact matches": which proposed identifiers are safe to confirm in one go, and which need a person.

Safe (applied):
- ISIN for a stock/ETF: exactly one pending candidate, from an EXACT NSE symbol match (score 1.0).
- AMFI scheme code for a fund: the best pending candidate scores >= HIGH_SCORE and leads the runner-up by at least
  MIN_MARGIN (candidates already share the fund's plan and option; see matching.scheme_matches).
Everything else (several close candidates, a lower score, a non-exact match) is left for manual review, with the
reason. Proposals are still never applied without the person asking: the list is shown first.
"""

from __future__ import annotations

HIGH_SCORE = 0.90
MIN_MARGIN = 0.15


def plan(instruments: list[dict]) -> dict:
    """instruments: [{instrument_id, name, needed_kind, confirmed: bool, candidates: [{id, kind, value, label, score,
    status, details}]}] -> {"apply": [...], "manual": [...]} (pure)."""
    apply, manual = [], []
    for i in instruments:
        if i["confirmed"]:
            continue
        pend = sorted([c for c in i["candidates"] if c["kind"] == i["needed_kind"] and c["status"] == "PENDING"],
                      key=lambda c: -c["score"])
        base = {"instrument_id": i["instrument_id"], "name": i["name"], "kind": i["needed_kind"]}
        if not pend:
            manual.append({**base, "reason": "no proposed match yet"})
            continue
        top = pend[0]
        if i["needed_kind"] == "ISIN":
            if len(pend) == 1 and top["score"] >= 1.0 and (top.get("details") or {}).get("exact_symbol_match"):
                apply.append({**base, "candidate_id": top["id"], "value": top["value"], "label": top["label"],
                              "score": top["score"], "why": "exact NSE symbol match"})
            else:
                manual.append({**base, "reason": f"{len(pend)} candidates" if len(pend) > 1 else "not an exact symbol match"})
            continue
        runner = pend[1]["score"] if len(pend) > 1 else None
        if top["score"] >= HIGH_SCORE and (runner is None or top["score"] - runner >= MIN_MARGIN):
            why = f"score {top['score']:.2f}" + (f", next best {runner:.2f}" if runner is not None else ", only candidate")
            apply.append({**base, "candidate_id": top["id"], "value": top["value"], "label": top["label"],
                          "score": top["score"], "why": why})
        elif top["score"] < HIGH_SCORE:
            manual.append({**base, "reason": f"best score {top['score']:.2f} is below {HIGH_SCORE:.2f}"})
        else:
            manual.append({**base, "reason": f"ambiguous: {top['score']:.2f} vs {runner:.2f}"})
    return {"apply": apply, "manual": manual, "rules": {"high_score": HIGH_SCORE, "min_margin": MIN_MARGIN}}
