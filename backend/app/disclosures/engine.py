"""AMC monthly portfolio disclosure parsing (xlsx/csv).

One engine, one Layout per AMC (column aliases + AMC markers). Unknown layouts raise
DisclosureFormatError listing what was looked for and what was found; nothing is guessed.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import openpyxl

from app.calc.lookthrough import is_equity_isin

ISIN_RE = re.compile(r"^IN[A-Z0-9]{10}$")
TOTAL_RE = re.compile(r"^(grand\s*)?(sub\s*-?\s*)?total\b", re.I)
STOP_RE = re.compile(r"^(grand\s*total|total\s*net\s*assets|net\s*assets)\b", re.I)
HEADER_SCAN_ROWS = 40


class DisclosureFormatError(ValueError):
    pass


def norm(h) -> str:
    return re.sub(r"[^a-z0-9%]+", "", str(h or "").lower())


@dataclass(frozen=True)
class Layout:
    key: str
    label: str
    markers: tuple[str, ...]  # text that identifies the AMC in the file's top rows / sheet names
    name: tuple[str, ...]
    isin: tuple[str, ...]
    weight: tuple[str, ...]
    industry: tuple[str, ...] = ()


LAYOUTS = {
    "HDFC": Layout("HDFC", "HDFC Mutual Fund", ("hdfc mutual fund", "hdfc asset management"),
                   ("Name of the Instrument", "Name Of the Instrument", "Name of Instrument"), ("ISIN",),
                   ("% to NAV", "% to Net Assets"), ("Industry+ /Rating", "Industry / Rating", "Industry")),
    "ICICI": Layout("ICICI", "ICICI Prudential Mutual Fund", ("icici prudential",),
                    ("Company/Issuer/Instrument Name", "Company/Issuer Name", "Name of the Instrument"), ("ISIN",),
                    ("% to Nav", "% to NAV", "% of NAV", "% to Net Assets"), ("Industry/Rating", "Industry")),
    "KOTAK": Layout("KOTAK", "Kotak Mahindra Mutual Fund", ("kotak mahindra", "kotak mutual fund"),
                    ("Name of Instrument", "Name of the Instrument", "Issuer/Instrument Name"), ("ISIN Code", "ISIN"),
                    ("% to Net Assets", "% to NAV", "% of Net Assets"), ("Industry", "Industry / Rating", "Rating/Industry")),
}
GENERIC = Layout("GENERIC_CSV", "Generic weights file (isin, name, weight[, industry])", (),
                 ("name", "company", "company name", "security name"), ("isin", "isin code"),
                 ("weight", "weight %", "weightage", "weightage %", "% weight"), ("industry", "sector"))

DATE_FORMATS = ["%B %d, %Y", "%B %d,%Y", "%b %d, %Y", "%b %d,%Y", "%d-%b-%Y", "%d-%B-%Y", "%d %B %Y", "%d %b %Y",
                "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %B, %Y", "%d-%b-%y"]
AS_ON_RE = re.compile(r"as\s*(?:on|at|of)\s*[:\-]?\s*([0-9A-Za-z ,./\-]{6,30})", re.I)


def parse_date_text(text: str) -> date | None:
    t = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text.strip().rstrip(".").strip())
    t = re.sub(r"\s+", " ", t)
    for n in range(len(t), 5, -1):  # tolerate trailing words after the date
        chunk = t[:n].strip(" ,.-")
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(chunk, fmt).date()
            except ValueError:
                continue
    return None


@dataclass
class ParsedRow:
    isin: str | None
    name: str
    industry: str | None
    weight: Decimal
    is_equity: bool


@dataclass
class ParsedDisclosure:
    parser: str
    amc: str
    sheet: str | None
    title: str
    as_of: date | None
    rows: list[ParsedRow]
    total_weight: Decimal
    equity_weight: Decimal
    warnings: list[str] = field(default_factory=list)


Sheet = tuple[str | None, list[tuple]]


def read_sheets(data: bytes, filename: str) -> list[Sheet]:
    name = filename.lower()
    if name.endswith(".csv"):
        text = data.decode("utf-8-sig", errors="replace")
        return [(None, [tuple(r) for r in csv.reader(io.StringIO(text))])]
    if name.endswith((".xlsx", ".xlsm")):
        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        except Exception as e:
            raise DisclosureFormatError(f"Could not open the workbook: {e}") from None
        return [(ws.title, [tuple(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]
    raise DisclosureFormatError("Unsupported file type: upload the AMC's .xlsx (or a .csv)")


def _text(rows: list[tuple], n: int = 12) -> str:
    return " ".join(str(c) for r in rows[:n] for c in r if c not in (None, ""))


def detect_amc(sheets: list[Sheet]) -> str | None:
    blob = (" ".join(t or "" for t, _ in sheets) + " " + " ".join(_text(r) for _, r in sheets[:5])).lower()
    for key, lay in LAYOUTS.items():
        if any(m in blob for m in lay.markers):
            return key
    return None


def _find(header: tuple, aliases: tuple[str, ...]) -> int | None:
    normed = [norm(h) for h in header]
    for a in aliases:  # exact alias match first, in alias priority order
        if norm(a) in normed:
            return normed.index(norm(a))
    for a in aliases:  # then "starts with" (e.g. "% to NAV (Rs.)")
        for i, h in enumerate(normed):
            if h and h.startswith(norm(a)):
                return i
    return None


def find_header(rows: list[tuple], lay: Layout) -> tuple[int, dict[str, int | None]] | None:
    for i, r in enumerate(rows[:HEADER_SCAN_ROWS]):
        cols = {"isin": _find(r, lay.isin), "weight": _find(r, lay.weight), "name": _find(r, lay.name),
                "industry": _find(r, lay.industry) if lay.industry else None}
        if cols["isin"] is not None and cols["weight"] is not None and cols["name"] is not None:
            return i, cols
    return None


def _dec(v) -> Decimal | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, float):
        v = repr(v)
    try:
        d = Decimal(str(v).replace(",", "").replace("%", "").strip())
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def find_as_of(rows: list[tuple]) -> date | None:
    for r in rows[:HEADER_SCAN_ROWS]:
        for c in r:
            if isinstance(c, datetime):
                continue  # bare date cells are ambiguous (could be a maturity date); require "as on"
            m = AS_ON_RE.search(str(c or ""))
            if m:
                d = parse_date_text(m.group(1))
                if d:
                    return d
    return None


NAME_NOISE = {"fund", "direct", "regular", "growth", "plan", "option", "the", "scheme", "idcw", "cumulative"}


def _want(fund_name: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", fund_name.lower().replace("midcap", "mid cap")) if w not in NAME_NOISE]


def _score_sheet(title: str | None, rows: list[tuple], fund_name: str) -> int:
    want = _want(fund_name)
    hay = ((title or "") + " " + _text(rows, 8)).lower().replace("midcap", "mid cap")
    hay_words = set(re.findall(r"[a-z0-9]+", hay))
    return sum(1 for w in want if w in hay_words)


def parse_disclosure(data: bytes, filename: str, fund_name: str, amc: str | None = None,
                     as_of: date | None = None, generic: bool = False) -> ParsedDisclosure:
    sheets = [s for s in read_sheets(data, filename) if s[1]]
    if not sheets:
        raise DisclosureFormatError("The file has no rows")
    if generic:
        lay = GENERIC
    else:
        key = (amc or "").upper() or detect_amc(sheets)
        if key not in LAYOUTS:
            found = _text(sheets[0][1], 3)[:200]
            raise DisclosureFormatError(
                "Unrecognised layout: could not identify the AMC (looked for "
                + "; ".join(f"{l.label}: {', '.join(l.markers)}" for l in LAYOUTS.values())
                + f"). First rows found: {found!r}. Choose the AMC explicitly, or use the generic CSV format.")
        lay = LAYOUTS[key]

    candidates = []
    for title, rows in sheets:
        hdr = find_header(rows, lay)
        if hdr:
            candidates.append((_score_sheet(title, rows, fund_name), title, rows, hdr))
    if not candidates:
        first = next((r for r in sheets[0][1][:HEADER_SCAN_ROWS] if sum(1 for c in r if c) >= 3), sheets[0][1][0])
        raise DisclosureFormatError(
            f"Unrecognised {lay.label} layout: no header row with a name column ({' / '.join(lay.name)}), "
            f"an ISIN column ({' / '.join(lay.isin)}) and a weight column ({' / '.join(lay.weight)}) in the first "
            f"{HEADER_SCAN_ROWS} rows. A row found: {[c for c in first if c not in (None, '')]}")
    candidates.sort(key=lambda c: -c[0])
    if len(candidates) > 1 and candidates[0][0] * 2 < len(_want(fund_name)):
        raise DisclosureFormatError(f"No sheet mentions '{fund_name}'. Sheets: {[c[1] for c in candidates[:10]]}")
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        raise DisclosureFormatError(
            f"Several scheme sheets match '{fund_name}' equally: {[c[1] for c in candidates[:5]]}. "
            "Upload the single-scheme file, or check the fund chosen.")
    _, title, rows, (hi, cols) = candidates[0]

    found_as_of = find_as_of(rows)
    if as_of is None:
        as_of = found_as_of
    if as_of is None:
        raise DisclosureFormatError("Could not find the portfolio date ('as on …') in the file; enter the as-of "
                                    "date manually")

    parsed: list[ParsedRow] = []
    for r in rows[hi + 1:]:
        def cell(k):
            i = cols.get(k)
            return r[i] if i is not None and i < len(r) else None
        name = str(cell("name") or "").strip()
        if name and STOP_RE.match(name):
            break
        if not name or TOTAL_RE.match(name):
            continue
        w = _dec(cell("weight"))
        if w is None:
            continue  # section headings ("EQUITY & EQUITY RELATED") have no weight
        isin = str(cell("isin") or "").strip().upper() or None
        if isin and not ISIN_RE.match(isin):
            isin = None
        ind = str(cell("industry") or "").strip() or None
        parsed.append(ParsedRow(isin, name, ind, w, is_equity_isin(isin)))
    if not parsed:
        raise DisclosureFormatError(f"Header found in sheet {title!r} but no holdings rows with a weight below it")

    total = sum((p.weight for p in parsed), Decimal(0))
    warnings = []
    if total > Decimal("1.5"):  # percent -> fraction
        for p in parsed:
            p.weight = p.weight / 100
        total = total / 100
    if not (Decimal("0.90") <= total <= Decimal("1.05")):
        warnings.append(f"Weights add up to {total * 100:.2f}% of NAV (expected about 100%); check the file.")
    eq = sum((p.weight for p in parsed if p.is_equity), Decimal(0))
    if eq == 0:
        raise DisclosureFormatError("No equity holdings (ISINs with security code 01) were found")
    if found_as_of and found_as_of != as_of:
        warnings.append(f"File says 'as on {found_as_of}', but {as_of} was entered; the entered date is used.")
    return ParsedDisclosure(lay.key, lay.label, title, _text(rows, 3)[:200], as_of, parsed, total, eq, warnings)
