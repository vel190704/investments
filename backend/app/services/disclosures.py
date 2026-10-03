"""Store uploaded fund disclosures / index weights; load the latest per fund for look-through."""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import repository as repo
from app.calc.lookthrough import FundRow, is_stale
from app.disclosures.engine import DisclosureFormatError, parse_disclosure
from app.models import DisclosureHolding, FundDisclosure
from app.timeutil import as_utc, today_ist

KINDS = ("AMC_DISCLOSURE", "INDEX_WEIGHTS")


def upload(s: Session, data: bytes, filename: str, instrument_id: int, kind: str, amc: str | None = None,
           as_of: date | None = None, index_name: str | None = None) -> dict:
    inst = repo.get_instrument(s, instrument_id)
    if inst is None or inst.asset_type != "MF":
        raise DisclosureFormatError("Choose one of your mutual funds")
    if kind not in KINDS:
        raise DisclosureFormatError(f"kind must be one of {KINDS}")
    if kind == "INDEX_WEIGHTS":
        if not index_name or not index_name.strip():
            raise DisclosureFormatError("Enter the index name (e.g. Nifty 50) for index weights")
        if as_of is None:
            raise DisclosureFormatError("Enter the as-of date of the index weights")
    if as_of and as_of > today_ist():
        raise DisclosureFormatError("The as-of date cannot be in the future")
    p = parse_disclosure(data, filename, inst.name, amc=amc, as_of=as_of, generic=(kind == "INDEX_WEIGHTS"))
    old = s.scalar(select(FundDisclosure).where(FundDisclosure.instrument_id == inst.id, FundDisclosure.kind == kind,
                                                FundDisclosure.as_of == p.as_of))
    replaced = old is not None
    if old is not None:
        s.delete(old)
        s.flush()
    d = FundDisclosure(instrument_id=inst.id, kind=kind, as_of=p.as_of, index_name=index_name, parser=p.parser,
                       source_file=filename, file_sha256=hashlib.sha256(data).hexdigest(),
                       equity_weight=p.equity_weight, rows=len(p.rows))
    d.holdings = [DisclosureHolding(isin=r.isin, name=r.name, industry=r.industry, weight=r.weight,
                                    is_equity=r.is_equity) for r in p.rows]
    s.add(d)
    s.flush()
    return {"id": d.id, "fund": inst.name, "kind": kind, "parser": p.amc, "sheet": p.sheet,
            "as_of": p.as_of.isoformat(), "rows": len(p.rows), "equity_weight": str(p.equity_weight),
            "total_weight": str(p.total_weight), "warnings": p.warnings, "replaced_same_month": replaced}


def label(d: FundDisclosure) -> str:
    if d.kind == "INDEX_WEIGHTS":
        return f"approximated from {d.index_name} index weights, as of {d.as_of.isoformat()}"
    return f"AMC portfolio disclosure as of {d.as_of.isoformat()}"


def latest_by_fund(s: Session) -> dict[int, FundDisclosure]:
    """Newest as-of per fund; on the same date the actual AMC disclosure beats index weights."""
    best: dict[int, FundDisclosure] = {}
    for d in s.scalars(select(FundDisclosure)):
        cur = best.get(d.instrument_id)
        key = (d.as_of, d.kind == "AMC_DISCLOSURE")
        if cur is None or key > (cur.as_of, cur.kind == "AMC_DISCLOSURE"):
            best[d.instrument_id] = d
    return best


def fund_rows(d: FundDisclosure) -> list[FundRow]:
    return [FundRow(h.isin, h.name, h.industry, h.weight, h.is_equity) for h in d.holdings]


def list_disclosures(s: Session) -> list[dict]:
    names = {i.id: i.name for i in repo.all_instruments(s)}
    latest = {d.id for d in latest_by_fund(s).values()}
    today = today_ist()
    out = []
    for d in s.scalars(select(FundDisclosure).order_by(FundDisclosure.instrument_id, FundDisclosure.as_of.desc())):
        out.append({"id": d.id, "instrument_id": d.instrument_id, "fund": names.get(d.instrument_id), "kind": d.kind,
                    "as_of": d.as_of.isoformat(), "index_name": d.index_name, "parser": d.parser,
                    "source_file": d.source_file, "uploaded_at": as_utc(d.uploaded_at).isoformat(), "rows": d.rows,
                    "equity_weight": str(d.equity_weight), "label": label(d), "in_use": d.id in latest,
                    "stale": is_stale(d.as_of, today)})
    return out


def delete(s: Session, disclosure_id: int) -> None:
    d = s.get(FundDisclosure, disclosure_id)
    if d is None:
        raise KeyError(disclosure_id)
    s.delete(d)
    s.flush()


def holdings_weights(s: Session) -> dict[int, dict[str, Decimal]]:
    """{fund instrument_id: {equity ISIN: weight}} from the disclosure in use (for the simulator)."""
    out: dict[int, dict[str, Decimal]] = {}
    for fid, d in latest_by_fund(s).items():
        w: dict[str, Decimal] = {}
        for h in d.holdings:
            if h.is_equity and h.isin:
                w[h.isin] = w.get(h.isin, Decimal(0)) + h.weight
        out[fid] = w
    return out
