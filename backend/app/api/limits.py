"""In-process rate limits (one backend instance) and the request size limit.

Buckets (sized for 5-15 people; change here):
- failed sign-ins: at most AUTH_FAIL_LIMIT 401 responses per client IP per window -> then 429 for that IP
  (blunts token guessing; the sign-in email itself is rate-limited by Supabase);
- uploads/imports, AI connection tests, admin invites: per signed-in session.
Keys never store the token: a short hash of the Authorization header, the dev user, or the client IP.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import deque
from dataclasses import dataclass

from starlette.requests import Request


@dataclass(frozen=True)
class Rule:
    name: str
    methods: tuple[str, ...]
    paths: tuple[str, ...]  # exact paths
    limit: int
    window_s: int


RULES = (
    Rule("uploads", ("POST",), ("/api/import", "/api/import/preview", "/api/disclosures"), 20, 600),
    Rule("ai_test", ("POST",), ("/api/llm/test",), 10, 3600),
    Rule("invites", ("POST",), ("/api/admin/invites",), 30, 3600),
)
AUTH_FAIL_LIMIT, AUTH_FAIL_WINDOW_S = 20, 600


class Limiter:
    def __init__(self, clock=time.monotonic):
        self._hits: dict[tuple[str, str], deque] = {}
        self._lock = threading.Lock()
        self._clock = clock

    def _bucket(self, name: str, key: str, window: int) -> deque:
        q = self._hits.setdefault((name, key), deque())
        now = self._clock()
        while q and now - q[0] > window:
            q.popleft()
        return q

    def blocked(self, name: str, key: str, limit: int, window: int) -> int | None:
        """Seconds to wait if the bucket is full, else None (does not record a hit)."""
        with self._lock:
            q = self._bucket(name, key, window)
            return max(1, int(window - (self._clock() - q[0]))) if len(q) >= limit else None

    def hit(self, name: str, key: str, window: int) -> None:
        with self._lock:
            self._bucket(name, key, window).append(self._clock())

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


LIMITER = Limiter()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"  # uvicorn --proxy-headers sets the real client


def session_key(request: Request) -> str:
    auth = request.headers.get("authorization") or request.headers.get("x-dev-user") or ""
    return "s:" + hashlib.sha256(auth.encode()).hexdigest()[:16] if auth else "ip:" + client_ip(request)


def rule_for(request: Request) -> Rule | None:
    for r in RULES:
        if request.method in r.methods and request.url.path in r.paths:
            return r
    return None
