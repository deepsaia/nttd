# Neuro-SAN Rail MAS Example

Multi-agent rail transport system for nttd using [Neuro-SAN](https://github.com/cognizant-ai-labs/neuro-san).

## Architecture

```
nttd server                          neuro-san server
(game loop, observation, actions)    (agent network, LLM reasoning)
     |                                    |
     |  1. POST observation -------->     |
     |                               rail_coordinator
     |                                 /     |     \
     |                          scout  builder  vehicle_mgr
     |                            |       |
     |  <-- HTTP callback --------+-------+
     |  (find_station_spot, get_engines, etc.)
     |                                    |
     |  <--- action JSON response --------|
     |
     v
  execute actions in OpenTTD
```

nttd sends game observations to the neuro-san server via HTTP. The agent
network reasons about what to do and calls back to nttd's observation tool
API for queries like `find_station_spot`. The final response is a JSON
action list that nttd executes in OpenTTD.

## Agent Network

**rail_coordinator** (front man) -- determines the current phase and delegates:
- **route_scout** -- finds best unserved cargo routes, validates station sites (Phase 1)
- **infrastructure_builder** -- builds stations, connects track, places depots (Phases 2-4)
- **vehicle_manager** -- buys trains, sets orders, starts, verifies, expands (Phases 5-7)

**Coded tools** (HTTP callbacks to nttd):
- `game_state` -- reads current observation from sly_data
- `find_station_spot` -- validates rail station placement near industries
- `find_rail_depot_spot` -- finds depot locations adjacent to existing track
- `get_engines` -- lists available train engines
- `get_rail_types` -- lists available track types

## Setup

### Environment Variables

```bash
# LLM API key (used by neuro-san for agent reasoning)
export OPENAI_API_KEY="sk-..."

# nttd server URL (coded tools call back to this)
export NTTD_API_URL="http://localhost:8000"
export NTTD_TIMEOUT="30.0"

# Neuro-SAN paths -- point to this example's files
export AGENT_MANIFEST_FILE="$(pwd)/examples/neuro_san_mas/registries/manifest.hocon"
export AGENT_TOOL_PATH="$(pwd)/examples/neuro_san_mas/coded_tools"
export PYTHONPATH="$(pwd)/examples/neuro_san_mas/coded_tools:${PYTHONPATH}"

# Neuro-SAN server config
export AGENT_HTTP_PORT=8080
export AGENT_MCP_ENABLE="false"
```

### Start Servers

```bash
# Terminal 1: Start nttd server
nttd server start --scenario config/scenario_30min.conf

# Terminal 2: Start neuro-san server
python -m neuro_san.service.main_loop.server_main_loop
```

### nttd Scenario Config

Add the rail_mas agent to your scenario `.conf` file:

```hocon
agents = [
  {
    agent_id = "rail_mas"
    company_id = 0
    framework = "mas"
    mas_transport {
      transport = "http"
      endpoint = "http://localhost:8080/v1/agent/rail_coordinator"
    }
    poll_interval = 5.0
    observation_tools = true
    max_actions_per_cycle = 20
  }
]
```

## Replicating for Other Transport Types

To create a road, air, or water MAS:

1. Copy `registries/rail_mas.hocon` to `registries/road_mas.hocon`
2. Rename agents: `rail_coordinator` -> `road_coordinator`, etc.
3. Adjust agent prompts for the transport type
4. Add transport-specific coded tools (e.g., `find_bus_stop_spots`, `find_dock_spots`)
5. Add the new `.hocon` to `manifest.hocon`
6. Add coded tools under `coded_tools/road_mas/`

## File Structure

```
examples/neuro_san_mas/
  registries/
    manifest.hocon           # Lists agent networks to serve
    rail_mas.hocon           # Rail agent network definition
  coded_tools/
    rail_mas/
      __init__.py
      nttd_client.py         # Shared HTTP client for nttd API calls
      read_observation.py    # Surfaces game observation from sly_data
      find_station_spot.py   # Validates station placement
      find_rail_depot_spot.py # Finds depot locations on track
      get_engines.py         # Lists available engines
      get_rail_types.py      # Lists rail track types
```
