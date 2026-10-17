"""In-app alert rules (pure). Each alert has a dedupe key so it is created exactly once."""

from __future__ import annotations


def evaluate(rules: dict, news: list[dict], levels: dict[str, str | None], stale: list[dict], reviews: list[dict],
             state: dict, today: str) -> tuple[list[dict], dict]:
    """Returns (alerts to create, new state). `state["levels"]` holds the last seen level per dimension."""
    out: list[dict] = []
    if rules.get("announcement"):
        cats = set(rules.get("announcement_categories", []))
        for n in news:
            if n["category"] in cats and n.get("instrument_id"):
                out.append({"rule": "announcement", "key": f"news:{n['id']}", "instrument_id": n["instrument_id"],
                            "title": f"{n['company']}: {n['category']}", "detail": f"{n['title']} ({n['source']})"})
    prev = (state or {}).get("levels")
    if rules.get("concentration_change") and prev is not None:
        for dim, cur in levels.items():
            before = prev.get(dim)
            if cur and before and cur != before:
                out.append({"rule": "concentration_change", "key": f"level:{dim}:{before}->{cur}:{today}",
                            "instrument_id": None, "title": f"{dim.capitalize()} concentration: {before} → {cur}",
                            "detail": f"The {dim} concentration flag changed from {before} to {cur}. See Portfolio health."})
    if rules.get("disclosure_stale"):
        for d in stale:
            out.append({"rule": "disclosure_stale", "key": f"stale:{d['id']}", "instrument_id": d.get("instrument_id"),
                        "title": f"Stale holdings data: {d['fund']}",
                        "detail": f"The disclosure in use is as of {d['as_of']} (older than 2 months). Upload a newer one."})
    if rules.get("review_due"):
        for r in reviews:
            out.append({"rule": "review_due", "key": f"review:{r['id']}", "instrument_id": r["instrument_id"],
                        "title": f"Thesis review due: {r['name']}",
                        "detail": f"Version {r['version']} asked for a review on {r['review_date']}."})
    # the baseline is recorded on the first run, so the first evaluation never reports a "change"
    return out, {"levels": {k: v for k, v in levels.items() if v} | ({} if prev is None else
                                                                     {k: v for k, v in prev.items() if k not in levels})}
