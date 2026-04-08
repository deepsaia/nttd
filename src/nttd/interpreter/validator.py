"""Action validator -- checks agent actions against known action types
and validates parameters for commonly-misused actions.

This is the server-side validation used by both the interpreter and
the REST /actions/interpret/validate endpoint.
"""

import logging

from nttd.constants import KNOWN_ACTIONS
from nttd.interpreter.action_schema import AgentAction

logger = logging.getLogger(__name__)

# Required parameters for actions that agents frequently get wrong.
# Maps action_type -> list of required parameter names.
_REQUIRED_PARAMS: dict[str, list[str]] = {
    "build_bridge": ["start_x", "start_y", "end_x", "end_y"],
}


def _validate_params(action: AgentAction) -> str | None:
    """Check required parameters for specific action types.

    Returns an error message if validation fails, None if OK.
    """
    params = action.parameters

    # build_bridge: agents often pass tile_from/tile_to instead of start_x/start_y/end_x/end_y
    if action.action_type == "build_bridge":
        required = _REQUIRED_PARAMS["build_bridge"]
        missing = [p for p in required if p not in params]
        if missing:
            hint = ""
            if "tile_from" in params or "tile_to" in params:
                hint = (
                    " (build_bridge uses x,y coordinates, not tile IDs."
                    " Use start_x, start_y, end_x, end_y from get_tile_info or find_flat_spots.)"
                )
            return f"build_bridge missing required params: {', '.join(missing)}{hint}"

    return None


def validate_actions(actions: list[AgentAction]) -> dict[int, str]:
    """Validate a list of agent actions.

    Checks action_type is known, then validates parameters for actions
    that commonly fail due to wrong parameter format.

    Returns:
        Dict mapping invalid action index to error message.
        Empty dict means all actions are valid.
    """
    errors: dict[int, str] = {}
    for i, action in enumerate(actions):
        if not action.action_type:
            errors[i] = "missing action_type"
        elif action.action_type not in KNOWN_ACTIONS:
            errors[i] = f"unknown action_type: {action.action_type}"
        else:
            param_error = _validate_params(action)
            if param_error:
                errors[i] = param_error
    return errors
