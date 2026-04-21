"""HTTP client helper for calling nttd observation tools from neuro-san coded tools.

Coded tools in the rail_mas agent network call back to nttd's REST API
to execute observation tools (find_station_spot, get_engines, etc.).
Connection info comes from sly_data (session_id, company_id) and the
NTTD_API_URL environment variable.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

import httpx

logger = logging.getLogger(__name__)

NTTD_API_URL = os.environ.get("NTTD_API_URL", "http://localhost:8000")
NTTD_TIMEOUT = float(os.environ.get("NTTD_TIMEOUT", "30.0"))


async def execute_tool(
    tool_name: str,
    parameters: Dict[str, Any],
    sly_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute an nttd observation tool via HTTP callback.

    :param tool_name: Name of the observation tool (e.g. "find_station_spot").
    :param parameters: Tool parameters as a dictionary.
    :param sly_data: Neuro-san sly_data containing session_id and company_id.
    :return: Tool result dictionary.
    """
    session_id = sly_data.get("session_id", "")
    company_id = sly_data.get("company_id", 0)

    url = f"{NTTD_API_URL}/api/v1/sessions/{session_id}/tools/execute"
    payload = {
        "tool_name": tool_name,
        "parameters": {**parameters, "company_id": company_id},
    }

    logger.info("Calling nttd tool %s with params %s", tool_name, json.dumps(parameters))

    async with httpx.AsyncClient(timeout=NTTD_TIMEOUT) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        result = response.json()

    logger.info("Tool %s returned %d bytes", tool_name, len(json.dumps(result)))
    return result
