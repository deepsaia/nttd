"""Read the moves an agent sent and give each command an id.

Language-model agents often send nested JSON as a string, a single object where a
list is expected, or a boolean as the word "true". The readers here accept those
shapes and return plain Python values, or an error text when the input cannot be
read at all.

A named command is ``{"action_id", "agent_tag", "command", "parameters"}``. The id is
the agent tag plus a counter, unique within one server run, so the game echoes it on
the result and the action log attributes the command to the agent.
"""

from __future__ import annotations

import json
from typing import Any

MOVES_FORMAT_HINT = (
    'moves must be a list of objects, each {"command": <name>, '
    '"parameters": {...}}. Use the list_commands tool for parameter details.'
)




def coerce_params(params: Any) -> dict[str, Any] | None:
    """Return params as a dict, decoding a JSON string if needed.

    Returns None when the value cannot be read as a dict at all.
    """
    if params is None:
        return {}
    if isinstance(params, dict):
        return params
    if isinstance(params, str):
        if not params.strip():
            return {}
        try:
            decoded = json.loads(params)
        except json.JSONDecodeError:
            return None
        if isinstance(decoded, dict):
            return decoded
    return None


def coerce_flag(value: Any) -> bool:
    """Read a boolean that may arrive as a string ("true", "False", "0")."""
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1")
    return bool(value)


def read_moves(raw_moves: Any) -> tuple[list[dict[str, Any]], str | None]:
    """Normalize a tool's moves into ``[{"command": str, "parameters": dict}]``.

    Returns (moves, error). A non-None error means the moves could not be read;
    the caller reports it to the agent and sends nothing.
    """
    if isinstance(raw_moves, str):
        if not raw_moves.strip():
            return [], None
        try:
            raw_moves = json.loads(raw_moves)
        except json.JSONDecodeError:
            return [], MOVES_FORMAT_HINT
    if isinstance(raw_moves, dict):
        raw_moves = [raw_moves]
    if raw_moves is None:
        return [], None
    if not isinstance(raw_moves, list):
        return [], MOVES_FORMAT_HINT

    moves: list[dict[str, Any]] = []
    for move in raw_moves:
        if isinstance(move, str):
            try:
                move = json.loads(move)
            except json.JSONDecodeError:
                return [], MOVES_FORMAT_HINT
        if isinstance(move, dict):
            command = move.get("command", "")
            params = coerce_params(move.get("parameters"))
        else:
            command = getattr(move, "command", "")
            params = coerce_params(getattr(move, "parameters", {}))
        command = getattr(command, "value", command)
        if not command or params is None:
            return [], MOVES_FORMAT_HINT
        moves.append({"command": str(command), "parameters": dict(params)})
    return moves, None


def name_commands(
    moves: list[dict[str, Any]], agent_tag: str, first_index: int,
) -> list[dict[str, Any]]:
    """Attach an id and the agent tag to each move.

    Ids are ``<agent_tag>:<n>`` with n counting from ``first_index``. The caller keeps
    the counter across calls so ids never repeat within a server run.
    """
    return [
        {
            "action_id": f"{agent_tag}:{first_index + offset}",
            "agent_tag": agent_tag,
            "command": move["command"],
            "parameters": move["parameters"],
        }
        for offset, move in enumerate(moves)
    ]
