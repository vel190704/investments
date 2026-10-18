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


def route_path(request: Request) -> str:
    """The matched route TEMPLATE (/api/admin/invites/{email}), never the raw path: raw paths can carry emails,
    ids or symbols. Unmatched requests are logged as "<no route>"."""
    route = request.scope.get("route")
    return getattr(route, "path", None) or "<no route>"


def validation_summary(errors: list[dict]) -> list[dict]:
    """Field, message and type only: never the submitted values (they may be journal text)."""
    return [{"loc": ".".join(str(x) for x in e.get("loc", ())), "msg": e.get("msg"), "type": e.get("type")}
            for e in errors]


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",  # the API serves data, never pages
    "Cross-Origin-Resource-Policy": "same-site",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def _secure(response, request: Request) -> None:
    from app.auth import DEV_ENVS, effective_env

    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    if effective_env() not in DEV_ENVS:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")


def _guard(request: Request) -> JSONResponse | None:
    """Size limit and rate limits, before any work is done. Returns the refusal, or None to continue."""
    from app.api.limits import AUTH_FAIL_LIMIT, AUTH_FAIL_WINDOW_S, LIMITER, client_ip, rule_for, session_key
    from app.config import get_settings

    st = get_settings()
    try:
        length = int(request.headers.get("content-length") or 0)
    except ValueError:
        length = 0
    if length > st.max_request_bytes:
        return JSONResponse({"detail": f"Request too large (limit {st.max_request_bytes // (1024 * 1024)} MB)",
                             "request_id": REQUEST_ID.get()}, status_code=413)
    if not st.rate_limits_enabled:
        return None
    wait = LIMITER.blocked("auth_fail", client_ip(request), AUTH_FAIL_LIMIT, AUTH_FAIL_WINDOW_S)
    rule = rule_for(request)
    if wait is None and rule is not None:
        key = session_key(request)
        wait = LIMITER.blocked(rule.name, key, rule.limit, rule.window_s)
        if wait is None:
            LIMITER.hit(rule.name, key, rule.window_s)
    if wait is not None:
        event(log, "rate_limited", logging.WARNING, bucket=rule.name if rule and wait else "auth_fail",
              retry_after_s=wait)
        return JSONResponse({"detail": f"Too many requests; try again in {wait} s", "request_id": REQUEST_ID.get()},
                            status_code=429, headers={"Retry-After": str(wait)})
    return None


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = _rid(request)
        token = REQUEST_ID.set(rid)
        t0 = time.perf_counter()
        try:
            refusal = None if request.url.path in QUIET_PATHS else _guard(request)
            if refusal is not None:
                refusal.headers["X-Request-ID"] = rid
                _secure(refusal, request)
                return refusal
            try:
                response = await call_next(request)
            except Exception as exc:
                from app.observability import capture

                capture(exc, str(getattr(request.state, "user_id", "-")))
                event(log, "http_request", logging.ERROR, exc_info=True, method=request.method,
                      path=route_path(request), status=500, duration_ms=round((time.perf_counter() - t0) * 1000))
                response = JSONResponse({"detail": "Internal server error (see logs/app.log)", "request_id": rid},
                                        status_code=500)
            else:
                status = response.status_code
                level = (logging.ERROR if status >= 500 else logging.WARNING if status >= 400
                         else logging.DEBUG if request.url.path in QUIET_PATHS else logging.INFO)
                log.log(level, "http_request", extra={
                    "user_id": str(getattr(request.state, "user_id", "-")),
                    "fields": {"method": request.method, "path": route_path(request), "status": status,
                               "duration_ms": round((time.perf_counter() - t0) * 1000)}})
            if response.status_code == 401:
                from app.api.limits import AUTH_FAIL_WINDOW_S, LIMITER, client_ip

                LIMITER.hit("auth_fail", client_ip(request), AUTH_FAIL_WINDOW_S)
            response.headers["X-Request-ID"] = rid
            _secure(response, request)
            return response
        finally:
            REQUEST_ID.reset(token)

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(request: Request, exc: RequestValidationError):
        errors = validation_summary(exc.errors())
        event(log, "validation_error", logging.WARNING, method=request.method, path=route_path(request), errors=errors)
        return JSONResponse({"detail": jsonable_encoder(exc.errors()), "request_id": REQUEST_ID.get()},
                            status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def on_http_error(request: Request, exc: StarletteHTTPException):
        if exc.status_code >= 400:
            event(log, "http_error", logging.ERROR if exc.status_code >= 500 else logging.WARNING,
                  method=request.method, path=route_path(request), status=exc.status_code,
                  detail=exc.detail if isinstance(exc.detail, str) else jsonable_encoder(exc.detail))
        return JSONResponse({"detail": exc.detail, "request_id": REQUEST_ID.get()}, status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))


def install_cors(app: FastAPI) -> None:
    """Only the configured frontend origins may call the API from a browser. Bearer tokens, no cookies."""
    from fastapi.middleware.cors import CORSMiddleware

    from app.config import get_settings

    st = get_settings()
    origins = [o.strip().rstrip("/") for o in st.cors_origins.split(",") if o.strip()]
    if "*" in origins:
        raise RuntimeError("CORS_ORIGINS must list exact origins, not *")
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_origin_regex=st.cors_origin_regex or None,
                       allow_credentials=False, allow_methods=["GET", "POST", "PUT", "DELETE"],
                       allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
                       expose_headers=["X-Request-ID", "Content-Disposition", "Retry-After"], max_age=600)
