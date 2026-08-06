"""Checks an agent's proposed actions before they cost a round trip to the game.

Backs ``POST /actions/interpret/validate``. Catching a missing parameter here costs
nothing; letting it through spends a round trip to get the same answer.

Parameter knowledge comes from the action manifest, which is generated from the
GameScript. It used to be a hand-written table of 14 actions with hand-written hints
beside it, and both had drifted: they declared ``plant_tree_rectangle`` takes
``x1,y1,x2,y2`` while the GameScript reads ``x, y, width, height`` and refuses anything
else. The hint even repeated the wrong shape as advice. The manifest covers all 129
actions and cannot drift, because a test regenerates it and compares.
"""

from __future__ import annotations

import logging

from nttd.config import action_manifest
from nttd.constants import KNOWN_ACTIONS, OPERATOR_ACTIONS
from nttd.interpreter.action_schema import AgentAction

logger = logging.getLogger(__name__)


def _validate_params(action: AgentAction) -> str | None:
    """Report any required parameter the action is missing, or None if it is complete.

    The message names what the action actually accepts rather than a hand-written
    hint. An agent that sent ``x1, y1`` to something wanting ``x, y, width, height``
    needs the real shape, and generating it from the manifest means the advice cannot
    contradict the game.
    """
    required = action_manifest.required_parameters(action.action_type)
    missing = [name for name in required if name not in action.parameters]
    if missing:
        message = f"{action.action_type} missing required params: {', '.join(missing)}"
        # Only when it adds something. Repeating the missing list back is noise, but an
        # agent that sent the wrong shape entirely needs to see the right one.
        accepted = action_manifest.accepted_parameters(action.action_type)
        if set(accepted) != set(missing):
            message += f" (accepts: {', '.join(accepted)})"
        return message

    return _validate_alternatives(action)


def _validate_alternatives(action: AgentAction) -> str | None:
    """Report an alternation the action satisfies no branch of.

    Several actions accept a choice: ``add_order`` takes a station id or a destination
    tile, and every action resolving a tile takes ``tile`` or an ``x,y`` pair. None of
    those parameters is required on its own, so checking requiredness alone lets an
    action through that names no destination at all.
    """
    for group in action_manifest.alternatives(action.action_type):
        if any(all(name in action.parameters for name in branch) for branch in group):
            continue
        options = " or ".join(", ".join(branch) for branch in group)
        return f"{action.action_type} needs one of: {options}"
    return None


def validate_actions(actions: list[AgentAction]) -> dict[int, str]:
    """Validate a list of agent actions.

    Returns:
        Invalid action index mapped to an error message. Empty means all are valid.
    """
    errors: dict[int, str] = {}
    for i, action in enumerate(actions):
        if not action.action_type:
            errors[i] = "missing action_type"
        elif action.action_type in OPERATOR_ACTIONS:
            # Distinguished from "unknown" so an agent learns the action exists but is
            # not available for play, rather than assuming a typo and retrying.
            errors[i] = (
                f"{action.action_type} is operator-tier: no human-player "
                f"equivalent, so it is not available for play"
            )
        elif action.action_type not in KNOWN_ACTIONS:
            errors[i] = f"unknown action_type: {action.action_type}"
        else:
            param_error = _validate_params(action)
            if param_error:
                errors[i] = param_error
    return errors
