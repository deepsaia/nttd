"""Coded tool that reads the current game observation from sly_data.

nttd sends the full observation as part of the MAS HTTP request payload.
The MAS HTTP adapter puts this into sly_data["observation"] before the
agent network runs. This coded tool simply surfaces it to the chat stream
so LLM agents can reason about it.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from neuro_san.interfaces.coded_tool import CodedTool


class ReadObservation(CodedTool):
    """Surfaces the nttd game observation from sly_data into the chat stream."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        observation = sly_data.get("observation")
        if observation is None:
            return "No game observation available in sly_data."

        if isinstance(observation, str):
            return observation
        return json.dumps(observation, indent=2)
