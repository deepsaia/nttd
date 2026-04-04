"""Action validator — checks agent actions against known action types.

This is the server-side validation used by both the interpreter and
the REST /actions/interpret/validate endpoint.
"""

from nttd.constants import KNOWN_ACTIONS
from nttd.interpreter.action_schema import AgentAction


def validate_actions(actions: list[AgentAction]) -> dict[int, str]:
    """Validate a list of agent actions.

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
    return errors
