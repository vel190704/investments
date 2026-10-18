"""One logging configuration for the backend: console + rotating logs/app.log (10 MB x 5).

- Lines are key=value (default) or JSON (LOG_FORMAT=json); level from LOG_LEVEL.
- Every line carries the request id of the HTTP request it belongs to (contextvar; "-" outside requests).
- Structured fields: log.info("event_name", extra={"fields": {...}}) or the `event()` helper.
- Redaction runs on the final formatted line, so messages, fields and tracebacks are all covered:
  API keys, Authorization/x-api-key headers, key/token query parameters and any registered secret value.
- Never log thesis/qualitative text or LLM prompt bodies: log hashes, counts and ids instead.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import re
import sys
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path

from app.timeutil import IST

REQUEST_ID: ContextVar[str] = ContextVar("request_id", default="-")
USER_ID: ContextVar[str] = ContextVar("user_id", default="-")  # internal numeric id; emails are never logged
MAX_BYTES = 10 * 1024 * 1024
BACKUPS = 5
_HANDLER_TAG = "_investments_handler"

_PATTERNS = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{6,}"), "sk-ant-***"),
    (re.compile(r"(?i)\b(authorization)(\"?'?\s*[:=]\s*\"?'?)(bearer\s+)?[^\s\"',;&}]+"), r"\1\2\3***"),
    (re.compile(r"(?i)\b(x-api-key|api[_-]?key|anthropic_api_key|access[_-]?token|secret|password)"
                r"(\"?'?\s*[:=]\s*\"?'?)[^\s\"',;&}]+"), r"\1\2***"),
    (re.compile(r"(?i)([?&](?:key|token|apikey|api_key|access_token|sig|signature)=)[^&\s\"']+"), r"\1***"),
]
_SECRETS: set[str] = set()


def register_secret(value: str | None) -> None:
    """Exact values (e.g. the configured API key) that must never appear in a log line."""
    if value and len(value) >= 8:
        _SECRETS.add(value)


def redact(text: str) -> str:
    for secret in _SECRETS:
        text = text.replace(secret, "***")
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


def _ts(record: logging.LogRecord) -> str:
    return datetime.fromtimestamp(record.created, IST).isoformat(timespec="milliseconds")


def _kv_value(v) -> str:
    s = v if isinstance(v, str) else json.dumps(v, default=str, ensure_ascii=False)
    return json.dumps(s, ensure_ascii=False) if (not s or re.search(r"[\s\"=]", s)) else s


class _Base(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(self._format(record))

    def _format(self, record: logging.LogRecord) -> str:  # pragma: no cover - abstract
        raise NotImplementedError


class KeyValueFormatter(_Base):
    def _format(self, record: logging.LogRecord) -> str:
        parts = [_ts(record), f"level={record.levelname}", f"logger={record.name}",
                 f"rid={getattr(record, 'request_id', REQUEST_ID.get())}",
                 f"uid={getattr(record, 'user_id', USER_ID.get())}", f"msg={_kv_value(record.getMessage())}"]
        for k, v in (getattr(record, "fields", None) or {}).items():
            parts.append(f"{k}={_kv_value(v)}")
        line = " ".join(parts)
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


class JsonFormatter(_Base):
    def _format(self, record: logging.LogRecord) -> str:
        obj = {"ts": _ts(record), "level": record.levelname, "logger": record.name,
               "rid": getattr(record, "request_id", REQUEST_ID.get()),
               "uid": getattr(record, "user_id", USER_ID.get()), "msg": record.getMessage(),
               **(getattr(record, "fields", None) or {})}
        if record.exc_info:
            obj["exc"] = self.formatException(record.exc_info)
        return json.dumps(obj, default=str, ensure_ascii=False)


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = REQUEST_ID.get()
        if not hasattr(record, "user_id"):
            record.user_id = USER_ID.get()
        return True


# third-party loggers that are noisy at INFO (we log the same facts ourselves, once, structured)
QUIET = {"alembic.runtime.plugins": logging.WARNING, "alembic.runtime.migration": logging.WARNING,
         "httpx": logging.WARNING, "httpx2": logging.WARNING, "httpcore": logging.WARNING,
         "yfinance": logging.WARNING, "peewee": logging.WARNING, "apscheduler": logging.WARNING,
         "uvicorn.access": logging.WARNING, "anthropic": logging.WARNING}


def configure_logging(level: str | None = None, fmt: str | None = None, log_dir: Path | None = None,
                      console: bool = True) -> Path | None:
    """Idempotent: replaces only the handlers it installed. Returns the log file path (None if not writable)."""
    from app.config import get_settings

    st = get_settings()
    register_secret(st.anthropic_api_key)
    level = (level or st.log_level or "INFO").upper()
    formatter: logging.Formatter = JsonFormatter() if (fmt or st.log_format) == "json" else KeyValueFormatter()
    root = logging.getLogger()
    for h in [h for h in root.handlers if getattr(h, _HANDLER_TAG, False)]:
        root.removeHandler(h)
        h.close()
    handlers: list[logging.Handler] = []
    if console:
        handlers.append(logging.StreamHandler(sys.stderr))
    path: Path | None = (log_dir or st.log_dir) / "app.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUPS,
                                                             encoding="utf-8"))
    except OSError:
        path = None
    for h in handlers:
        setattr(h, _HANDLER_TAG, True)
        h.setFormatter(formatter)
        h.addFilter(_ContextFilter())
        root.addHandler(h)
    root.setLevel(level)
    for name, lvl in QUIET.items():
        logging.getLogger(name).setLevel(max(lvl, logging.getLevelName(level)))
    for name in ("uvicorn", "uvicorn.error"):  # route uvicorn's own lines through our handlers
        lg = logging.getLogger(name)
        lg.handlers, lg.propagate = [], True
    return path


def event(logger: logging.Logger, name: str, level: int = logging.INFO, exc_info=None, **fields) -> None:
    logger.log(level, name, extra={"fields": fields}, exc_info=exc_info)
