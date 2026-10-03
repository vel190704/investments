"""Create PENDING identifier candidates for instruments that lack a confirmed ISIN / scheme code."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import repository as repo
from app.models import IdentifierCandidate, Instrument
from app.resolve.matching import scheme_matches
from app.resolve.sources import amfi_schemes, nse_securities
from app.timeutil import utcnow


def _has_confirmed(cands: list[IdentifierCandidate], kind: str) -> bool:
    return any(c.kind == kind and c.status == "CONFIRMED" for c in cands)


def _upsert(s: Session, inst: Instrument, kind: str, value: str, label: str, source: str, score: float,
            details: dict) -> bool:
    c = repo.find_candidate(s, inst.id, kind, value)
    if c is None:
        s.add(IdentifierCandidate(instrument_id=inst.id, kind=kind, value=value, label=label, source=source,
                                  score=score, details=details, status="PENDING"))
        return True
    c.label, c.source, c.score, c.details = label, source, score, details
    return False


def resolve_identifiers(s: Session) -> dict:
    instruments = repo.all_instruments(s)
    created, errors = 0, []
    needs_isin = [i for i in instruments if i.asset_type in ("STOCK", "ETF")
                  and not _has_confirmed(repo.candidates(s, i.id), "ISIN")]
    needs_scheme = [i for i in instruments if i.asset_type == "MF"
                    and not _has_confirmed(repo.candidates(s, i.id), "SCHEME_CODE")]
    if needs_isin:
        try:
            nse, fetched = nse_securities()
            for inst in needs_isin:
                sec = nse.get((inst.symbol or "").upper())
                if sec is None:
                    errors.append(f"{inst.symbol}: not found in NSE securities lists")
                    continue
                created += _upsert(s, inst, "ISIN", sec.isin, f"{sec.symbol} — {sec.name}",
                                   f"NSE {'ETF' if sec.kind == 'ETF' else 'equity'} list", 1.0,
                                   {"exact_symbol_match": True, "nse_name": sec.name, "kind": sec.kind,
                                    "underlying": sec.underlying, "list_fetched_at": fetched.isoformat()})
        except Exception as e:
            errors.append(f"NSE securities lists unavailable: {e}")
    if needs_scheme:
        try:
            schemes, fetched = amfi_schemes()
            for inst in needs_scheme:
                matches = scheme_matches(inst.name, schemes)
                if not matches:
                    errors.append(f"{inst.name}: no AMFI scheme with the same plan/option matched")
                for sch, score in matches:
                    created += _upsert(s, inst, "SCHEME_CODE", sch.scheme_code, sch.name, "AMFI NAVAll.txt", score,
                                       {"isin_growth": sch.isin_growth, "fund_house": sch.fund_house,
                                        "plan": sch.plan, "option": sch.option,
                                        "nav": str(sch.nav) if sch.nav else None,
                                        "nav_date": sch.nav_date.isoformat() if sch.nav_date else None,
                                        "list_fetched_at": fetched.isoformat()})
        except Exception as e:
            errors.append(f"AMFI NAVAll.txt unavailable: {e}")
    s.flush()
    pending = sum(1 for c in repo.candidates(s) if c.status == "PENDING")
    return {"created": created, "errors": errors, "pending": pending,
            "summary": f"{created} new candidate(s), {pending} awaiting confirmation"
                       + (f", {len(errors)} problem(s): " + "; ".join(errors) if errors else "")}


def decide(s: Session, candidate_id: int, confirm: bool) -> IdentifierCandidate:
    c = repo.get_candidate(s, candidate_id)
    if c is None:
        raise KeyError(candidate_id)
    inst = repo.get_instrument(s, c.instrument_id)
    now = utcnow()
    if confirm:
        # one confirmed value per kind: other candidates of that kind become REJECTED
        for other in repo.candidates(s, c.instrument_id):
            if other.kind == c.kind and other.id != c.id and other.status != "REJECTED":
                other.status, other.decided_at = "REJECTED", now
        c.status, c.decided_at = "CONFIRMED", now
        if c.kind == "ISIN":
            inst.isin = c.value
        else:
            inst.scheme_code = c.value
            if not inst.isin and c.details.get("isin_growth"):
                inst.isin = c.details["isin_growth"]
    else:
        was_confirmed = c.status == "CONFIRMED"
        c.status, c.decided_at = "REJECTED", now
        if was_confirmed:
            if c.kind == "ISIN" and inst.isin == c.value:
                inst.isin = None
            if c.kind == "SCHEME_CODE" and inst.scheme_code == c.value:
                inst.scheme_code = None
    s.flush()
    return c
