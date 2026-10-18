"""Polite client: per-source timeout, one retry with backoff, skip window, never evading blocks."""

import httpx
import pytest

from app.net import polite
from app.net.polite import PoliteClient, SourceUnavailable

FEED = "https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml"


class Clock:
    def __init__(self):
        self.t = 1000.0
        self.slept: list[float] = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(round(s, 3))
        self.t += s


def client(handler, clock, **kw):
    return PoliteClient(transport=httpx.MockTransport(handler), sleep=clock.sleep, clock=clock.now, **kw)


def feed_handler(script):
    """script: list of 'timeout' | int status, consumed per feed request; robots.txt is always allowed."""
    calls = {"feed": 0, "timeouts": []}

    def h(req: httpx.Request):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        step = script[min(calls["feed"], len(script) - 1)]
        calls["feed"] += 1
        calls["timeouts"].append(req.extensions["timeout"]["read"])
        if step == "timeout":
            raise httpx.ReadTimeout("read timed out", request=req)
        return httpx.Response(step, text="<rss/>")
    return h, calls


def test_default_timeout_is_25s_and_per_host_override():
    clock = Clock()
    h, calls = feed_handler([200])
    c = client(h, clock)
    c.get_text(FEED)
    assert calls["timeouts"] == [25.0]
    h, calls = feed_handler([200])
    c = client(h, clock, host_timeouts={"nsearchives.nseindia.com": 40.0})
    c.get_text(FEED)
    assert calls["timeouts"] == [40.0]


def test_read_timeout_is_retried_once_with_backoff():
    clock = Clock()
    h, calls = feed_handler(["timeout", 200])
    c = client(h, clock)
    assert c.get_text(FEED) == "<rss/>"
    assert calls["feed"] == 2
    assert polite.RETRY_BACKOFF in clock.slept


def test_two_timeouts_fail_and_the_host_is_skipped_for_the_window():
    clock = Clock()
    h, calls = feed_handler(["timeout", "timeout"])
    c = client(h, clock)
    with pytest.raises(SourceUnavailable, match="ReadTimeout after 2 attempts"):
        c.get_text(FEED)
    assert calls["feed"] == 2
    with pytest.raises(SourceUnavailable, match="skipped: host failed recently"):
        c.get_text(FEED.replace("Online", "Board"))
    assert calls["feed"] == 2  # no network call inside the skip window
    clock.t += polite.DOWN_SECONDS + 1
    h2, calls2 = feed_handler([200])
    c._client = httpx.Client(transport=httpx.MockTransport(h2))
    assert c.get_text(FEED) == "<rss/>"


@pytest.mark.parametrize("status", [401, 403, 429])
def test_blocking_answers_are_never_retried(status):
    clock = Clock()
    h, calls = feed_handler([status, 200])
    c = client(h, clock)
    with pytest.raises(SourceUnavailable, match="not retried"):
        c.get_text(FEED)
    assert calls["feed"] == 1


def test_server_errors_503_are_retried_once():
    clock = Clock()
    h, calls = feed_handler([503, 200])
    assert client(h, clock).get_text(FEED) == "<rss/>"
    assert calls["feed"] == 2


def test_timeouts_come_from_settings(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("SOURCE_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("SOURCE_TIMEOUTS", '{"nsearchives.nseindia.com": 45}')
    get_settings.cache_clear()
    try:
        c = polite.PoliteClient.from_settings()
        assert c._default_timeout == 12.0 and c._host_timeouts == {"nsearchives.nseindia.com": 45.0}
    finally:
        get_settings.cache_clear()
