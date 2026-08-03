"""Pins the trust-tier layout of the HTTP surface.

The tiers are namespacing and accident-avoidance, not authentication: nttd is
self-hosted, so a contestant can reach any prefix. What they buy is that an agent
pointed at /v1/participant has a tool surface which cannot reach deity powers, and
that a new route lands in a tier deliberately rather than by whichever file it was
added to.

This test fails if a dangerous route appears in the participant tier, which is the
mistake the split exists to prevent.

Run with: uv run pytest tests/test_api_tiers.py -v
"""

from __future__ import annotations

from nttd.api.app import app
from nttd.api.tiers import TIER_DESCRIPTIONS, Tier


def _paths() -> set[str]:
    return {route.path for route in app.routes if hasattr(route, "path")}


def _tier_paths(tier: Tier) -> set[str]:
    return {p for p in _paths() if p.startswith(f"{tier.prefix}/")}


def test_all_three_tiers_are_mounted() -> None:
    for tier in Tier:
        assert _tier_paths(tier), f"{tier.prefix} has no routes"


def test_participant_tier_cannot_reach_dangerous_routes() -> None:
    """The property the split exists to guarantee.

    Each of these either mutates the world outside the action log, grants powers a
    human player does not have, or controls the session itself.
    """
    forbidden = (
        "deity",        # change_balance, found_town, create_subsidy, ...
        "rcon",         # arbitrary server console
        "gs/execute",   # bypasses the action allowlist and the action log
        "/save",
        "/load",
        "/settings",
        "/end-conditions",
        "/scenario",
        "/clients",     # kick, move
    )
    participant = _tier_paths(Tier.PARTICIPANT)
    offenders = {
        path for path in participant
        if any(fragment in path for fragment in forbidden)
    }
    assert not offenders, f"dangerous routes in the participant tier: {offenders}"


def test_participant_tier_has_the_gameplay_routes() -> None:
    """Negative tests alone would pass on an empty tier."""
    participant = _tier_paths(Tier.PARTICIPANT)
    for expected in (
        "/actions/submit",
        "/state/compact",
        "/pause",
        "/unpause",
        "/heartbeat/action",
    ):
        assert any(p.endswith(expected) for p in participant), f"missing {expected}"


def test_operator_tier_owns_the_dangerous_routes() -> None:
    operator = _tier_paths(Tier.OPERATOR)
    for expected in ("rcon", "gs/execute", "deity", "/save", "/load"):
        assert any(expected in p for p in operator), f"{expected} is not operator-tier"


def test_public_tier_is_read_only() -> None:
    """A public route must not mutate: no POST, PUT, PATCH, or DELETE."""
    mutating = {"POST", "PUT", "PATCH", "DELETE"}
    offenders: list[str] = []
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith(f"{Tier.PUBLIC.prefix}/"):
            continue
        if mutating & (getattr(route, "methods", None) or set()):
            offenders.append(f"{sorted(getattr(route, 'methods'))} {path}")
    assert not offenders, f"mutating routes in the public tier: {offenders}"


def test_legacy_unprefixed_paths_still_exist() -> None:
    """Existing scenarios, examples, the console, and the CLI depend on these."""
    legacy = {p for p in _paths() if not p.startswith("/v1")}
    for expected in (
        "/sessions/{session_id}/actions/submit",
        "/sessions/{session_id}/status",
        "/admin/sessions/new",
        "/health",
    ):
        assert expected in legacy, f"legacy path {expected} disappeared"


def test_every_tier_is_described_in_openapi() -> None:
    """The descriptions are how an agent reading /docs learns which tier to use."""
    schema = app.openapi()
    described = {tag["name"]: tag["description"] for tag in schema.get("tags", [])}
    for tier in Tier:
        assert tier.tag in described, f"{tier.tag} has no OpenAPI description"
        assert described[tier.tag] == TIER_DESCRIPTIONS[tier]


def test_tier_prefixes_are_distinct() -> None:
    prefixes = [tier.prefix for tier in Tier]
    assert len(set(prefixes)) == len(prefixes)
    assert all(p.startswith("/v1/") for p in prefixes)
