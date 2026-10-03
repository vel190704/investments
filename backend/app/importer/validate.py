"""Pure row parsing/validation for the workbook sheets. No DB access.

Every function returns data + problems; nothing here raises on bad input.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.money import rupees_to_paise, to_decimal

TXN_TYPES = {"BUY", "SELL", "SIP", "DIVIDEND", "OPENING"}
ASSET_TYPES = {"STOCK", "ETF", "MF"}
KNOWN_PLATFORMS = {"Groww", "Zerodha Coin"}
TXN_COLUMNS = ["date", "type", "asset_type", "name", "symbol", "isin", "scheme_code",
               "quantity", "price", "amount", "charges", "platform", "notes"]
TXN_REQUIRED = ["date", "type", "asset_type", "name", "quantity", "price", "amount"]
FALLBACK_REQUIRED = ["as_of_date", "asset_type", "name", "quantity", "invested_amount"]
PLAN_REQUIRED = ["asset_type", "name", "monthly_amount", "allocation_percent"]
ISIN_RE = re.compile(r"^IN[A-Z0-9]{9}[0-9]$")


@dataclass
class Problem:
    row: int
    message: str
    field: str | None = None


@dataclass
class ParsedTxn:
    row: int
    date: date
    type: str
    asset_type: str
    name: str
    symbol: str | None
    isin: str | None
    scheme_code: str | None
    quantity: Decimal | None
    price: Decimal | None
    amount_paise: int
    charges_paise: int
    platform: str | None
    notes: str | None
    warnings: list[str] = field(default_factory=list)

    @property
    def instrument_key(self) -> str:
        return instrument_key(self.asset_type, self.symbol, self.name)


def normalise_name(name: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", name.lower()).split())


def instrument_key(asset_type: str, symbol: str | None, name: str) -> str:
    if asset_type in ("STOCK", "ETF"):
        return f"EQ:{(symbol or '').strip().upper()}"
    return f"MF:{normalise_name(name)}"


def is_blank(v) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def text(v) -> str | None:
    if is_blank(v):
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def parse_date(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    try:
        return date.fromisoformat(s[:10]) if re.match(r"^\d{4}-\d{2}-\d{2}", s) else date.fromisoformat(s)
    except ValueError as e:
        raise ValueError(f"invalid date {s!r} (expected YYYY-MM-DD)") from e


def parse_number(v, name: str) -> Decimal | None:
    if is_blank(v):
        return None
    try:
        d = to_decimal(v)
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name} {v!r} is not a number") from None
    if not d.is_finite():
        raise ValueError(f"{name} {v!r} is not a finite number")
    return d


def header_problems(header: list, required: list[str], sheet: str) -> list[str]:
    cols = {str(h).strip().lower() for h in header if h is not None}
    missing = [c for c in required if c not in cols]
    return [f"Sheet '{sheet}' is missing required column(s): {', '.join(missing)}"] if missing else []


def row_dict(header: list, values: tuple) -> dict:
    keys = [str(h).strip().lower() if h is not None else None for h in header]
    return {k: v for k, v in zip(keys, values) if k}


def parse_txn(row_no: int, r: dict) -> tuple[ParsedTxn | None, str | None, list[Problem]]:
    """Returns (parsed, skip_reason, errors). Exactly one of parsed/skip_reason/errors is meaningful."""
    if is_blank(r.get("date")):
        return None, "empty date", []
    errs: list[Problem] = []

    def err(field_: str, msg: str):
        errs.append(Problem(row_no, msg, field_))

    try:
        d = parse_date(r.get("date"))
    except ValueError as e:
        err("date", str(e)); d = None
    ttype = (text(r.get("type")) or "").upper()
    if ttype not in TXN_TYPES:
        err("type", f"type {r.get('type')!r} must be one of {', '.join(sorted(TXN_TYPES))}")
    atype = (text(r.get("asset_type")) or "").upper()
    if atype not in ASSET_TYPES:
        err("asset_type", f"asset_type {r.get('asset_type')!r} must be STOCK, ETF or MF")
    name = text(r.get("name"))
    if not name:
        err("name", "name is required")
    symbol = text(r.get("symbol"))
    symbol = symbol.upper() if symbol else None
    warnings: list[str] = []
    if atype in ("STOCK", "ETF") and not symbol:
        err("symbol", "symbol (NSE) is required for STOCK/ETF")
    if atype == "MF" and symbol:
        warnings.append("symbol is ignored for MF rows")
        symbol = None
    isin = text(r.get("isin"))
    if isin:
        isin = isin.upper()
        if not ISIN_RE.match(isin):
            err("isin", f"isin {isin!r} is not a valid Indian ISIN")
    scheme_code = text(r.get("scheme_code"))
    if scheme_code and not scheme_code.isdigit():
        err("scheme_code", f"scheme_code {scheme_code!r} must be numeric")

    qty = price = amount = charges = None
    for fld in ("quantity", "price", "amount", "charges"):
        try:
            val = parse_number(r.get(fld), fld)
        except ValueError as e:
            err(fld, str(e)); continue
        if val is not None and val < 0:
            err(fld, f"{fld} must not be negative (SELL direction comes from type)"); continue
        if fld == "quantity": qty = val
        elif fld == "price": price = val
        elif fld == "amount": amount = val
        else: charges = val

    if ttype == "DIVIDEND":
        if amount is None or amount <= 0:
            err("amount", "DIVIDEND needs a positive amount")
        if qty is not None or price is not None:
            warnings.append("quantity/price are ignored for DIVIDEND rows")
        qty = price = None
    elif ttype in TXN_TYPES:
        if qty is None or qty <= 0:
            err("quantity", f"{ttype} needs a positive quantity")
        if amount is None or amount <= 0:
            err("amount", f"{ttype} needs a positive amount")
        if qty and amount and price:
            implied = qty * price
            tol = max(Decimal(1), amount * Decimal("0.005"))
            if abs(implied - amount) > tol:
                warnings.append(f"quantity × price = {implied:.2f} differs from amount {amount}; amount is used")

    platform = text(r.get("platform"))
    if platform and platform not in KNOWN_PLATFORMS:
        warnings.append(f"unrecognised platform {platform!r}")

    if errs:
        return None, None, errs
    return ParsedTxn(
        row=row_no, date=d, type=ttype, asset_type=atype, name=name, symbol=symbol, isin=isin,
        scheme_code=scheme_code, quantity=qty, price=price,
        amount_paise=rupees_to_paise(amount), charges_paise=rupees_to_paise(charges or 0),
        platform=platform, notes=text(r.get("notes")), warnings=warnings,
    ), None, []


@dataclass
class ParsedFallback:
    row: int
    as_of_date: date
    platform: str | None
    asset_type: str
    name: str
    symbol: str | None
    quantity: Decimal
    invested_paise: int
    monthly_plan_paise: int | None
    sector: str | None
    notes: str | None

    @property
    def instrument_key(self) -> str:
        return instrument_key(self.asset_type, self.symbol, self.name)


def parse_fallback(row_no: int, r: dict) -> tuple[ParsedFallback | None, str | None, list[Problem]]:
    if is_blank(r.get("as_of_date")):
        return None, "empty as_of_date", []
    errs: list[Problem] = []
    try:
        d = parse_date(r.get("as_of_date"))
    except ValueError as e:
        errs.append(Problem(row_no, str(e), "as_of_date")); d = None
    atype = (text(r.get("asset_type")) or "").upper()
    if atype not in ASSET_TYPES:
        errs.append(Problem(row_no, f"asset_type {r.get('asset_type')!r} must be STOCK, ETF or MF", "asset_type"))
    name = text(r.get("name"))
    if not name:
        errs.append(Problem(row_no, "name is required", "name"))
    symbol = text(r.get("symbol"))
    symbol = symbol.upper() if symbol else None
    if atype in ("STOCK", "ETF") and not symbol:
        errs.append(Problem(row_no, "symbol is required for STOCK/ETF", "symbol"))
    nums = {}
    for fld in ("quantity", "invested_amount", "monthly_plan"):
        try:
            nums[fld] = parse_number(r.get(fld), fld)
        except ValueError as e:
            errs.append(Problem(row_no, str(e), fld))
    if nums.get("quantity") is None or nums["quantity"] <= 0:
        errs.append(Problem(row_no, "quantity must be positive", "quantity"))
    if nums.get("invested_amount") is None or nums["invested_amount"] < 0:
        errs.append(Problem(row_no, "invested_amount must be zero or positive", "invested_amount"))
    if errs:
        return None, None, errs
    mp = nums.get("monthly_plan")
    return ParsedFallback(
        row_no, d, text(r.get("platform")), atype, name, symbol if atype != "MF" else None,
        nums["quantity"], rupees_to_paise(nums["invested_amount"]),
        rupees_to_paise(mp) if mp is not None else None, text(r.get("sector")), text(r.get("notes")),
    ), None, []


@dataclass
class ParsedPlan:
    row: int
    platform: str | None
    asset_type: str
    name: str
    monthly_amount_paise: int
    allocation_fraction: Decimal
    is_bucket: bool


def parse_plan(row_no: int, r: dict) -> tuple[ParsedPlan | None, str | None, list[Problem]]:
    """The TOTAL summary row is returned as skip_reason='TOTAL' (used for validation only)."""
    platform = text(r.get("platform"))
    atype = (text(r.get("asset_type")) or "").upper()
    name = text(r.get("name"))
    if (platform or "").upper() == "TOTAL" or atype == "ALL":
        return None, "TOTAL", []
    errs: list[Problem] = []
    if not name:
        errs.append(Problem(row_no, "name is required", "name"))
    try:
        amt = parse_number(r.get("monthly_amount"), "monthly_amount")
        if amt is None or amt < 0:
            errs.append(Problem(row_no, "monthly_amount must be zero or positive", "monthly_amount"))
    except ValueError as e:
        errs.append(Problem(row_no, str(e), "monthly_amount")); amt = None
    try:
        frac = parse_number(r.get("allocation_percent"), "allocation_percent")
        if frac is None or frac < 0 or frac > 1:
            errs.append(Problem(row_no, "allocation_percent must be a FRACTION between 0 and 1 (0.6 = 60%)",
                                "allocation_percent"))
    except ValueError as e:
        errs.append(Problem(row_no, str(e), "allocation_percent")); frac = None
    if errs:
        return None, None, errs
    return ParsedPlan(row_no, platform, atype, name, rupees_to_paise(amt), frac, is_bucket=atype != "MF"), None, []
