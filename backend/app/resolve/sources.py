"""Downloads + parsers for NSE securities lists and AMFI NAVAll.txt (cached under data/cache)."""

from __future__ import annotations

import csv
import io
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import logging

import httpx

from app.config import get_settings
from app.net.outbound import outbound

log = logging.getLogger(__name__)

NSE_EQUITY_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_ETF_URL = "https://nsearchives.nseindia.com/content/equities/eq_etfseclist.csv"
AMFI_NAV_URL = "https://www.amfiindia.com/spages/NAVAll.txt"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) personal-portfolio-dashboard"}


def download(url: str, cache_name: str, max_age_hours: float) -> tuple[str, datetime]:
    """Return (text, fetched_at). Uses the cache when fresh; falls back to a stale cache on failure."""
    settings = get_settings()
    path: Path = settings.cache_dir / cache_name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and (time.time() - path.stat().st_mtime) < max_age_hours * 3600:
        return path.read_text(encoding="utf-8"), datetime.fromtimestamp(path.stat().st_mtime).astimezone()
    try:
        with outbound(cache_name, url) as rec:
            r = httpx.get(url, headers=UA, timeout=settings.http_timeout_seconds, follow_redirects=True)
            rec["status"], rec["bytes"] = r.status_code, len(r.content)
            r.raise_for_status()
        path.write_text(r.text, encoding="utf-8")
        return r.text, datetime.now().astimezone()
    except Exception:
        if path.exists():
            log.warning("serving stale cache", extra={"fields": {"source": cache_name, "cached_at": datetime.fromtimestamp(
                path.stat().st_mtime).astimezone().isoformat()}})
            return path.read_text(encoding="utf-8"), datetime.fromtimestamp(path.stat().st_mtime).astimezone()
        raise


@dataclass(frozen=True)
class NseSecurity:
    symbol: str
    name: str
    isin: str
    kind: str  # EQUITY | ETF
    underlying: str | None = None  # NSE "Underlying Key" (GOLD, Nifty 50, GLOBAL INDICES, ...)
    etf_underlying: str | None = None  # NSE "ETF Underlying" (EQUITY | COMMODITY | DEBT | GLOBAL INDICES)
    underlying_asset: str | None = None  # NSE "Underlying Asset" (e.g. "Hang Seng Index")


def parse_nse_equity(text: str) -> dict[str, NseSecurity]:
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        if row.get("SYMBOL") and row.get("ISIN NUMBER"):
            out[row["SYMBOL"].upper()] = NseSecurity(row["SYMBOL"].upper(), row.get("NAME OF COMPANY", ""),
                                                     row["ISIN NUMBER"], "EQUITY")
    return out


def parse_nse_etf(text: str) -> dict[str, NseSecurity]:
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        if row.get("Symbol") and row.get("ISINNumber"):
            out[row["Symbol"].upper()] = NseSecurity(
                row["Symbol"].upper(), row.get("SecurityName") or row.get("Underlying Asset", ""),
                row["ISINNumber"], "ETF", row.get("Underlying Key") or row.get("ETF Underlying"),
                row.get("ETF Underlying") or None, row.get("Underlying Asset") or None)
    return out


def nse_securities() -> tuple[dict[str, NseSecurity], datetime]:
    eq, t1 = download(NSE_EQUITY_URL, "EQUITY_L.csv", 24 * 7)
    etf, t2 = download(NSE_ETF_URL, "eq_etfseclist.csv", 24 * 7)
    return {**parse_nse_equity(eq), **parse_nse_etf(etf)}, min(t1, t2)


NSE_INDEX_LISTS = {
    "Nifty Total Market": "https://nsearchives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv",
    "Nifty Microcap 250": "https://nsearchives.nseindia.com/content/indices/ind_niftymicrocap250_list.csv",
}


@dataclass(frozen=True)
class NseIndustry:
    symbol: str
    isin: str
    company: str
    industry: str
    list_name: str


def parse_nse_index_list(text: str, list_name: str) -> list[NseIndustry]:
    """NSE index constituent CSV: Company Name, Industry, Symbol, Series, ISIN Code."""
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        if row.get("ISIN Code") and row.get("Industry"):
            out.append(NseIndustry(row.get("Symbol", "").upper(), row["ISIN Code"].upper(),
                                   row.get("Company Name", ""), row["Industry"], list_name))
    return out


def nse_industries() -> tuple[dict[str, NseIndustry], dict[str, NseIndustry], datetime]:
    """(by ISIN, by symbol, oldest fetch time) across the NSE index lists. The first list wins."""
    by_isin: dict[str, NseIndustry] = {}
    by_symbol: dict[str, NseIndustry] = {}
    fetched = []
    for name, url in NSE_INDEX_LISTS.items():
        text, t = download(url, url.rsplit("/", 1)[1], 24 * 7)
        fetched.append(t)
        for r in parse_nse_index_list(text, name):
            by_isin.setdefault(r.isin, r)
            by_symbol.setdefault(r.symbol, r)
    return by_isin, by_symbol, min(fetched)


@dataclass(frozen=True)
class AmfiScheme:
    scheme_code: str
    isin_growth: str | None
    isin_reinvest: str | None
    name: str  # full display name incl. plan/option
    base_name: str
    plan: str | None
    option: str | None
    nav: Decimal | None
    nav_date: date | None
    fund_house: str | None
    category: str | None = None  # from the section header, e.g. "Equity Scheme - Mid Cap Fund"


def _clean_isin(v: str) -> str | None:
    v = v.strip()
    return v if v and v not in ("-", "NA") else None


def parse_amfi(text: str) -> dict[str, AmfiScheme]:
    """Parse NAVAll.txt. Supports the 8-column layout (Scheme Name;Plan;Option split out)
    and the legacy 6-column layout (plan/option inside the scheme name)."""
    out: dict[str, AmfiScheme] = {}
    fund_house = None
    category = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if ";" not in line:
            m = re.match(r"^(Open Ended|Close Ended|Interval Fund) Schemes?\s*\((.+)\)\s*$", line)
            if m:
                category = f"{m.group(1)} — {m.group(2).strip()}"
            elif "Mutual Fund" in line:
                fund_house = line
            continue
        parts = [p.strip() for p in line.split(";")]
        if not parts[0].isdigit():
            continue  # header
        if len(parts) >= 8:
            code, isin1, isin2, base, plan, option, nav_s, date_s = parts[:8]
            name = " - ".join(x for x in (base, plan, option) if x)
        elif len(parts) >= 6:
            code, isin1, isin2, base, nav_s, date_s = parts[:6]
            plan = option = None
            name = base
        else:
            continue
        try:
            nav = Decimal(nav_s)
            if nav <= 0:
                nav = None
        except InvalidOperation:
            nav = None
        try:
            nav_date = datetime.strptime(date_s, "%d-%b-%Y").date()
        except ValueError:
            nav_date = None
        out[code] = AmfiScheme(code, _clean_isin(isin1), _clean_isin(isin2), name, base, plan or None,
                               option or None, nav, nav_date, fund_house, category)
    return out


def amfi_schemes(max_age_hours: float = 6) -> tuple[dict[str, AmfiScheme], datetime]:
    text, fetched = download(AMFI_NAV_URL, "NAVAll.txt", max_age_hours)
    return parse_amfi(text), fetched
