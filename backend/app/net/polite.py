"""Polite outbound fetching for news and announcement feeds.

- clear User-Agent identifying this personal, single-user tool;
- robots.txt checked for every URL (cached 24 h); disallowed URLs are never fetched;
- at least MIN_INTERVAL seconds between requests to the same host;
- responses cached for CACHE_SECONDS;
- per-host read timeout (default 25 s; SOURCE_TIMEOUT_SECONDS / SOURCE_TIMEOUTS in .env);
- timeouts, connection errors and 502/503/504 are retried ONCE after RETRY_BACKOFF seconds;
- 401/403/429 are never retried (that would be evading a block); they become SourceUnavailable.
"""

from __future__ import annotations

import threading
import time
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

USER_AGENT = "personal-portfolio-dashboard/0.4 (single-user, local; respects robots.txt)"
MIN_INTERVAL = 2.0
CACHE_SECONDS = 30 * 60
ROBOTS_SECONDS = 24 * 3600
DOWN_SECONDS = 10 * 60  # after a network failure, skip that host for this long (no hammering a slow server)
DEFAULT_TIMEOUT = 25.0
RETRY_BACKOFF = 5.0
RETRY_STATUSES = {502, 503, 504}


class SourceUnavailable(Exception):
    """The source could not be used; the message is shown to the user."""


@dataclass
class _Cached:
    at: float
    value: object


class PoliteClient:
    def __init__(self, transport: httpx.BaseTransport | None = None, timeout: float = DEFAULT_TIMEOUT,
                 min_interval: float = MIN_INTERVAL, sleep=time.sleep, clock=time.monotonic,
                 host_timeouts: dict[str, float] | None = None):
        self._client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True,
                                    transport=transport)
        self._default_timeout = float(timeout)
        self._host_timeouts = {h: float(t) for h, t in (host_timeouts or {}).items()}
        self._robots: dict[str, _Cached] = {}
        self._cache: dict[str, _Cached] = {}
        self._last: dict[str, float] = {}
        self._down: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()
        self._min_interval, self._sleep, self._clock = min_interval, sleep, clock

    @classmethod
    def from_settings(cls, settings=None, **kw) -> PoliteClient:
        from app.config import get_settings

        st = settings or get_settings()
        return cls(timeout=st.source_timeout_seconds, host_timeouts=st.source_timeouts, **kw)

    def _get(self, url: str, host: str) -> httpx.Response:
        """One polite GET with a single retry (after RETRY_BACKOFF) on timeouts, connection errors and 502/503/504.
        Raises SourceUnavailable and marks the host down when both attempts fail."""
        timeout = self._host_timeouts.get(host, self._default_timeout)
        last = ""
        for attempt in (1, 2):
            if attempt == 2:
                self._sleep(RETRY_BACKOFF)
            self._wait(host)
            try:
                r = self._client.get(url, timeout=timeout)
            except httpx.TransportError as e:
                last = type(e).__name__
                continue
            if r.status_code in RETRY_STATUSES:
                last = f"HTTP {r.status_code}"
                continue
            return r
        raise self._mark_down(host, f"Source unavailable ({host}: {last} after 2 attempts, timeout {timeout:g}s)")

    def _wait(self, host: str) -> None:
        with self._lock:
            last = self._last.get(host)
            now = self._clock()
            if last is not None and now - last < self._min_interval:
                self._sleep(self._min_interval - (now - last))
            self._last[host] = self._clock()

    def _check_down(self, host: str) -> None:
        d = self._down.get(host)
        if d and self._clock() - d[0] < DOWN_SECONDS:
            raise SourceUnavailable(d[1] + " (skipped: host failed recently)")

    def _mark_down(self, host: str, message: str) -> SourceUnavailable:
        self._down[host] = (self._clock(), message)
        return SourceUnavailable(message)

    def allowed(self, url: str) -> tuple[bool, str]:
        parts = urlsplit(url)
        self._check_down(parts.netloc)
        base = f"{parts.scheme}://{parts.netloc}"
        c = self._robots.get(base)
        if c is None or self._clock() - c.at > ROBOTS_SECONDS:
            rp = urllib.robotparser.RobotFileParser()
            r = self._get(base + "/robots.txt", parts.netloc)
            if r.status_code in (401, 403):
                rp.disallow_all = True  # robots.txt itself is refused to an identified client -> not permitted
            elif r.status_code >= 400:
                rp.allow_all = True  # no robots.txt -> allowed
            else:
                rp.parse(r.text.splitlines())
            c = _Cached(self._clock(), rp)
            self._robots[base] = c
        ok = c.value.can_fetch(USER_AGENT, url)
        return ok, "" if ok else f"Source unavailable (robots.txt of {parts.netloc} disallows automated access)"

    def get_text(self, url: str) -> str:
        hit = self._cache.get(url)
        if hit and self._clock() - hit.at < CACHE_SECONDS:
            return hit.value
        ok, why = self.allowed(url)
        if not ok:
            raise SourceUnavailable(why)
        host = urlsplit(url).netloc
        r = self._get(url, host)
        if r.status_code in (401, 403, 429):
            raise SourceUnavailable(f"Source unavailable ({host} answered HTTP {r.status_code}; not retried)")
        if r.status_code >= 400:
            raise SourceUnavailable(f"Source unavailable ({host} answered HTTP {r.status_code})")
        self._cache[url] = _Cached(self._clock(), r.text)
        return r.text


_default: PoliteClient | None = None


def default_client() -> PoliteClient:
    global _default
    if _default is None:
        _default = PoliteClient.from_settings()
    return _default
