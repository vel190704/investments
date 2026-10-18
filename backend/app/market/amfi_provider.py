"""Mutual-fund NAVs from AMFI NAVAll.txt. Needs a confirmed scheme code."""

from __future__ import annotations

from app.market.base import FetchError, InstrumentRef, Quote
from app.resolve.sources import amfi_schemes
from app.timeutil import utcnow

SOURCE = "AMFI NAVAll.txt"


class AmfiNavProvider:
    name = SOURCE

    def __init__(self, loader=amfi_schemes):
        self._loader = loader

    def supports(self, ref: InstrumentRef) -> bool:
        return ref.asset_type == "MF"

    def fetch(self, refs: list[InstrumentRef]) -> dict[int, Quote | FetchError]:
        out: dict[int, Quote | FetchError] = {}
        todo = []
        for r in refs:
            if not r.scheme_code:
                out[r.security_id] = FetchError("scheme code not confirmed yet (see Mappings)")
            else:
                todo.append(r)
        if not todo:
            return out
        try:
            schemes, _ = self._loader(max_age_hours=1)
        except Exception as e:
            return {**out, **{r.security_id: FetchError(f"AMFI download failed: {e}") for r in todo}}
        for r in todo:
            s = schemes.get(r.scheme_code)
            if s is None or s.nav is None or s.nav_date is None:
                out[r.security_id] = FetchError(f"scheme {r.scheme_code} has no NAV in NAVAll.txt")
            else:
                out[r.security_id] = Quote(price=s.nav, price_date=s.nav_date, source=SOURCE,
                                             source_ref=r.scheme_code, fetched_at=utcnow())
        return out
