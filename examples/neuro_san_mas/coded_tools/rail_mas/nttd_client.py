"""HTTP client for read-only GS queries from neuro-san coded tools.

Coded tools in the rail_mas agent network call back to nttd's REST API
to run observation queries (find_station_spot, get_engines, etc.).
Connection info comes from sly_data (session_id, company_id) and the
NTTD_API_URL environment variable.

Mutating actions (build, buy, connect) are never called here -- they
accumulate in sly_data["action_list"] and execute through nttd's
action executor after the agent turn completes.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

import httpx

logger = logging.getLogger(__name__)

NTTD_API_URL = os.environ.get("NTTD_API_URL", "http://localhost:8000")
NTTD_TIMEOUT_SECONDS = float(os.environ.get("NTTD_TIMEOUT_SECONDS", "300.0"))


async def query_gs(
    tool_name: str,
    parameters: Dict[str, Any],
    sly_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Query nttd game state via a read-only GS observation tool.

    :param tool_name: Name of the observation tool (e.g. "find_station_spot").
    :param parameters: Tool parameters as a dictionary.
    :param sly_data: Neuro-san sly_data containing session_id and company_id.
    :return: Tool result dictionary.
    """
    session_id = sly_data.get("session_id", "")
    company_id = sly_data.get("company_id", 0)

    url = f"{NTTD_API_URL}/sessions/{session_id}/state/gs/query"
    gs_params = {**parameters, "company_id": company_id}

    logger.info("Calling nttd tool %s with params %s", tool_name, json.dumps(gs_params))

    async with httpx.AsyncClient(timeout=NTTD_TIMEOUT_SECONDS) as client:
        response = await client.post(
            url,
            params={"action": tool_name},
            json=gs_params,
        )
        response.raise_for_status()
        result = response.json()

    logger.info("Tool %s returned %d bytes", tool_name, len(json.dumps(result)))
    return result
