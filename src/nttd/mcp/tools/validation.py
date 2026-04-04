"""Validation tool — lets agents check proposed actions before execution."""

import json

from mcp.server.fastmcp import FastMCP

from nttd.constants import ACTION_CATEGORIES, KNOWN_ACTIONS
from nttd.mcp.client import NttdMCPClient


def register_validation_tools(mcp: FastMCP, client: NttdMCPClient) -> None:
    """Register action validation tools on the MCP server."""

    @mcp.tool()
    async def validate_actions(actions: list[dict]) -> str:
        """Validate a list of proposed actions without executing them.

        Each action should have 'action_type' (str) and 'parameters' (dict).
        Returns validation results per action: valid or error reason.

        Use this before outputting your final action list to catch mistakes.

        Args:
            actions: List of action dicts, each with 'action_type' and 'parameters'.
                     Example: [{"action_type": "build_road_stop", "parameters": {"tile": 123}}]
        """
        results: list[dict[str, str]] = []
        for i, action in enumerate(actions):
            action_type = action.get("action_type", "")
            params = action.get("parameters", {})

            if not action_type:
                results.append({"index": i, "status": "invalid", "error": "missing action_type"})
                continue

            if action_type not in KNOWN_ACTIONS:
                results.append({
                    "index": i,
                    "status": "invalid",
                    "action_type": action_type,
                    "error": f"unknown action_type: {action_type}",
                })
                continue

            if not isinstance(params, dict):
                results.append({
                    "index": i,
                    "status": "invalid",
                    "action_type": action_type,
                    "error": "parameters must be a dict",
                })
                continue

            results.append({"index": i, "status": "valid", "action_type": action_type})

        valid_count = sum(1 for r in results if r["status"] == "valid")
        return json.dumps({
            "total": len(actions),
            "valid": valid_count,
            "invalid": len(actions) - valid_count,
            "results": results,
        }, indent=2)

    @mcp.tool()
    async def list_available_actions() -> str:
        """List all available action types that can be used in the action list.

        Returns action types grouped by category. Use these exact action_type
        values when building your action list.
        """
        return json.dumps(ACTION_CATEGORIES, indent=2)
