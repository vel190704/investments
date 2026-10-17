"""Monthly update page: data for the pure checklist."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import repository as repo
from app.calc.monthly import checklist, month_bounds
from app.models import ImportRun, PortfolioSnapshot, PriceQuote, Transaction
from app.timeutil import IST, as_utc, today_ist, utcnow


def monthly_update(s: Session) -> dict:
    today = today_ist()
    start, end = month_bounds(today)
    insts = {i.id: i for i in repo.all_instruments(s)}
    plan = [{"instrument_id": p.instrument_id, "name": insts[p.instrument_id].name,
             "monthly_amount_paise": p.monthly_amount_paise}
            for p in repo.plan_items(s) if p.instrument_id and not p.is_bucket and p.instrument_id in insts]
    txns = [{"instrument_id": t.instrument_id, "asset_type": insts[t.instrument_id].asset_type, "type": t.type,
             "date": t.date} for t in s.scalars(select(Transaction).where(Transaction.date >= start, Transaction.date <= end))]
    last = s.scalar(select(ImportRun).where(ImportRun.ok.is_(True)).order_by(ImportRun.id.desc()).limit(1))
    last_import = {"ok": True, "date": as_utc(last.started_at).astimezone(IST).date()} if last else None
    fetched = s.scalar(select(func.max(PriceQuote.fetched_at)))
    snap = s.scalar(select(PortfolioSnapshot.id).where(PortfolioSnapshot.snapshot_date == today)) is not None
    out = checklist(today, utcnow(), plan, txns, last_import, as_utc(fetched), snap)
    out["plan"] = [{"name": p["name"], "monthly_amount_paise": p["monthly_amount_paise"]} for p in plan]
    out["how_to"] = [
        "In Coin, open each SIP order for this month and note the units allotted and the NAV.",
        "Add a row to the transactions sheet: date, SIP, MF, the fund name exactly as before, units, NAV, amount.",
        "Or use Transactions › Add transaction in the app (kept as an in-app entry; never removed by an import).",
        "Import the workbook: the preview shows rows to add/remove before you confirm.",
    ]
    return out
