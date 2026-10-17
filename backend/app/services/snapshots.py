"""Daily portfolio snapshots (one per IST date, upserted) and snapshot comparisons."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calc.changes import HoldingView, compare, diff_allocation
from app.models import PortfolioSnapshot, SnapshotAssetClass, SnapshotHolding
from app.services import changelog
from app.services.portfolio import load_rows
from app.timeutil import as_utc, today_ist


def _weights(classes: dict[str, int], total: int) -> dict[str, Decimal]:
    return {c: (Decimal(v) / total if total else Decimal(0)) for c, v in classes.items()}


def take_snapshot(s: Session, trigger: str = "manual", on_date: date | None = None) -> dict | None:
    """Upsert the snapshot for `on_date` (default: today IST). Returns None when there is no data."""
    rows, _ = load_rows(s)
    if not rows:
        return None
    on_date = on_date or today_ist()
    snap = s.scalar(select(PortfolioSnapshot).where(PortfolioSnapshot.snapshot_date == on_date))
    if snap is None:
        snap = PortfolioSnapshot(snapshot_date=on_date, total_value_paise=0, total_invested_paise=0,
                                 invested_priced_paise=0, trigger=trigger)
        s.add(snap)
    else:
        snap.asset_classes.clear()
        snap.holdings.clear()
        s.flush()

    priced = [r for r in rows if r.value_paise is not None]
    snap.trigger = trigger
    snap.total_value_paise = sum(r.value_paise for r in priced)
    snap.total_invested_paise = sum(r.pos.invested_paise for r in rows)
    snap.invested_priced_paise = sum(r.pos.invested_paise for r in priced)
    snap.unpriced = [r.inst.name for r in rows if r.value_paise is None]

    classes: dict[str, list[int]] = {}
    for r in rows:
        c = classes.setdefault(r.asset_class, [0, 0])
        c[0] += r.value_paise or 0
        c[1] += r.pos.invested_paise
        snap.holdings.append(SnapshotHolding(
            instrument_id=r.inst.id, asset_class=r.asset_class, quantity=r.pos.quantity, avg_cost=r.pos.avg_cost,
            invested_paise=r.pos.invested_paise, price=r.quote.price if r.quote else None,
            price_date=r.quote.price_date if r.quote else None, price_source=r.quote.source if r.quote else None,
            value_paise=r.value_paise,
        ))
    for name, (v, inv) in classes.items():
        snap.asset_classes.append(SnapshotAssetClass(asset_class=name, value_paise=v, invested_paise=inv))
    s.flush()

    prev = s.scalar(select(PortfolioSnapshot).where(PortfolioSnapshot.snapshot_date < on_date)
                    .order_by(PortfolioSnapshot.snapshot_date.desc()).limit(1))
    logged = 0
    if prev is not None:
        before = _weights({c.asset_class: c.value_paise for c in prev.asset_classes}, prev.total_value_paise)
        after = _weights({c: v[0] for c, v in classes.items()}, snap.total_value_paise)
        entries = diff_allocation(before, after)
        for e in entries:
            e["summary"] += f" (snapshot {prev.snapshot_date.isoformat()} → {on_date.isoformat()})"
        changelog.replace_allocation_entries(s, on_date, entries)
        logged = len(entries)
    return {"snapshot_date": on_date.isoformat(), "total_value_paise": snap.total_value_paise,
            "partial": bool(snap.unpriced), "unpriced": snap.unpriced, "allocation_changes_logged": logged}


def snapshot_dict(p: PortfolioSnapshot) -> dict:
    return {
        "snapshot_date": p.snapshot_date.isoformat(), "total_value_paise": p.total_value_paise,
        "total_invested_paise": p.total_invested_paise, "invested_priced_paise": p.invested_priced_paise,
        "partial": bool(p.unpriced), "unpriced": p.unpriced, "trigger": p.trigger,
        "updated_at": as_utc(p.updated_at).isoformat(),
        "asset_classes": [{"asset_class": c.asset_class, "value_paise": c.value_paise,
                           "invested_paise": c.invested_paise} for c in p.asset_classes],
    }


def list_snapshots(s: Session) -> list[PortfolioSnapshot]:
    return list(s.scalars(select(PortfolioSnapshot).order_by(PortfolioSnapshot.snapshot_date)))


def series(s: Session) -> dict:
    """Snapshot points plus explicit gap points (value None) for dates the app was not running."""
    from app.models import SnapshotGap

    snaps = list_snapshots(s)
    pts = [{"date": p.snapshot_date.isoformat(), "value_paise": p.total_value_paise,
            "invested_paise": p.total_invested_paise, "invested_priced_paise": p.invested_priced_paise,
            "partial": bool(p.unpriced), "unpriced": p.unpriced, "gap": False} for p in snaps]
    have = {p["date"] for p in pts}
    gaps = [g for g in s.scalars(select(SnapshotGap).order_by(SnapshotGap.gap_date)) if g.gap_date.isoformat() not in have]
    pts += [{"date": g.gap_date.isoformat(), "value_paise": None, "invested_paise": None, "invested_priced_paise": None,
             "partial": False, "unpriced": [], "gap": True, "reason": g.reason} for g in gaps]
    pts.sort(key=lambda p: p["date"])
    return {
        "points": pts, "gaps": [g.gap_date.isoformat() for g in gaps],
        "enough_history": len(snaps) >= 2,  # gaps never count as history
        "note": None if len(snaps) >= 2 else
        "History builds from today: one snapshot is stored per day after each price refresh. "
        "No earlier history is estimated or back-filled.",
    }


def _views_from_snapshot(p: PortfolioSnapshot, names: dict[int, str]) -> list[HoldingView]:
    return [HoldingView(h.instrument_id, names.get(h.instrument_id, str(h.instrument_id)), h.asset_class,
                        h.quantity, h.avg_cost, h.invested_paise, h.value_paise) for h in p.holdings]


def _live_views(s: Session) -> list[HoldingView]:
    rows, _ = load_rows(s)
    return [HoldingView(r.inst.id, r.inst.symbol or r.inst.name, r.asset_class, r.pos.quantity, r.pos.avg_cost,
                        r.pos.invested_paise, r.value_paise) for r in rows]


def compare_states(s: Session, a: str, b: str) -> dict:
    """a, b: 'YYYY-MM-DD' snapshot dates or 'live' (current state). Raises KeyError for a missing date."""
    from app.models import Instrument

    names = {i.id: i.symbol or i.name for i in s.scalars(select(Instrument))}

    def load(ref: str) -> tuple[list[HoldingView], str]:
        if ref == "live":
            return _live_views(s), "live (current holdings at latest cached prices)"
        snap = s.scalar(select(PortfolioSnapshot).where(PortfolioSnapshot.snapshot_date == date.fromisoformat(ref)))
        if snap is None:
            raise KeyError(ref)
        return _views_from_snapshot(snap, names), f"snapshot {ref}" + (" (partial)" if snap.unpriced else "")

    va, la = load(a)
    vb, lb = load(b)
    return {"a": a, "b": b, "label_a": la, "label_b": lb, **compare(va, vb)}
