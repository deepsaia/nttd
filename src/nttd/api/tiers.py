"""Trust tiers for the HTTP surface.

Routes are grouped into three tiers, exposed as URL prefixes so the boundary is
structural rather than a code-review convention, and visible in /docs so an agent
can see which surface it is meant to touch.

  operator     Provisioning and authoring: session lifecycle, rcon, save/load,
               settings, deity powers, raw GameScript execution. Not gameplay.
  participant  Play: observe, act, step. What a contestant's agent uses.
  public       Read-only: health, status, finished-run artifacts.

What the tiers are NOT
----------------------
They are not an authentication boundary. nttd is self-hosted, so a contestant
already controls the process and can reach any prefix. Requiring a credential on
the operator tier would add setup friction while blocking nobody.

The real protection against a scored run being invalidated is SESSION STATE: a
scored session refuses operator-tier game mutation for every caller regardless of
what they present. See ``nttd.api.scored_lock``.

So the tiers buy discoverability and accident-avoidance: an agent pointed at
/v1/participant has a tool surface that cannot reach deity powers, and a new route
lands in a tier deliberately rather than by whichever file it was added to.
"""

from __future__ import annotations

from enum import StrEnum

V1_PREFIX = "/v1"


class Tier(StrEnum):
    """Trust tier of a route group."""

    OPERATOR = "operator"
    PARTICIPANT = "participant"
    PUBLIC = "public"

    @property
    def prefix(self) -> str:
        """URL prefix for this tier, e.g. ``/v1/participant``."""
        return f"{V1_PREFIX}/{self.value}"

    @property
    def tag(self) -> str:
        """OpenAPI tag, so /docs groups routes by trust rather than by module."""
        return f"{self.value}"


# Human-readable descriptions surfaced in the OpenAPI document.
TIER_DESCRIPTIONS: dict[Tier, str] = {
    Tier.OPERATOR: (
        "Provisioning and scenario authoring: session lifecycle, rcon, save/load, "
        "settings, deity powers, raw GameScript execution. Not gameplay. A scored "
        "session refuses the game-mutating routes here for every caller."
    ),
    Tier.PARTICIPANT: (
        "Gameplay: observe, act, step. The company an action affects is taken from "
        "the participant token, never from the request body."
    ),
    Tier.PUBLIC: "Read-only: health, session status, and finished-run artifacts.",
}
