"""Monthly-routine checklist (pure). Every tick is derived from data, never from a manual checkbox."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from app.timeutil import IST


def month_bounds(today: date) -> tuple[date, date]:
    start = today.replace(day=1)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start, nxt - timedelta(days=1)


def checklist(today: date, now: datetime, plan_funds: list[dict], month_txns: list[dict],
              last_import: dict | None, last_price_fetch: datetime | None, snapshot_today: bool) -> dict:
    """plan_funds: [{instrument_id, name, monthly_amount_paise}] from monthly_plan (MF rows linked to holdings);
    month_txns: [{instrument_id, asset_type, type, date}] dated in the current month."""
    start, end = month_bounds(today)
    sip_ids = {t["instrument_id"] for t in month_txns if t["type"] in ("SIP", "BUY")}
    missing = [f for f in plan_funds if f["instrument_id"] not in sip_ids]
    stock_buys = [t for t in month_txns if t["asset_type"] in ("STOCK", "ETF") and t["type"] in ("BUY", "SIP")]
    imported = bool(last_import and last_import["ok"] and start <= last_import["date"] <= today)
    fresh = bool(last_price_fetch and now - last_price_fetch <= timedelta(hours=24))
    items = [
        {"key": "sip_rows", "title": "Add this month's SIP rows (units and NAV from Coin; amount is authoritative)",
         "done": not missing and bool(plan_funds),
         "detail": ("All planned funds have a SIP/BUY row this month." if not missing and plan_funds else
                    "No funds in monthly_plan." if not plan_funds else
                    "Missing this month: " + ", ".join(f["name"] for f in missing))},
        {"key": "stock_buys", "title": "Add any new stock/ETF buys", "done": bool(stock_buys),
         "detail": f"{len(stock_buys)} stock/ETF buy row(s) dated this month." if stock_buys else
         "No stock/ETF buys recorded this month (fine if you made none)."},
        {"key": "import", "title": "Import the updated workbook (preview, then confirm)", "done": imported,
         "detail": f"Last successful import: {last_import['date'].isoformat()}" if last_import else "No import yet."},
        {"key": "prices", "title": "Refresh prices and NAVs", "done": fresh,
         "detail": f"Last price fetch: {last_price_fetch.astimezone(IST):%d %b %Y, %H:%M} IST" if last_price_fetch else "Prices never fetched."},
        {"key": "snapshot", "title": "Take today's snapshot", "done": snapshot_today,
         "detail": "Stored." if snapshot_today else "No snapshot for today yet (one is stored after each refresh)."},
    ]
    warnings = [f"{f['name']}: no SIP row dated {start.strftime('%B %Y')} yet." for f in missing]
    return {"month": start.strftime("%B %Y"), "from": start.isoformat(), "to": end.isoformat(), "items": items,
            "warnings": warnings, "done": sum(1 for i in items if i["done"]), "total": len(items)}
