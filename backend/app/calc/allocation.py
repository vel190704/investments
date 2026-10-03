"""Asset-class allocation and weights. Weight = current market value / total value."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

ASSET_CLASS_MF = "Mutual funds"
ASSET_CLASS_STOCKS = "Indian stocks"
ASSET_CLASS_INTL_ETF = "International ETFs"
ASSET_CLASS_IN_ETF = "Indian ETFs"
ASSET_CLASS_ORDER = [ASSET_CLASS_MF, ASSET_CLASS_STOCKS, ASSET_CLASS_INTL_ETF, ASSET_CLASS_IN_ETF]

# Per the spec; corroborated by NSE's ETF list ("GLOBAL INDICES" underlying).
INTERNATIONAL_ETF_SYMBOLS = frozenset({"MAFANG", "HNGSNGBEES"})


def asset_class_of(asset_type: str, exposure: str) -> str:
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
