"""Action validator -- checks agent actions against known action types
and validates parameters for commonly-misused actions.

This is the server-side validation used by both the interpreter and
the REST /actions/interpret/validate endpoint.
"""

import logging

from nttd.constants import KNOWN_ACTIONS, OPERATOR_ACTIONS
from nttd.interpreter.action_schema import AgentAction

logger = logging.getLogger(__name__)

# Required parameters per action type, mirroring the GameScript handlers.
# Catching a missing parameter here costs nothing; letting it through spends a
# round trip to the game to get the same answer.
_REQUIRED_PARAMS: dict[str, list[str]] = {
    "build_bridge": ["start_x", "start_y", "end_x", "end_y"],
    # Terraforming and area operations use corner pairs, not a single tile.
    "raise_tile": ["x", "y", "slope"],
    "lower_tile": ["x", "y", "slope"],
    "level_tiles": ["x1", "y1", "x2", "y2"],
    "plant_tree": ["x", "y"],
    "plant_tree_rectangle": ["x1", "y1", "x2", "y2"],
    "build_one_way_road": ["x1", "y1", "x2", "y2"],
    "build_one_way_road_full": ["x1", "y1", "x2", "y2"],
    "convert_road_type": ["x1", "y1", "x2", "y2"],
    # Conditional orders address an order by position within a vehicle's list.
    "set_order_condition": ["vehicle_id", "order_pos", "condition"],
    "set_order_compare_function": ["vehicle_id", "order_pos", "compare_function"],
    "set_order_compare_value": ["vehicle_id", "order_pos", "value"],
    "set_stop_location": ["vehicle_id", "order_pos", "stop_location"],
    # estimate_cost wraps another action, so it needs that action and its params.
    "estimate_cost": ["action", "params"],
}

# Extra guidance for parameter shapes agents get wrong in a specific way.
_PARAM_HINTS: dict[str, tuple[tuple[str, ...], str]] = {
    "build_bridge": (
        ("tile_from", "tile_to"),
        " (build_bridge uses x,y coordinates, not tile IDs."
        " Use start_x, start_y, end_x, end_y from get_tile_info or find_flat_spots.)",
    ),
    # A single x,y is the natural guess for an area operation, so name the shape.
    "level_tiles": (("x", "y", "width", "height"), " (level_tiles takes a corner pair: x1, y1, x2, y2)"),
    "build_one_way_road": (("from_x", "from_y", "to_x", "to_y"), " (use x1, y1, x2, y2)"),
    "build_one_way_road_full": (("from_x", "from_y", "to_x", "to_y"), " (use x1, y1, x2, y2)"),
    "convert_road_type": (("from_x", "from_y", "to_x", "to_y"), " (use x1, y1, x2, y2)"),
    "plant_tree_rectangle": (("x", "y"), " (plant_tree_rectangle takes a corner pair: x1, y1, x2, y2)"),
    # order_position reads more naturally than order_pos, so it is a common miss.
    "set_order_condition": (("order_position",), " (the parameter is order_pos)"),
    "set_order_compare_function": (("order_position",), " (the parameter is order_pos)"),
    "set_order_compare_value": (("order_position",), " (the parameter is order_pos)"),
    "set_stop_location": (("order_position",), " (the parameter is order_pos)"),
}


def _validate_params(action: AgentAction) -> str | None:
    """Check required parameters for specific action types.

    Returns an error message if validation fails, None if OK.
    """
    required = _REQUIRED_PARAMS.get(action.action_type)
    if not required:
        return None

    params = action.parameters
    missing = [p for p in required if p not in params]
    if not missing:
        return None

    hint = ""
    wrong_names, hint_text = _PARAM_HINTS.get(action.action_type, ((), ""))
    if any(name in params for name in wrong_names):
        hint = hint_text

    return f"{action.action_type} missing required params: {', '.join(missing)}{hint}"


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
        elif action.action_type in OPERATOR_ACTIONS:
            # Distinguished from "unknown" so an agent learns the action exists
            # but is not available for play, rather than assuming a typo.
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
