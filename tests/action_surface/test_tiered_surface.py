"""The tier prefix is the only name a route has.

Every router used to be mounted twice: once under its tier and once bare, which gave 73
duplicate paths and 85 operations marked deprecated in the schema. It was never an auth
bypass, since the same router objects served both, so the handlers and their checks were
identical either way.

The harm was subtler. A second name for the whole surface kept a stale client working well
enough to hide that it was stale. nttd-examples posted to /sessions/{id}/actions/submit, which
still resolved, so a runner half worked instead of failing on its first request, and the drift
went unnoticed until the examples were rebuilt. A 404 on the first call is worth more than a
run that half works.

These assert the shim stays gone, since re-adding one include_router is a small edit with a
large effect.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from nttd.api.app import app
from nttd.api.tiers import Tier

# Paths that are not tiered and are not meant to be. /health answers before any session exists
# and is what a container probe hits; the docs are FastAPI's own.
_INFRASTRUCTURE = frozenset({
    "/health", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc",
})

# WebSockets were always mounted once, never duplicated, so they are not part of the shim.
# Untiered all the same, which is worth knowing rather than asserting away.
_WEBSOCKETS = frozenset({"/ws/{session_id}/admin", "/ws/{session_id}/{agent_id}"})

_TIER_PREFIXES = tuple(tier.prefix for tier in Tier)


def _api_paths() -> set[str]:
    paths = {getattr(route, "path", "") for route in app.routes}
    return paths - _INFRASTRUCTURE - _WEBSOCKETS


def test_every_route_is_tier_prefixed() -> None:
    untiered = sorted(p for p in _api_paths() if not p.startswith(_TIER_PREFIXES))
    assert untiered == [], f"untiered paths are back: {untiered}"


def test_no_operation_is_marked_deprecated() -> None:
    """85 of them were. A schema where most of the surface is deprecated tells a reader
    nothing about which half to use."""
    schema = app.openapi()
    deprecated = [
        f"{method.upper()} {path}"
        for path, operations in schema["paths"].items()
        for method, operation in operations.items()
        if isinstance(operation, dict) and operation.get("deprecated")
    ]
    assert deprecated == [], f"deprecated operations are back: {deprecated}"


@pytest.mark.parametrize(
    "path",
    [
        "/admin/sessions",
        "/admin/sessions/new",
        "/sessions/ses_x/state/full",
        "/sessions/ses_x/actions/submit",
        "/sessions/ses_x/step",
    ],
)
def test_an_untiered_path_is_not_served(path: str) -> None:
    """The paths a stale client would use. 404 is the point: it fails on the first call
    rather than on the fifth feature.
    """
    with TestClient(app) as client:
        assert client.get(path).status_code == 404
        assert client.post(path).status_code == 404


def test_the_tiered_equivalent_of_a_removed_path_still_answers() -> None:
    """Guards against the obvious overshoot, removing the route rather than its duplicate."""
    with TestClient(app) as client:
        assert client.get(f"{Tier.OPERATOR.prefix}/admin/sessions").status_code == 200
