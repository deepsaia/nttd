"""Parser for extracting action lists from agent output.

Handles both structured (list[dict]) and text (JSON embedded in natural
language) agent responses.
"""

import json
import logging
import re
from typing import Any

from nttd.interpreter.action_schema import AgentAction

logger = logging.getLogger(__name__)


def parse_action_list(agent_output: str | list[dict[str, Any]]) -> list[AgentAction]:
    """Parse agent output into a list of AgentAction objects.

    Accepts:
    - A Python list of dicts (already structured)
    - A JSON string containing an array of actions
    - Natural language text with an embedded JSON array (extracted via regex)

    Returns:
        List of validated AgentAction objects. Invalid entries are logged and skipped.
    """
    raw_list = _extract_raw_list(agent_output)
    actions: list[AgentAction] = []
    for i, item in enumerate(raw_list):
        try:
            actions.append(AgentAction.model_validate(item))
        except Exception as e:
            logger.warning("Skipping invalid action at index %d: %s — %s", i, item, e)
    return actions


def _extract_raw_list(agent_output: str | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extract a list of dicts from agent output."""
    if isinstance(agent_output, list):
        return agent_output

    text = agent_output.strip()

    # Try direct JSON parse
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    # Try extracting JSON array from markdown code blocks
    code_block_match = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", text)
    if code_block_match:
        try:
            return json.loads(code_block_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try extracting any JSON array from the text
    array_match = re.search(r"\[[\s\S]*\]", text)
    if array_match:
        try:
            return json.loads(array_match.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning("Could not extract action list from agent output: %.200s", text)
    return []
