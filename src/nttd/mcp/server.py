"""MCP server for nttd — exposes observation and validation tools for LLM agents.

Agents use MCP tools to observe game state and validate proposed actions.
Execution happens through a separate interpreter layer, not through MCP.

Each MCP server instance is configured for a specific session and company via
environment variables. Run with::

    NTTD_URL=http://localhost:8000 \\
    NTTD_SESSION_ID=ses_abc123 \\
    NTTD_AGENT_ID=mcp_agent_1 \\
    NTTD_COMPANY_ID=0 \\
    python -m nttd.mcp.server

Or configure in Claude Desktop / Claude Code mcp.json.
"""

import os

from mcp.server.fastmcp import FastMCP

from nttd.mcp.client import NttdMCPClient
from nttd.mcp.tools.observation import register_observation_tools
from nttd.mcp.tools.pathfinding import register_pathfinding_tools
from nttd.mcp.tools.validation import register_validation_tools

# Read config from environment
NTTD_URL = os.environ.get("NTTD_URL", "http://localhost:8000")
NTTD_SESSION_ID = os.environ.get("NTTD_SESSION_ID", "")
NTTD_AGENT_ID = os.environ.get("NTTD_AGENT_ID", "mcp_agent")
NTTD_COMPANY_ID = int(os.environ.get("NTTD_COMPANY_ID", "0"))

if not NTTD_SESSION_ID:
    raise ValueError("NTTD_SESSION_ID environment variable is required")

# Create the MCP server and nttd client
mcp = FastMCP(
    "nttd",
    instructions=(
        "OpenTTD game observation and planning tools. You are advising company "
        f"{NTTD_COMPANY_ID} in session {NTTD_SESSION_ID}. "
        "Use observation tools to understand the game state (towns, industries, "
        "vehicles, finances). Use pathfind for route planning. Use validate_actions "
        "to verify your proposed action list before it is executed.\n\n"
        "You do NOT execute actions directly. Instead, output your decisions as a "
        "JSON action list. Each action should have 'action_type' and 'parameters'. "
        "Example:\n"
        '[\n'
        '  {"action_type": "build_road_stop", "parameters": {"tile": 12345, "length": 1}},\n'
        '  {"action_type": "buy_vehicle", "parameters": {"depot_tile": 67890, "engine_id": 5}}\n'
        ']'
    ),
)

client = NttdMCPClient(
    base_url=NTTD_URL,
    session_id=NTTD_SESSION_ID,
    agent_id=NTTD_AGENT_ID,
    company_id=NTTD_COMPANY_ID,
)

# Register tool modules — observation, pathfinding, and validation only
register_observation_tools(mcp, client)
register_pathfinding_tools(mcp, client)
register_validation_tools(mcp, client)


def main() -> None:
    """Entry point for ``python -m nttd.mcp.server``."""
    mcp.run()


if __name__ == "__main__":
    main()
