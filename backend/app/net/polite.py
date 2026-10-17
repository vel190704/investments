"""Polite outbound fetching for news and announcement feeds.

- clear User-Agent identifying this personal, single-user tool;
- robots.txt checked for every URL (cached 24 h); disallowed URLs are never fetched;
- at least MIN_INTERVAL seconds between requests to the same host;
- responses cached for CACHE_SECONDS;
- 401/403/429 and network errors become SourceUnavailable (no retries, no evasion).
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


class SourceUnavailable(Exception):
    """The source could not be used; the message is shown to the user."""


@dataclass
class _Cached:
    at: float
    value: object


class PoliteClient:
    def __init__(self, transport: httpx.BaseTransport | None = None, timeout: float = 20.0,
                 min_interval: float = MIN_INTERVAL, sleep=time.sleep, clock=time.monotonic):
        self._client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=timeout, follow_redirects=True,
                                    transport=transport)
        self._robots: dict[str, _Cached] = {}
        self._cache: dict[str, _Cached] = {}
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self._min_interval, self._sleep, self._clock = min_interval, sleep, clock

    def _wait(self, host: str) -> None:
        with self._lock:
            last = self._last.get(host)
            now = self._clock()
            if last is not None and now - last < self._min_interval:
                self._sleep(self._min_interval - (now - last))
            self._last[host] = self._clock()

    def allowed(self, url: str) -> tuple[bool, str]:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        c = self._robots.get(base)
        if c is None or self._clock() - c.at > ROBOTS_SECONDS:
            rp = urllib.robotparser.RobotFileParser()
            self._wait(parts.netloc)
            try:
                r = self._client.get(base + "/robots.txt")
            except httpx.HTTPError as e:
                raise SourceUnavailable(f"Source unavailable ({parts.netloc}: {type(e).__name__})") from None
            if r.status_code in (401, 403):
                rp.disallow_all = True  # robots.txt itself is refused -> treat as not permitted
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
        self._wait(host)
        try:
            r = self._client.get(url)
        except httpx.HTTPError as e:
            raise SourceUnavailable(f"Source unavailable ({host}: {type(e).__name__})") from None
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
        _default = PoliteClient()
    return _default
