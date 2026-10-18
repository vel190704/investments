"""Structured log line per outbound call: source, host (never the full URL), status, duration, retries, error class."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from urllib.parse import urlsplit

from app.logging_config import event

log = logging.getLogger("app.outbound")


def host_of(url_or_host: str) -> str:
    return urlsplit(url_or_host).netloc or url_or_host


def scrub(text: str, private: tuple[str, ...]) -> str:
    """Remove private terms (e.g. the ticker being fetched) from error text before it is logged."""
    for term in sorted(filter(None, private), key=len, reverse=True):
        text = text.replace(term, "<security>")
    return text


@contextmanager
def outbound(source: str, url_or_host: str, private: tuple[str, ...] = (), **fields):
    """with outbound("NSE announcements", url) as rec: ... rec["status"] = 200; rec["retries"] = 1
    Logs INFO on success, WARNING (with error class + short message) when the block raises; re-raises."""
    rec: dict = {}
    t0 = time.perf_counter()
    try:
        yield rec
    except Exception as e:
        event(log, "outbound", logging.WARNING, source=source, host=host_of(url_or_host), status=rec.get("status"),
              duration_ms=round((time.perf_counter() - t0) * 1000), retries=rec.get("retries", 0), outcome="error",
              error=type(e).__name__, message=scrub(str(e), private)[:300], **fields, **{k: v for k, v in rec.items()
                                                                         if k not in ("status", "retries")})
        raise
    event(log, "outbound", logging.INFO, source=source, host=host_of(url_or_host), status=rec.get("status"),
          duration_ms=round((time.perf_counter() - t0) * 1000), retries=rec.get("retries", 0),
          outcome=rec.pop("outcome", "ok"), **fields, **{k: v for k, v in rec.items() if k not in ("status", "retries")})
