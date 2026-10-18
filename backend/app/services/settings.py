"""Persisted user settings (app_settings table), one validated JSON section per key.

No assumed values where the user must decide: `targets` and `emergency_fund` start unset.
Defaults exist only for technical parameters (drift tolerance, concentration thresholds) and the
projection rates, which ship as clearly flagged placeholders (`reviewed: false`).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.calc.allocation import (
    ASSET_CLASS_DEBT, ASSET_CLASS_GOLD, ASSET_CLASS_INTL_ETF, ASSET_CLASS_MF, ASSET_CLASS_STOCKS,
)
from app.calc.concentration import THRESHOLDS, Threshold
from app.models import AppSetting

TARGET_CLASSES = [ASSET_CLASS_MF, ASSET_CLASS_STOCKS, ASSET_CLASS_INTL_ETF, ASSET_CLASS_GOLD, ASSET_CLASS_DEBT]

DEFAULTS: dict[str, dict | None] = {
    "targets": None,
    "drift": {"tolerance_pp": "5"},
    "concentration": {k: {"low": str(t.low), "high": str(t.high)} for k, t in THRESHOLDS.items()},
    "projection": {"conservative": "6", "base": "9", "higher": "12", "default_years": 10,
                   "default_step_up": "0", "reviewed": False},
    "emergency_fund": None,
    "sector_ranges": None,
    "themes": None,
    "health": {
        "company_lookthrough": {"low": "0.05", "high": "0.10"},
        "sector_largest": {"low": "0.25", "high": "0.40"},
        "sector_hhi": {"low": "1500", "high": "2500"},
        "overlap": {"low": "0.30", "high": "0.50"},
        "drift": {"high_multiple": "2"},
        "emergency": {"moderate_below": "1.0", "high_below": "0.5"},
    },
}
DEFAULTS.update({
    "llm": {"outbound_enabled": False, "model": None, "monthly_call_cap": 30, "weekly_job": False,
            "price_in_per_mtok": None, "price_out_per_mtok": None, "effort": "high", "refusal_fallback": False},
    "news": {"feeds": [
        {"name": "ET Markets", "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"},
        {"name": "Mint Markets", "url": "https://www.livemint.com/rss/markets"},
    ]},
    "alerts": {"announcement": True, "announcement_categories": [
        "results", "order win / contract", "dividend", "board meeting", "acquisition / merger", "regulatory / legal",
        "management change", "rating action"], "concentration_change": True, "disclosure_stale": True,
        "review_due": True},
})
from app.calc.framework import DEFAULT_RUBRIC, DEFAULT_SECTOR_RULES

DEFAULTS.update({"rubric": dict(DEFAULT_RUBRIC), "sector_rules": {k: list(v) for k, v in DEFAULT_SECTOR_RULES.items()}})
# Live intraday prices: off until the user turns it on (it makes a request every poll interval in market hours).
# The holiday table starts empty: dates are entered by hand and verified against the NSE holiday list.
DEFAULTS.update({"live": {"enabled": False, "poll_seconds": 60}, "market_holidays": {"holidays": []}})
HOLIDAY_NOTE = ("Enter exchange holidays by hand and verify them against the NSE holiday list (nseindia.com › "
                "Resources › Exchange Communication › Holidays). Nothing is scraped. Until a holiday is entered, that "
                "weekday is treated as a trading day.")
SECTIONS = tuple(DEFAULTS)
FALLBACK_MODEL = "claude-opus-5-5"
PRICING_NOTE = "Verify against the provider's pricing page; the app ships no prices."
EFFORTS = ("low", "medium", "high", "xhigh", "max")

HEALTH_LABELS = {
    "company_lookthrough": ("Company total exposure (direct + funds), % of portfolio", "fraction"),
    "sector_largest": ("Largest sector, % of equity exposure", "fraction"),
    "sector_hhi": ("Sector HHI", "hhi"),
    "overlap": ("Largest pairwise fund overlap", "fraction"),
}
# Live intraday prices: off until the user turns it on (it makes a request every poll interval in market hours).
# The holiday table starts empty: dates are entered by hand and verified against the NSE holiday list.
DEFAULTS.update({"live": {"enabled": False, "poll_seconds": 60}, "market_holidays": {"holidays": []}})
HOLIDAY_NOTE = ("Enter exchange holidays by hand and verify them against the NSE holiday list (nseindia.com › "
                "Resources › Exchange Communication › Holidays). Nothing is scraped. Until a holiday is entered, that "
                "weekday is treated as a trading day.")
SECTIONS = tuple(DEFAULTS)


class SettingsError(ValueError):
    pass


def _dec(v, name: str, lo: Decimal | None = None, hi: Decimal | None = None) -> Decimal:
    try:
        d = Decimal(str(v).strip())
    except (InvalidOperation, ValueError):
        raise SettingsError(f"{name} must be a number") from None
    if not d.is_finite():
        raise SettingsError(f"{name} must be a number")
    if lo is not None and d < lo:
        raise SettingsError(f"{name} must be at least {lo}")
    if hi is not None and d > hi:
        raise SettingsError(f"{name} must be at most {hi}")
    return d


def _s(d: Decimal) -> str:
    return format(d.normalize(), "f") if d != 0 else "0"


def validate(section: str, value: dict) -> dict:
    if section not in SECTIONS:
        raise SettingsError(f"unknown settings section {section!r}")
    if not isinstance(value, dict):
        raise SettingsError("value must be an object")

    if section == "targets":
        missing = [c for c in TARGET_CLASSES if c not in value]
        extra = [k for k in value if k not in TARGET_CLASSES]
        if missing or extra:
            raise SettingsError(f"targets need exactly these classes: {', '.join(TARGET_CLASSES)}")
        vals = {c: _dec(value[c], f"{c} target", Decimal(0), Decimal(100)) for c in TARGET_CLASSES}
        total = sum(vals.values())
        if total != 100:
            raise SettingsError(f"targets must total exactly 100% (they total {_s(total)}%)")
        return {c: _s(v) for c, v in vals.items()}

    if section == "drift":
        return {"tolerance_pp": _s(_dec(value.get("tolerance_pp"), "tolerance", Decimal("0.1"), Decimal(50)))}

    if section == "concentration":
        out = {}
        for key, t in THRESHOLDS.items():
            v = value.get(key) or {}
            hi_cap = Decimal(10000) if t.unit == "hhi" else Decimal(1)
            low = _dec(v.get("low", t.low), f"{t.label} low", Decimal(0), hi_cap)
            high = _dec(v.get("high", t.high), f"{t.label} high", Decimal(0), hi_cap)
            if not low < high:
                raise SettingsError(f"{t.label}: low must be below high")
            out[key] = {"low": _s(low), "high": _s(high)}
        return out

    if section == "projection":
        rates = {k: _dec(value.get(k), f"{k} rate", Decimal(-50), Decimal(50))
                 for k in ("conservative", "base", "higher")}
        if not rates["conservative"] <= rates["base"] <= rates["higher"]:
            raise SettingsError("rates must be ordered: Conservative ≤ Base ≤ Higher")
        years = value.get("default_years", 10)
        if not isinstance(years, int) or not 1 <= years <= 50:
            raise SettingsError("default years must be a whole number from 1 to 50")
        step = _dec(value.get("default_step_up", "0"), "step-up", Decimal(0), Decimal(50))
        return {**{k: _s(v) for k, v in rates.items()}, "default_years": years, "default_step_up": _s(step),
                "reviewed": bool(value.get("reviewed", False))}

    if section == "sector_ranges":
        out = {}
        for sector, rg in value.items():
            if not str(sector).strip() or not isinstance(rg, dict):
                raise SettingsError("each range needs a sector name and {min, max}")
            lo = _dec(rg.get("min"), f"{sector} min", Decimal(0), Decimal(100))
            hi = _dec(rg.get("max"), f"{sector} max", Decimal(0), Decimal(100))
            if lo > hi:
                raise SettingsError(f"{sector}: min must not exceed max")
            out[str(sector).strip()] = {"min": _s(lo), "max": _s(hi)}
        return out

    if section == "themes":
        import re

        out = {}
        for tag, isins in value.items():
            tag = str(tag).strip()
            if not tag or not isinstance(isins, list):
                raise SettingsError("each theme needs a name and a list of company ISINs")
            clean = []
            for i in isins:
                i = str(i).strip().upper()
                if not re.match(r"^IN[A-Z0-9]{10}$", i):
                    raise SettingsError(f"{tag}: {i!r} is not an ISIN (themes are matched by ISIN)")
                clean.append(i)
            out[tag] = sorted(set(clean))
        return out

    if section == "health":
        out = {}
        d = DEFAULTS["health"]
        for key, (label, unit) in HEALTH_LABELS.items():
            v = value.get(key) or {}
            cap = Decimal(10000) if unit == "hhi" else Decimal(1)
            lo = _dec(v.get("low", d[key]["low"]), f"{label} low", Decimal(0), cap)
            hi = _dec(v.get("high", d[key]["high"]), f"{label} high", Decimal(0), cap)
            if not lo < hi:
                raise SettingsError(f"{label}: low must be below high")
            out[key] = {"low": _s(lo), "high": _s(hi)}
        mult = _dec((value.get("drift") or {}).get("high_multiple", d["drift"]["high_multiple"]),
                    "drift HIGH multiple", Decimal(1), Decimal(10))
        out["drift"] = {"high_multiple": _s(mult)}
        e = value.get("emergency") or {}
        mod = _dec(e.get("moderate_below", d["emergency"]["moderate_below"]), "emergency MODERATE below", Decimal(0), Decimal(5))
        high = _dec(e.get("high_below", d["emergency"]["high_below"]), "emergency HIGH below", Decimal(0), Decimal(5))
        if not high < mod:
            raise SettingsError("emergency fund: the HIGH cut-off must be below the MODERATE cut-off")
        out["emergency"] = {"moderate_below": _s(mod), "high_below": _s(high)}
        return out

    if section == "llm":
        import re

        model = value.get("model")
        model = str(model).strip() if model not in (None, "") else None
        if model is not None and not re.fullmatch(r"[a-z0-9][a-z0-9.\-]{2,80}", model):
            raise SettingsError("model must be a model id such as claude-opus-5-5 (lower-case letters, digits, dots, dashes)")
        cap = value.get("monthly_call_cap", 30)
        if not isinstance(cap, int) or isinstance(cap, bool) or not 0 <= cap <= 10000:
            raise SettingsError("monthly call cap must be a whole number from 0 to 10,000")
        effort = str(value.get("effort", "high"))
        if effort not in EFFORTS:
            raise SettingsError(f"effort must be one of {', '.join(EFFORTS)}")
        def price(key, label):
            v = value.get(key)
            if v in (None, ""):
                return None
            return _s(_dec(v, label, Decimal(0), Decimal(1000)))

        return {"outbound_enabled": bool(value.get("outbound_enabled", False)), "model": model,
                "monthly_call_cap": cap, "weekly_job": bool(value.get("weekly_job", False)),
                "price_in_per_mtok": price("price_in_per_mtok", "input price"),
                "price_out_per_mtok": price("price_out_per_mtok", "output price"),
                "effort": effort, "refusal_fallback": bool(value.get("refusal_fallback", False))}

    if section == "news":
        feeds = value.get("feeds")
        if not isinstance(feeds, list):
            raise SettingsError("feeds must be a list of {name, url}")
        out_feeds = []
        for f in feeds:
            name, url = str((f or {}).get("name", "")).strip(), str((f or {}).get("url", "")).strip()
            if not name or not url.startswith("https://"):
                raise SettingsError("each feed needs a name and an https:// URL")
            out_feeds.append({"name": name[:100], "url": url[:1000]})
        return {"feeds": out_feeds}

    if section == "alerts":
        from app.calc.news import CATEGORIES

        cats = value.get("announcement_categories", [])
        if not isinstance(cats, list) or any(c not in CATEGORIES for c in cats):
            raise SettingsError(f"categories must come from: {', '.join(CATEGORIES)}")
        return {"announcement": bool(value.get("announcement", True)), "announcement_categories": cats,
                "concentration_change": bool(value.get("concentration_change", True)),
                "disclosure_stale": bool(value.get("disclosure_stale", True)),
                "review_due": bool(value.get("review_due", True))}

    if section == "live":
        from app.calc.market_hours import POLL_MAX, POLL_MIN

        try:
            poll = int(value.get("poll_seconds", 60))
        except (TypeError, ValueError):
            raise SettingsError("poll interval must be a whole number of seconds") from None
        if not POLL_MIN <= poll <= POLL_MAX:
            raise SettingsError(f"poll interval must be between {POLL_MIN} and {POLL_MAX} seconds")
        return {"enabled": bool(value.get("enabled", False)), "poll_seconds": poll}

    if section == "market_holidays":
        rows, seen = [], set()
        for h in value.get("holidays", []):
            try:
                d = date.fromisoformat(str(h.get("date", "")))
            except ValueError:
                raise SettingsError(f"holiday date {h.get('date')!r} is not YYYY-MM-DD") from None
            name = str(h.get("name", "")).strip()
            if not name:
                raise SettingsError(f"holiday {d.isoformat()} needs a name")
            if d in seen:
                raise SettingsError(f"holiday {d.isoformat()} is listed twice")
            seen.add(d)
            rows.append({"date": d.isoformat(), "name": name[:80]})
        return {"holidays": sorted(rows, key=lambda r: r["date"])}

    if section == "rubric":
        return {
            "pe_vs_peer_tolerance_pct": _s(_dec(value.get("pe_vs_peer_tolerance_pct", "0"), "P/E tolerance", Decimal(0), Decimal(100))),
            "peg_max": _s(_dec(value.get("peg_max", "1.0"), "PEG maximum", Decimal("0.01"), Decimal(10))),
            "roe_min_pct": _s(_dec(value.get("roe_min_pct", "15"), "ROE minimum", Decimal(-100), Decimal(200))),
            "de_max": _s(_dec(value.get("de_max", "2.0"), "D/E maximum", Decimal(0), Decimal(50))),
            "fcf_positive": bool(value.get("fcf_positive", True)),
            "fcf_not_declining": bool(value.get("fcf_not_declining", True)),
        }

    if section == "sector_rules":
        allowed = {"debt_to_equity", "interest_coverage", "peg", "roe", "pe_vs_peers", "fcf_positive", "fcf_not_declining"}
        out = {}
        for sector, metrics in value.items():
            if not str(sector).strip() or not isinstance(metrics, list) or any(m not in allowed for m in metrics):
                raise SettingsError(f"sector rules: metrics must be from {sorted(allowed)}")
            out[str(sector).strip()] = sorted(set(metrics))
        return out

    # emergency_fund
    out = {}
    for k in ("monthly_expenses_paise", "balance_paise"):
        v = value.get(k)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise SettingsError(f"{k} must be a whole number of paise, zero or more")
        out[k] = v
    if out["monthly_expenses_paise"] == 0:
        raise SettingsError("monthly essential expenses must be more than zero")
    months = value.get("target_months")
    if not isinstance(months, int) or not 3 <= months <= 6:
        raise SettingsError("target months must be a whole number from 3 to 6")
    out["target_months"] = months
    return out


def get(s: Session, section: str) -> dict | None:
    row = s.get(AppSetting, section)
    return row.value if row is not None else DEFAULTS[section]


def is_set(s: Session, section: str) -> bool:
    return s.get(AppSetting, section) is not None


def put(s: Session, section: str, value: dict) -> dict:
    clean = validate(section, value)
    row = s.get(AppSetting, section)
    if row is None:
        s.add(AppSetting(key=section, value=clean))
    else:
        row.value = clean
    s.flush()
    return clean


def reset(s: Session, section: str) -> None:
    if section not in SECTIONS:
        raise SettingsError(f"unknown settings section {section!r}")
    row = s.get(AppSetting, section)
    if row is not None:
        s.delete(row)
        s.flush()


def all_settings(s: Session) -> dict:
    return {sec: {"value": get(s, sec), "is_set": is_set(s, sec), "default": DEFAULTS[sec]} for sec in SECTIONS}


# typed accessors used by calculations
def targets(s: Session) -> dict[str, Decimal] | None:
    v = get(s, "targets")
    return {c: Decimal(x) / 100 for c, x in v.items()} if v else None


def tolerance_pp(s: Session) -> Decimal:
    return Decimal(get(s, "drift")["tolerance_pp"])


def concentration_thresholds(s: Session) -> dict[str, Threshold]:
    v = get(s, "concentration")
    out = {}
    for key, t in THRESHOLDS.items():
        o = v.get(key, {})
        out[key] = Threshold(t.key, t.label, Decimal(o.get("low", t.low)), Decimal(o.get("high", t.high)), t.unit,
                             t.explanation)
    return out


def health_thresholds(s: Session) -> dict:
    """Typed health thresholds (Threshold objects for low/high pairs)."""
    v = get(s, "health")
    d = DEFAULTS["health"]
    out = {}
    for key, (label, unit) in HEALTH_LABELS.items():
        x = v.get(key, d[key])
        out[key] = Threshold(key, label, Decimal(x["low"]), Decimal(x["high"]), unit, "")
    out["drift_high_multiple"] = Decimal(v.get("drift", d["drift"])["high_multiple"])
    e = v.get("emergency", d["emergency"])
    out["emergency"] = (Decimal(e["high_below"]), Decimal(e["moderate_below"]))
    return out


def llm_model(s: Session) -> str:
    """Settings model, else CLAUDE_MODEL from .env, else the documented default."""
    from app.config import get_settings

    return get(s, "llm").get("model") or get_settings().claude_model or FALLBACK_MODEL
