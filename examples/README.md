# Building Agents for nttd

nttd is an agent-agnostic API server — it wraps OpenTTD and exposes the game
as a REST API. Agents are external clients built with any framework (LangChain,
LangGraph, CrewAI, AutoGen, OpenAI SDK, etc.). nttd provides the game
interface; you bring the intelligence.

## Architecture

```
Agent Framework (LangChain, OpenAI, etc.)
    ↓ observe (MCP tools or REST)
nttd Observation API → game state, towns, vehicles, finances
    ↓ decide (LLM reasoning)
Agent outputs action list: [{"action_type": "...", "parameters": {...}}]
    ↓ interpret & execute
nttd Interpreter → validates → submits to GameScript → OpenTTD engine
```

**Key design**: Agents observe and decide. They do NOT execute directly.
The agent outputs a structured action list, and nttd's interpreter handles
validation and execution. This separates reasoning from execution.

## Agent Loop

```
register → observe → decide → interpret → execute → repeat
```

The game runs continuously (no pause-and-play). Agents poll for state,
reason about it, output actions, and the interpreter executes them.

## Two Observation Interfaces

| Interface | Best for | Setup |
|-----------|----------|-------|
| **REST API** | All agents, custom frameworks | Direct HTTP calls |
| **MCP Server** | MCP-compatible frameworks | Configure `mcp.json` |

Both are observation-only. Execution always goes through the interpreter.

---

## Example Agents

| File | Framework | Pattern |
|------|-----------|---------|
| `langchain_nttd_agent.py` | LangChain | Tool-calling or single-shot LLM |
| `openai_nttd_agent.py` | OpenAI SDK | Native function calling |
| `langgraph_nttd_agent.py` | LangGraph | Strategic planner + tactical executor |
| `simple_bus_agent.py` | None (httpx) | Scripted rule-based agent |
| `agent_client.py` | None (httpx) | REST API lifecycle demo |

Each example includes:
- **Agent instructions** (system prompt with role, strategy, game rules)
- **Observation tool bindings** (game state queries)
- **Action output format** (structured JSON matching interpreter schema)
- **The full loop** (observe → decide → interpret → execute)

### Shared Instructions

`agent_instructions.py` contains reusable system prompts and the action
format specification. Import and customize for your agent:

```python
from examples.agent_instructions import get_bus_agent_prompt, get_general_agent_prompt

# Bus route specialist
prompt = get_bus_agent_prompt(company_id=0)

# General transport CEO
prompt = get_general_agent_prompt(company_id=0)
```

---

## Action Format

Agents output decisions as a JSON array. Each action has `action_type` and
`parameters` — this format maps directly to what the GameScript expects:

```json
[
  {"action_type": "build_road_stop", "parameters": {"tile": 12345, "length": 1}},
  {"action_type": "build_road_depot", "parameters": {"tile": 12350}},
  {"action_type": "buy_vehicle", "parameters": {"depot_tile": 12350, "engine_id": 5}},
  {"action_type": "add_order", "parameters": {"vehicle_id": 0, "order_index": 0, "destination": 12345}},
  {"action_type": "start_vehicle", "parameters": {"vehicle_id": 0}}
]
```

Submit to the interpreter for execution:

```bash
curl -X POST "http://localhost:8000/sessions/{sid}/actions/interpret?company_id=0" \
  -H "Content-Type: application/json" \
  -d '[{"action_type": "build_road_stop", "parameters": {"tile": 12345}}]'
```

Validate without executing:

```bash
curl -X POST "http://localhost:8000/sessions/{sid}/actions/interpret/validate" \
  -H "Content-Type: application/json" \
  -d '[{"action_type": "build_road_stop", "parameters": {"tile": 12345}}]'
```

List all available action types:

```bash
curl http://localhost:8000/sessions/{sid}/actions/available
```

---

## Observation Endpoints (REST)

```bash
# Compact game state (~1-3 KB, LLM-friendly)
GET /sessions/{sid}/state/compact?company_id=0

# Full snapshot (~15-50 KB)
GET /sessions/{sid}/state/full

# GS queries (specific data)
POST /sessions/{sid}/state/gs/query?action=get_towns
POST /sessions/{sid}/state/gs/query?action=get_engines  {"company_id": 0, "vehicle_type": 1}
POST /sessions/{sid}/state/gs/query?action=find_bus_stop_spots  {"town_id": 3, "company_id": 0}
```

## MCP Server (Optional)

For MCP-compatible frameworks, configure `mcp.json`:

```json
{
  "mcpServers": {
    "nttd": {
      "command": "uv",
      "args": ["run", "python", "-m", "nttd.mcp"],
      "env": {
        "NTTD_URL": "http://localhost:8000",
        "NTTD_SESSION_ID": "ses_abc123",
        "NTTD_AGENT_ID": "my_agent",
        "NTTD_COMPANY_ID": "0"
      }
    }
  }
}
```

MCP exposes ~30 observation + validation tools. No execution tools — execution
goes through the interpreter endpoint.

---

## Available GS Queries

| Query | Parameters | Returns |
|-------|-----------|---------|
| `get_towns` | — | All towns: id, name, population, x, y |
| `get_town_info` | `town_id` | Detailed town info |
| `get_industries` | — | Industries with production/acceptance |
| `get_companies` | — | All companies |
| `get_company_finance` | `company_id` | Balance, loan, income, value |
| `get_stations` | `company_id` | Stations with cargo waiting |
| `get_vehicles` | `company_id` | Vehicles with profit info |
| `get_engines` | `company_id`, `vehicle_type` | Purchasable engines |
| `get_orders` | `vehicle_id` | Vehicle order list |
| `get_cargo_types` | — | All cargo types |
| `get_subsidies` | — | Active subsidies |
| `get_tile_info` | `tile` | Terrain at tile |
| `get_map_size` | — | Map dimensions |
| `find_bus_stop_spots` | `town_id`, `max_results` | Tiles for bus stops |
| `find_depot_spots` | `town_id`, `max_results` | Tiles for depots |

---

## Available Action Types

**Road**: `build_road`, `build_road_line`, `build_road_depot`, `build_road_stop`,
`remove_road`, `remove_road_depot`, `remove_road_stop`

**Rail**: `build_rail`, `build_rail_track`, `build_rail_station`, `build_rail_depot`,
`build_rail_signal`, `build_rail_waypoint`, `remove_*`, `convert_rail`

**Marine**: `build_canal`, `build_lock`, `build_buoy`, `build_water_depot`, `remove_*`

**Air/Other**: `build_airport`, `remove_airport`, `build_dock`, `build_bridge`,
`build_tunnel`, `demolish_tile`

**Vehicles**: `buy_vehicle`, `sell_vehicle`, `start_vehicle`, `stop_vehicle`,
`send_to_depot`, `clone_vehicle`, `refit_vehicle`, `reverse_vehicle`

**Orders**: `add_order`, `insert_order`, `remove_order`, `skip_to_order`,
`move_order`, `set_order_flags`, `share_orders`, `copy_orders`

**Company**: `build_company_hq`, `set_loan`, `rename_company`

**Groups**: `create_group`, `delete_group`, `move_to_group`, `set_auto_replace`

---

## Tips

- **Start with `simple_bus_agent.py`** to understand the flow without LLM complexity.
- **Use `find_bus_stop_spots`** and `find_depot_spots` — don't scan tiles manually.
- **Validate before executing** — use `/actions/interpret/validate` or the `validate_actions` MCP tool.
- **Vehicle IDs change** — after buying a vehicle, observe vehicles to get the new ID.
- **Order destinations are tile IDs** (stop tiles), not town IDs.
- **Game speed** is configurable at session start. Faster games need faster agent decisions.
- **AI opponents**: Set `ai_opponents` when creating a session for competition.

---

## Agent Observe-Decide-Execute Flow

The loop lives in AgentConnection (src/nttd/gameloop/connection.py). Each agent runs an independent cycle:

1. Observe (_observe())

SessionRuntime.world (WorldState)
    |
    v
Snapshot builder compiles game state:
  - company: finances, vehicles, stations
  - towns, industries (from GS queries cached in WorldState)
  - route_planning: RoutePlanner.for_agent() -> existing + top 5 unserved routes
  - previous_actions: results from last cycle (success/fail + error messages)
    |
    v
Filtered by agent_type:
  - road agent only sees road vehicles + bus/truck stations
  - rail agent only sees trains + rail stations
  (via AGENT_VEHICLE_TYPES and AGENT_STATION_FILTERS)
    |
    v
JSON observation string -> sent to LLM as context

2. Decide (_decide())

LLM receives:
  - System prompt (from agent_instructions.py, per agent_type)
  - Observation JSON (game state + route_planning + previous_actions)
  - Observation tool schemas (if observation_tools=true in config)
    |
    v
Multi-turn tool calling:
  LLM can call observation tools (get_towns, pathfind, find_bus_stop_spots, etc.)
  Each tool call -> ObservationToolkit.execute() -> either:
    - GS bridge: admin_client.send_gamescript(action, params) -> GameScript query -> result
    - Custom handler: pathfind -> Python A* pathfinder -> path result
  Tool results fed back to LLM for next turn
    |
    v
Final LLM response: JSON array of actions
  e.g. [{"action_type": "build_path", "parameters": {"steps": [...], "transport_type": "road"}}]

3. Interpret (parse_action_list())

Raw LLM text -> interpreter/parser.py
  - Extracts JSON array from LLM response (handles markdown fences, trailing text)
  - Validates each element has "action_type" (str) and "parameters" (dict)
  - Returns list[AgentAction] -- fully generic, no action-type-specific validation
  - AgentAction is just: action_type: str + parameters: dict[str, Any]

4. Execute (_execute())

For each AgentAction:
    |
    v
  Wrap in ActionEnvelope (adds company_id, connection_id, timestamp)
    |
    v
  admin_client.send_gamescript(action_type, parameters)
    |
    v
  Python AdminClient -> JSON message over TCP admin port -> OpenTTD server
    |
    v
  OpenTTD passes message to GameScript (nttd-gs/main.nut)
    |
    v
  GS main.nut::HandleCommand():
    - Dispatch table maps action_type -> handler function
    - e.g. "build_path" -> CmdBuildPath(params)
    - CmdBuildPath enters GSCompanyMode(company_id) -- executes as that company
    - Iterates path steps, calls GSRoad.BuildRoad / GSRail.BuildRail / GSBridge.BuildBridge
    - Returns {success: true, result: {built: N, failed: M, ...}}
    |
    v
  Response travels back: GS -> admin port -> AdminClient -> ActionResult
    |
    v
  ActionResult (success/fail + data) stored in previous_actions for next cycle
