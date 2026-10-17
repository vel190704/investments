"""Portfolio exposure by sensitivity tag (code only; no LLM; not a forecast)."""

from __future__ import annotations

from decimal import Decimal

from app.money import format_pct

TAGS = ["rate-sensitive", "export/currency-exposed", "import/currency-exposed", "foreign-currency assets",
        "crude-input-exposed", "commodity-input-exposed", "regulation-exposed", "demand-cyclical"]
SCENARIOS = {
    "rate_cut": ("Rate cut", ["rate-sensitive"]),
    "rate_rise": ("Rate rise", ["rate-sensitive"]),
    "weaker_rupee": ("Weaker rupee", ["export/currency-exposed", "import/currency-exposed", "foreign-currency assets"]),
    "higher_crude": ("Higher crude oil", ["crude-input-exposed"]),
    "sector_regulation": ("Sector regulation", ["regulation-exposed"]),
    "demand_slowdown": ("Demand slowdown", ["demand-cyclical"]),
}
STARTER_LABEL = "Starter set: general sector characteristics — review and edit. Not facts about any company."
# Starter tags for NSE sector names (general characteristics only).
STARTER: dict[str, list[str]] = {
    "Financial Services": ["rate-sensitive", "regulation-exposed"],
    "Construction": ["rate-sensitive", "demand-cyclical", "commodity-input-exposed"],
    "Capital Goods": ["demand-cyclical", "rate-sensitive"],
    "Information Technology": ["export/currency-exposed", "demand-cyclical"],
    "Oil Gas & Consumable Fuels": ["crude-input-exposed", "regulation-exposed"],
    "Power": ["rate-sensitive", "regulation-exposed", "commodity-input-exposed"],
    "Healthcare": ["export/currency-exposed", "regulation-exposed"],
    "Telecommunication": ["regulation-exposed", "rate-sensitive"],
    "Fast Moving Consumer Goods": ["commodity-input-exposed", "demand-cyclical"],
    "Metals & Mining": ["demand-cyclical", "commodity-input-exposed", "export/currency-exposed"],
    "Automobile and Auto Components": ["demand-cyclical", "commodity-input-exposed", "rate-sensitive"],
    "Chemicals": ["crude-input-exposed", "export/currency-exposed"],
    "Realty": ["rate-sensitive", "demand-cyclical", "regulation-exposed"],
    "International equity — Hong Kong/China": ["foreign-currency assets", "regulation-exposed"],
    "International equity — US (technology-heavy)": ["foreign-currency assets"],
}


def exposure_by_tag(sector_rows: list[dict], sensitivities: dict[str, list[str]],
                    direct: list[tuple[str, str]]) -> list[dict]:
    """sector_rows: [{sector, pct}] (look-through, % of total portfolio);
    sensitivities: {sector: [tags]}; direct: [(holding name, sector)]."""
    out = []
    for key, (label, tags) in SCENARIOS.items():
        parts = []
        for tag in tags:
            secs = [r for r in sector_rows if tag in sensitivities.get(r["sector"], [])]
            share = sum((Decimal(r["pct"]) for r in secs), Decimal(0))
            parts.append({
                "tag": tag, "weight": str(share), "weight_text": format_pct(share),
                "sectors": [{"sector": r["sector"], "pct": r["pct"]} for r in sorted(secs, key=lambda r: -Decimal(r["pct"]))],
                "holdings": sorted({name for name, sec in direct if tag in sensitivities.get(sec, [])}),
            })
        out.append({"scenario": key, "label": label, "tags": parts})
    return out
