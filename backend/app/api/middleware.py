"""Request id + per-request logging. Every log line during a request carries its id (logging_config.REQUEST_ID),
and the response returns it as X-Request-ID so the UI can show it next to an error."""

from __future__ import annotations

import logging
import re
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging_config import REQUEST_ID, event

log = logging.getLogger("app.http")
_RID_OK = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
QUIET_PATHS = {"/api/health"}  # polled; logged at DEBUG


def _rid(request: Request) -> str:
    incoming = request.headers.get("x-request-id", "")
    return incoming if _RID_OK.match(incoming) else uuid.uuid4().hex[:12]


def validation_summary(errors: list[dict]) -> list[dict]:
    """Field, message and type only: never the submitted values (they may be journal text)."""
    return [{"loc": ".".join(str(x) for x in e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
            for e in errors]


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = _rid(request)
        token = REQUEST_ID.set(rid)
        t0 = time.perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception:
                event(log, "http_request", logging.ERROR, exc_info=True, method=request.method,
                      path=request.url.path, status=500, duration_ms=round((time.perf_counter() - t0) * 1000))
                response = JSONResponse({"detail": "Internal server error (see logs/app.log)", "request_id": rid},
                                        status_code=500)
            else:
                status = response.status_code
                level = (logging.ERROR if status >= 500 else logging.WARNING if status >= 400
                         else logging.DEBUG if request.url.path in QUIET_PATHS else logging.INFO)
                event(log, "http_request", level, method=request.method, path=request.url.path, status=status,
                      duration_ms=round((time.perf_counter() - t0) * 1000))
            response.headers["X-Request-ID"] = rid
            return response
        finally:
            REQUEST_ID.reset(token)

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(request: Request, exc: RequestValidationError):
        errors = validation_summary(exc.errors())
        event(log, "validation_error", logging.WARNING, method=request.method, path=request.url.path, errors=errors)
        return JSONResponse({"detail": jsonable_encoder(exc.errors()), "request_id": REQUEST_ID.get()},
                            status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def on_http_error(request: Request, exc: StarletteHTTPException):
        if exc.status_code >= 400:
            event(log, "http_error", logging.ERROR if exc.status_code >= 500 else logging.WARNING,
                  method=request.method, path=request.url.path, status=exc.status_code,
                  detail=exc.detail if isinstance(exc.detail, str) else jsonable_encoder(exc.detail))
        return JSONResponse({"detail": exc.detail, "request_id": REQUEST_ID.get()}, status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))
