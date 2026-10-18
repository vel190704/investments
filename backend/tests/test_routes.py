"""Route table hygiene: no static path may be shadowed by an earlier dynamic one."""

import re

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import db
from app.main import app

PARAM = re.compile(r"{([^}:]+)(?::([^}]+))?}")


def _sample(path: str) -> str:
    """A concrete URL for a route template: int params -> 7, others -> 'sample'."""
    return PARAM.sub(lambda m: "7" if m.group(2) == "int" else "a/b" if m.group(2) == "path" else "sample", path)


def _regex(path: str) -> str:
    """Starlette's matching rule for a template: int -> digits, path -> anything, default -> one segment."""
    parts = re.split(r"({[^}]+})", path)
    conv = {"int": "[0-9]+", "path": ".*", "float": "[0-9]+(?:\\.[0-9]+)?"}
    return "".join(conv.get(PARAM.fullmatch(p).group(2), "[^/]+") if PARAM.fullmatch(p) else re.escape(p) for p in parts)


def flat_routes(routes, prefix: str = "") -> list[tuple[str, APIRoute]]:
    """(full path, route) in matching order; FastAPI >= 0.140 nests included routers lazily."""
    out = []
    for r in routes:
        if isinstance(r, APIRoute):
            out.append((prefix + r.path, r))
        elif hasattr(r, "original_router"):
            out += flat_routes(r.original_router.routes, prefix + r.include_context.prefix)
    return out


def shadowed_routes(routes) -> list[str]:
    api = flat_routes(routes)
    assert api, "no API routes found: the route walker no longer understands this FastAPI version"
    out = []
    for j, (lpath, later) in enumerate(api):
        url = _sample(lpath)
        for epath, earlier in api[:j]:
            if epath == lpath or "{" not in epath or not (earlier.methods & later.methods):
                continue
            if re.fullmatch(_regex(epath), url):
                out.append(f"{sorted(later.methods & earlier.methods)} {lpath} is shadowed by earlier {epath}")
    return out


def test_no_route_is_shadowed_by_an_earlier_dynamic_route():
    assert shadowed_routes(app.routes) == []


def test_shadow_detector_catches_the_portfolio_case():
    from fastapi import APIRouter

    r = APIRouter()
    r.post("/analysis/{iid}")(lambda iid: None)
    r.post("/analysis/portfolio")(lambda: None)
    assert shadowed_routes(r.routes) == ["['POST'] /analysis/portfolio is shadowed by earlier /analysis/{iid}"]


def test_int_path_params_are_typed_in_the_template():
    """Every *id path parameter uses the :int convertor, so words like 'portfolio' never match it."""
    untyped = [p for p, _ in flat_routes(app.routes) for name, conv in PARAM.findall(p)
               if name.endswith("id") and conv != "int"]
    assert untyped == []


def test_portfolio_analysis_routes_reach_their_handlers(tmp_path):
    db.configure(f"sqlite:///{tmp_path / 'r.db'}")
    with TestClient(app) as c:
        # Path-parameter validation errors carry a list detail naming "iid"; the handler's own errors are strings.
        for r in (c.post("/api/analysis/portfolio"), c.get("/api/analysis/portfolio/preview")):
            assert isinstance(r.json()["detail"], str), r.text
            assert r.json()["detail"] == "No priced holdings yet"
