# Neuro-SAN Rail MAS

Multi-agent rail transport system for nttd using [Neuro-SAN](https://github.com/cognizant-ai-labs/neuro-san).

## Architecture

```
nttd server                          neuro-san server
(game loop, observation, actions)    (agent network, LLM reasoning)
     |                                    |
     |  1. POST observation -------->     |
     |                               rail_coordinator
     |                                /   |   |    \
     |                       doctor planner completer validator
     |                          |       |       |
     |  <-- HTTP callback ------+-------+-------+
     |  (find_station_spot, get_engines, etc.)
     |                                    |
     |  <--- action JSON response --------|
     |
     v
  execute actions in OpenTTD
```

nttd sends game observations to the neuro-san server via HTTP. The agent
network reasons about route planning, and coded tools call back to nttd
for GS queries like `find_station_spot`. The final response is a JSON
action list that nttd executes in OpenTTD via GameScript.

All actions flow through `sly_data["action_list"]` -- coded tools append
actions to this list, and nttd reads the final list from the response.

## Agent Network

Defined in `registries/rail_mas.hocon`.

**rail_coordinator** (front man) -- calls agents in sequence each cycle:

1. **route_doctor** -- repairs incomplete routes: adds orders to vehicles
   with < 2 orders, retries failed builds from the previous cycle.
2. **route_completer** -- builds depots and buys vehicles for routes that
   have stations + track but no train yet. Auto-selects wagon type by
   matching station cargo to engine list.
3. **route_planner** -- selects the next unserved cargo route, validates
   station spots, checks finances, and queues station + track build actions.
4. **action_validator** -- deduplicates actions, filters unknown types,
   blocks disruptive actions against running trains.

**Shared agents:**
- **finance_advisor** -- checks affordability and adjusts loans. Called by
  both route_completer and route_planner.
- **company_status** -- diagnostic summary of company state.

## Coded Tools

All coded tools are under `coded_tools/rail_mas/` and implement
`neuro_san.interfaces.coded_tool.CodedTool`.

### Route planning tools
| Tool | Description |
|------|-------------|
| `find_unserved_routes` | Returns cargo routes from observation not near existing stations |
| `build_route_actions` | Validates station spots via GS, emits station + track actions. Validates cargo chain. |
| `build_depot_and_vehicles` | Finds depot spot near track, builds depot + engine + wagons |

### Route repair tools
| Tool | Description |
|------|-------------|
| `check_vehicle_status` | Reports vehicles needing orders, orphan stations, failed actions |
| `pair_orphan_stations` | Pairs orphan stations by proximity into likely route endpoints |
| `build_repair_actions` | Creates add_order + start_vehicle actions for incomplete vehicles |
| `retry_failed_actions` | Retries failed actions from previous cycle with adjusted parameters |

### Finance tools
| Tool | Description |
|------|-------------|
| `check_finances` | Returns balance, loan, affordability assessment |
| `set_loan_action` | Prepends a set_loan action to the action list |

### Validation tools
| Tool | Description |
|------|-------------|
| `validate_action_list` | Deduplicates, filters, blocks unsafe actions |

### GS query tools (HTTP callbacks to nttd)
| Tool | Description |
|------|-------------|
| `find_station_spot` | Validates rail station placement near industries |
| `find_rail_depot_spot` | Finds depot spots adjacent to existing track |
| `get_engines` | Lists available train engines and wagons |
| `get_rail_types` | Lists available rail track types |

### Utilities
| File | Description |
|------|-------------|
| `nttd_client.py` | HTTP client for GS queries to nttd API |
| `observation_util.py` | Parses and caches observation from sly_data |
| `cargo_matcher.py` | Matches cargo labels to wagons from engine list |
| `read_company_status.py` | Builds diagnostic company summary from observation |

## Setup

### Environment Variables

```bash
# LLM API key (used by neuro-san for agent reasoning)
export OPENAI_API_KEY="sk-..."

# nttd server URL (coded tools call back to this)
export NTTD_API_URL="http://localhost:8000"
export NTTD_TIMEOUT="30.0"

# Neuro-SAN paths
export AGENT_MANIFEST_FILE="$(pwd)/examples/neuro_san_mas/registries/manifest.hocon"
export AGENT_TOOL_PATH="$(pwd)/examples/neuro_san_mas/coded_tools"
export PYTHONPATH="$(pwd)/examples/neuro_san_mas/coded_tools:${PYTHONPATH}"

# Neuro-SAN server config
export AGENT_HTTP_PORT=8080
export AGENT_MCP_ENABLE="false"
```

### Running

```bash
# Terminal 1: Start nttd server + session
nttd server start

# Terminal 2: Start neuro-san server
python -m neuro_san.service.main_loop.server_main_loop

# Terminal 3: Run benchmark (creates session, registers agent, runs)
nttd benchmark run config/scenario_20min_rail_mas.conf
```

### nttd Scenario Config

The rail MAS agent is configured in `config/scenario_20min_rail_mas.conf`:

```hocon
agents = [
  {
    agent_id          = "rail_mas"
    company_id        = 0
    nttd_framework    = "mas"
    agent_type        = "rail"
    observation_mode  = "mas_rail"
    include_finance   = true
    poll_interval     = 10.0
    max_actions_per_cycle = 50
    mas_transport {
      protocol      = "http"
      mas_framework = "neuro_san"
      endpoint      = "http://localhost:8080/api/v1/rail_mas/streaming_chat"
      timeout       = 300.0
    }
  }
]
```

See `docs/agent_guide.md` for full configuration reference.

## File Structure

```
examples/neuro_san_mas/
  registries/
    manifest.hocon              # Lists agent networks to serve
    rail_mas.hocon              # Rail agent network definition (HOCON)
  coded_tools/
    rail_mas/
      __init__.py
      nttd_client.py            # HTTP client for GS queries
      observation_util.py       # Parse/cache observation from sly_data
      cargo_matcher.py          # Cargo-to-wagon matching
      find_unserved_routes.py   # Route discovery from observation
      build_route_actions.py    # Station + track action builder
      build_depot_and_vehicles.py  # Depot + train action builder
      check_vehicle_status.py   # Vehicle/station diagnostics
      pair_orphan_stations.py   # Station pairing by proximity
      build_repair_actions.py   # Order + start actions for vehicles
      retry_failed_actions.py   # Retry logic for failed actions
      check_finances.py         # Financial assessment
      set_loan_action.py        # Loan adjustment actions
      validate_action_list.py   # Action dedup and safety filtering
      read_company_status.py    # Company status summary
      find_station_spot.py      # GS query: station placement
      find_rail_depot_spot.py   # GS query: depot placement
      get_engines.py            # GS query: available engines
      get_rail_types.py         # GS query: available rail types
```
