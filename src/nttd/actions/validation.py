"""Command contracts shared by lookup, dry runs, queries and execution.

These checks validate syntax, not changing game state. Entity existence and other
game preconditions must still be checked by the GameScript when commands execute.
"""

from __future__ import annotations

import difflib
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator, validators

from nttd.config import action_manifest

# Squirrel distinguishes integers from floats, even 1.0. JSON Schema's default
# integer checker does not, and bool must never be accepted as an entity id.
_Validator = validators.extend(
    Draft202012Validator,
    type_checker=Draft202012Validator.TYPE_CHECKER.redefine(
        "integer",
        lambda _checker, value: isinstance(value, int) and not isinstance(value, bool),
    ),
)


@lru_cache(maxsize=512)
def parameter_schema(name: str, allow_company: bool = False) -> dict[str, Any]:
    """Build the lookup/validation schema from the manifest, without coercion."""
    entry = action_manifest.ACTIONS[name]
    properties = {}
    for key, meta in entry["parameters"].items():
        properties[key] = {"type": meta["type"], **meta.get("schema", {})}
    if allow_company:
        properties["company_id"] = {"type": "integer"}
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": action_manifest.required_parameters(name),
    }
    groups = []
    for group in entry.get("one_of", []):
        groups.append({"anyOf": [{"required": branch} for branch in group]})
    for group in entry.get("optional_one_of", []):
        names = sorted({key for branch in group for key in branch})
        groups.append(
            {
                "anyOf": [
                    {"not": {"anyOf": [{"required": [key]} for key in names]}},
                    *[{"required": branch} for branch in group],
                ]
            }
        )
    if groups:
        schema["allOf"] = groups
    if name == "estimate_cost":
        properties["action"]["enum"] = [
            n for n, e in action_manifest.ACTIONS.items() if e["tier"] == "participant" and n != "estimate_cost"
        ]
    return schema


def validate_parameters(name: str, params: Any, *, allow_company: bool = False) -> str | None:
    """Return an actionable refusal, or None. Never guess or rename parameters."""
    if name not in action_manifest.ACTIONS:
        return f"Unknown command {name!r}. Use list_commands to find a command."
    schema = parameter_schema(name, allow_company)
    messages: list[str] = []
    for error in _Validator(schema).iter_errors(params):
        path = "parameters" + "".join(f"[{key}]" if isinstance(key, int) else f".{key}" for key in error.absolute_path)
        message = error.message
        if error.validator == "additionalProperties" and isinstance(error.instance, dict):
            accepted = error.schema.get("properties", {})
            unknown = sorted(set(error.instance) - set(accepted))
            message = f"unknown parameter(s): {', '.join(unknown)}"
            suggestions = []
            for key in unknown:
                near = difflib.get_close_matches(key, accepted, n=1, cutoff=0.6)
                if near:
                    suggestions.append(f"{key} -> {near[0]}")
            message += f"; accepts: {', '.join(accepted) or 'no parameters'}"
            if suggestions:
                message += f"; possible corrections: {', '.join(suggestions)}"
        elif error.validator == "anyOf":
            branches = error.schema["anyOf"]
            options = [", ".join(branch["required"]) for branch in branches if "required" in branch]
            message = "needs one of: " + " or ".join(options)
            if any("not" in branch for branch in branches):
                message += "; alternatively omit the entire optional group"
        elif error.validator == "enum" and name == "estimate_cost" and list(error.absolute_path) == ["action"]:
            message = "must name a gameplay command other than estimate_cost"
        messages.append(f"{path}: {message}")
    if messages:
        return f"{name}: " + "; ".join(dict.fromkeys(messages)) + f". See list_commands(name='{name}')."

    if name == "estimate_cost":
        nested = validate_parameters(params["action"], params["params"], allow_company=allow_company)
        if nested:
            return f"estimate_cost parameters.params: {nested}"
    if name == "get_tile_area":
        area = (abs(params["x2"] - params["x1"]) + 1) * (abs(params["y2"] - params["y1"]) + 1)
        maximum = params.get("max_tiles", 400)
        if area > maximum:
            return (
                f"get_tile_area: requested {area} tiles; max_tiles is {maximum}. "
                "Bounds are inclusive; reduce the rectangle or explicitly increase max_tiles."
            )
    return None
