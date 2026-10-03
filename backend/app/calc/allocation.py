"""Asset-class allocation and weights. Weight = current market value / total value."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

ASSET_CLASS_MF = "Mutual funds"
ASSET_CLASS_STOCKS = "Indian stocks"
ASSET_CLASS_INTL_ETF = "International ETFs"
ASSET_CLASS_IN_ETF = "Indian ETFs"
ASSET_CLASS_GOLD = "Gold"
ASSET_CLASS_DEBT = "Debt/Cash"
ASSET_CLASS_OTHER_COMMODITY = "Other commodities"
ASSET_CLASS_ORDER = [ASSET_CLASS_MF, ASSET_CLASS_STOCKS, ASSET_CLASS_INTL_ETF, ASSET_CLASS_IN_ETF, ASSET_CLASS_GOLD,
                     ASSET_CLASS_DEBT, ASSET_CLASS_OTHER_COMMODITY]
OVERRIDABLE_CLASSES = [ASSET_CLASS_MF, ASSET_CLASS_STOCKS, ASSET_CLASS_INTL_ETF, ASSET_CLASS_IN_ETF, ASSET_CLASS_GOLD,
                       ASSET_CLASS_DEBT, ASSET_CLASS_OTHER_COMMODITY]

# Region of global indices named in NSE's ETF list (Underlying Asset). Unknown -> not classified.
GLOBAL_INDEX_REGION = {
    "hang seng": "Hong Kong/China",
    "nyse fang+": "US (technology-heavy)",
    "nasdaq": "US (technology-heavy)",
    "s&p 500": "US",
}

# Per the spec; corroborated by NSE's ETF list ("GLOBAL INDICES" underlying).
INTERNATIONAL_ETF_SYMBOLS = frozenset({"MAFANG", "HNGSNGBEES"})


def classify(asset_type: str, exposure: str, override: str | None = None, etf_underlying: str | None = None,
             etf_underlying_key: str | None = None) -> str:
    """Effective asset class: manual override > ETF by NSE underlying > Phase 1 rule."""
    if override:
        return override
    if asset_type == "ETF" and etf_underlying:
        u, k = etf_underlying.upper(), (etf_underlying_key or "").upper()
        if u == "COMMODITY":
            return ASSET_CLASS_GOLD if k == "GOLD" else ASSET_CLASS_OTHER_COMMODITY
        if u == "DEBT":
            return ASSET_CLASS_DEBT
        if u == "GLOBAL INDICES":
            return ASSET_CLASS_INTL_ETF
        if u == "EQUITY":
            return ASSET_CLASS_INTL_ETF if exposure == "INTERNATIONAL" else ASSET_CLASS_IN_ETF
    return asset_class_of(asset_type, exposure)


def region_for_global_index(underlying_asset: str | None) -> str:
    n = (underlying_asset or "").lower()
    for needle, region in GLOBAL_INDEX_REGION.items():
        if needle in n:
            return region
    return "International (region not classified)"


def asset_class_of(asset_type: str, exposure: str) -> str:
    """Phase 1 rule (vehicle based); see classify() for the effective class."""
    if asset_type == "MF":
        return ASSET_CLASS_MF
    if asset_type == "STOCK":
        return ASSET_CLASS_STOCKS
    if asset_type == "ETF":
        return ASSET_CLASS_INTL_ETF if exposure == "INTERNATIONAL" else ASSET_CLASS_IN_ETF
    raise ValueError(f"Unknown asset_type {asset_type!r}")


def derive_category(asset_type: str, name: str, exposure: str) -> str:
    """Human label derived from the instrument name (keyword rules, not market data)."""
    n = " ".join(name.lower().replace("-", " ").split())
    if asset_type == "MF":
        rules = [
            ("nifty next 50", "Nifty Next 50 index fund"),
            ("nifty 50", "Nifty 50 index fund"),
            ("mid cap", "Mid-cap fund"),
            ("midcap", "Mid-cap fund"),
            ("small cap", "Small-cap fund"),
            ("smallcap", "Small-cap fund"),
            ("large cap", "Large-cap fund"),
            ("flexi cap", "Flexi-cap fund"),
            ("elss", "ELSS fund"),
        ]
        for needle, label in rules:
            if needle in n:
                return label
        return "Mutual fund"
    if asset_type == "ETF":
        return "International ETF" if exposure == "INTERNATIONAL" else "Indian ETF"
    return "Indian stock"


def weights(values: dict, total: int | None = None) -> dict:
    """values in paise -> exact Decimal fractions of `total` (default: sum of values)."""
    total = sum(values.values()) if total is None else total
    if total <= 0:
        return {k: Decimal(0) for k in values}
    t = Decimal(total)
    return {k: Decimal(v) / t for k, v in values.items()}


def display_pct(fraction: Decimal, places: int = 1) -> Decimal:
    """Fraction -> percentage rounded half-up (the same rounding everywhere in the UI).

    Rounded figures may not add up to exactly 100; calculations always use exact fractions.
    """
    return (fraction * 100).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def asset_class_values(holdings: list[dict]) -> dict[str, int]:
    """holdings: dicts with asset_class and value_paise (None = unpriced, excluded)."""
    out = {c: 0 for c in ASSET_CLASS_ORDER}
    for h in holdings:
        if h["value_paise"] is not None:
            out[h["asset_class"]] += h["value_paise"]
    return {c: v for c, v in out.items() if v > 0 or c != ASSET_CLASS_IN_ETF}
