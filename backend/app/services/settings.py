"""Persisted user settings (app_settings table), one validated JSON section per key.

No assumed values where the user must decide: `targets` and `emergency_fund` start unset.
Defaults exist only for technical parameters (drift tolerance, concentration thresholds) and the
projection rates, which ship as clearly flagged placeholders (`reviewed: false`).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.calc.allocation import ASSET_CLASS_INTL_ETF, ASSET_CLASS_MF, ASSET_CLASS_STOCKS
from app.calc.concentration import THRESHOLDS, Threshold
from app.models import AppSetting

ASSET_CLASS_GOLD = "Gold"
ASSET_CLASS_DEBT = "Debt/Cash"
TARGET_CLASSES = [ASSET_CLASS_MF, ASSET_CLASS_STOCKS, ASSET_CLASS_INTL_ETF, ASSET_CLASS_GOLD, ASSET_CLASS_DEBT]

DEFAULTS: dict[str, dict | None] = {
    "targets": None,
    "drift": {"tolerance_pp": "5"},
    "concentration": {k: {"low": str(t.low), "high": str(t.high)} for k, t in THRESHOLDS.items()},
    "projection": {"conservative": "6", "base": "9", "higher": "12", "default_years": 10,
                   "default_step_up": "0", "reviewed": False},
    "emergency_fund": None,
}
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
