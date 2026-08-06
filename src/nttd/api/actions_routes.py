"""Publishes the action manifest: what nttd can do, and what each action takes.

Public tier, and deliberately so. This is static reference data about the build rather
than anything belonging to a session, so it answers before a session exists, which is
when an agent most wants it: deciding what it is able to do is not something to discover
one refusal at a time.

The same content is printed by ``nttd actions`` and written to ``docs/actions/``. This is
the one an agent should use. Markdown costs tokens to parse and invites the parsing to be
approximate; here the shape is already structured, and the accepted constants come with
it.

Operator actions are excluded by default. No session can run one, so returning them by
default would hand every caller nine actions that only ever fail. They are not hidden:
the reply says how many were left out and how to ask for them.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from nttd.config import action_manifest

logger = logging.getLogger(__name__)
router = APIRouter(tags=["actions"])

_OPERATOR_NOTE = (
    "Operator actions are excluded: no session can run one, and a scored session refuses "
    "them for every caller. Pass tier=operator to see them."
)


@router.get("/actions")
async def list_actions(
    tier: Annotated[
        str | None,
        Query(description="participant, read_only or operator. Default: all but operator."),
    ] = None,
    category: Annotated[str | None, Query(description="rail, road, order, query, ...")] = None,
) -> dict[str, Any]:
    """Every action nttd can run, with its parameters and their accepted values.

    Generated from the GameScript, so it cannot describe an action the game does not
    implement or miss one it does.
    """
    entries = action_manifest.ACTIONS
    if tier is not None:
        entries = {n: e for n, e in entries.items() if e["tier"] == tier}
    else:
        entries = {n: e for n, e in entries.items() if e["tier"] != "operator"}
    if category is not None:
        entries = {n: e for n, e in entries.items() if e["category"] == category}

    manifest = action_manifest.manifest()
    body: dict[str, Any] = {
        "manifest_version": manifest.get("manifest_version"),
        "generated_from": manifest.get("generated_from"),
        "enum_values_from": manifest.get("enum_values_from"),
        "count": len(entries),
        "actions": entries,
    }
    if tier is None:
        excluded = sum(
            1 for e in action_manifest.ACTIONS.values() if e["tier"] == "operator"
        )
        body["excluded"] = {"tier": "operator", "count": excluded, "reason": _OPERATOR_NOTE}
    return body


@router.get("/actions/{action_type}")
async def get_action(action_type: str) -> dict[str, Any]:
    """One action in full: parameters, types, defaults, alternatives and constants."""
    entry = action_manifest.ACTIONS.get(action_type)
    if entry is None:
        # Naming the nearest few beats a bare 404: an agent that mistyped an action can
        # correct it without fetching the whole manifest to find out what it meant.
        raise HTTPException(
            status_code=404,
            detail={
                "error": f"No such action: {action_type}",
                "did_you_mean": _nearest(action_type),
            },
        )
    return {"action_type": action_type, **entry}


def _nearest(action_type: str, limit: int = 5) -> list[str]:
    """Action names closest to what was asked for."""
    import difflib  # noqa: PLC0415

    return difflib.get_close_matches(action_type, action_manifest.ACTIONS, n=limit, cutoff=0.5)
