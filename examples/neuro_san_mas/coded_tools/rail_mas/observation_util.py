"""Parse and cache the observation from sly_data.

The observation arrives as a JSON string in sly_data["observation"].
This utility parses it once and caches the result so subsequent tool
calls within the same cycle skip re-parsing.
"""

from __future__ import annotations

import json
from typing import Any


def get_observation(sly_data: dict[str, Any]) -> dict[str, Any]:
    """Return the fully-parsed observation dict from *sly_data*.

    On the first call within a cycle the JSON string is parsed and stored
    as ``sly_data["_parsed_observation"]``.  Subsequent calls return the
    cached copy.
    """
    cached = sly_data.get("_parsed_observation")
    if cached is not None:
        return cached

    obs = sly_data.get("observation", {})
    if isinstance(obs, str):
        obs = json.loads(obs)

    sly_data["_parsed_observation"] = obs
    return obs
