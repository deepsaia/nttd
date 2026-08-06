"""The action vocabulary, as enums an MCP client receives in the tool schema.

This is the answer to the obvious objection to a small tool surface. Collapsing 120
actions into one ``nttd_act`` tool would be hiding them if the client had to be told the
names in a prompt: a model would guess, and guessing at ``build_road_stop`` versus
``build_road_station`` fails in a way that looks like the game refusing a legal move.

It does not have to be told. ``action_type`` is typed as an enum here, so every name
arrives inside the tool's JSON schema, where the client already looks. A name that is not
in the manifest cannot be sent, and one that is needs no prompt to discover.

Two enums rather than one, because the two verbs take different vocabularies: an
observation is not something to submit as a move, and a move is not something to read.
Operator actions are in neither, since no session can run one.
"""

from __future__ import annotations

from enum import StrEnum

from nttd.config import action_manifest


def _names(tier: str) -> dict[str, str]:
    """Action names of one tier, as enum members keyed by themselves."""
    return {
        name: name
        for name, entry in sorted(action_manifest.ACTIONS.items())
        if entry.get("tier") == tier
    }


# Built at import from the manifest, so adding an action to the GameScript and
# regenerating is the whole of exposing it over MCP. A hand-kept list here would be the
# same defect the manifest replaced, one layer up.
PlayableAction = StrEnum("PlayableAction", _names("participant"))
ObservationAction = StrEnum("ObservationAction", _names("read_only"))
