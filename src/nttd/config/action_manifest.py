"""The loaded action manifest: what nttd can do, and what each action takes.

Generated from the GameScript by ``scripts/generate_action_manifest.py`` and read here.
This is the single description of nttd's action surface: the validator, the HTTP
endpoint that publishes it, and any client generating tools from it all read the same
file.

It replaced a hand-written table in ``interpreter/validator.py`` that covered 14 of 129
actions and had drifted. That table declared ``plant_tree_rectangle`` takes
``x1,y1,x2,y2``; the GameScript reads ``x, y, width, height`` and refuses anything else,
so a contestant following nttd's own validator was rejected by the game. The hint text
beside it repeated the same wrong shape.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MANIFEST_PATH = Path(__file__).resolve().parents[3] / "config" / "actions" / "manifest.json"


def _load() -> dict[str, Any]:
    """Read the manifest, or fall back to an empty one.

    An unreadable manifest degrades validation to the vocabulary check rather than
    refusing every action: a missing policy file should not stop a game being played.
    It is logged loudly because the surface it describes is then invisible.
    """
    if not MANIFEST_PATH.exists():
        logger.warning(
            "No action manifest at %s. Parameter validation and the published action "
            "surface are unavailable until it is generated: "
            "uv run python scripts/generate_action_manifest.py",
            MANIFEST_PATH,
        )
        return {"actions": {}}
    try:
        return json.loads(MANIFEST_PATH.read_text())
    except json.JSONDecodeError:
        logger.exception("Could not parse the action manifest at %s", MANIFEST_PATH)
        return {"actions": {}}


# Loaded once. The manifest describes the GameScript, which does not change while the
# server runs, so re-reading it per validation would buy nothing.
_MANIFEST = _load()
ACTIONS: dict[str, Any] = _MANIFEST.get("actions", {})


def manifest() -> dict[str, Any]:
    """The whole manifest, as published."""
    return _MANIFEST


def parameters(action_type: str) -> dict[str, Any]:
    """Every parameter an action accepts, keyed by name."""
    return (ACTIONS.get(action_type) or {}).get("parameters", {})


def required_parameters(action_type: str) -> list[str]:
    """The parameters an action cannot run without."""
    return sorted(
        name for name, meta in parameters(action_type).items() if meta.get("required")
    )


def accepted_parameters(action_type: str) -> list[str]:
    """Every parameter name an action accepts, required or not."""
    return sorted(parameters(action_type))


def tier(action_type: str) -> str:
    """``participant``, ``operator``, ``read_only``, or empty when unknown."""
    return (ACTIONS.get(action_type) or {}).get("tier", "")
