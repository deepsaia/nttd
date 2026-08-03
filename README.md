# nttd

Agent-agnostic API server for OpenTTD AI simulation. Agents connect via REST/WebSocket, subscribe to game observations, and submit actions. No framework lock-in.

nttd wraps an OpenTTD dedicated server and exposes it as a structured JSON API. An in-game GameScript handles queries and actions that the admin port alone can't provide (towns, industries, vehicles, building, etc.).

---

## Quick Start

### Prerequisites

- Python 3.13+, [uv](https://docs.astral.sh/uv/)
- [OpenTTD 15.x](https://www.openttd.org/) installed (macOS: `/Applications/OpenTTD.app`)
- [OpenGFX](https://www.openttd.org/downloads/opengfx-releases/latest) base graphics set

### Install

```bash
git clone git@github.com:deepsaia/nttd.git
cd nttd
uv sync --extra agents    # includes LangChain + OpenAI adapters
```

To install Openttd game on your system, follow the instructions at: https://www.openttd.org/downloads/openttd-releases/latest
After installation, run the game.  
You might want to install `OpenGFX2 Classic`, `OpenSFX (sound)` and `OpenMSX (music)` from the Online Content explorer when you
run the game for the first time. `OpenSFX (sound)` and `OpenMSX (music)` are optional and not required for gameplay.  
Quick check: When you restart the game -> Online Content -> Search for the keyword `Open`,
you should see a green dot in front of your installed content.

### Run Benchmarks

You can follow [cli_guide.md](docs/cli_guide.md) for detailed CLI guide.

From project root

On one terminal
```bash
nttd server
```

[Optional] On second terminal (If running neuro-san based multi-agent systems)
```bash
nttd mas neuro-san
```

Then on another terminal
```bash
nttd benchmark --config config/scenario_30min_3agent.conf
```
> [!TIP]
> Note: Pick the appropriate benchmark config file from `nttd/config/` dir
> You should see a session id generated when a sessoin begins. 
> The id goes like this ses_<hex_code>

Observability:
Then on yet another terminal,
```bash
nttd analyze -r orders,financial,session_summary,action_analysis,agent_performance,cargo_delivery,token_accounting -s ses_xyz
```
Note: The session id is your own session ID

---

### Run an AI Agent (step by step)

```bash
# 1. Start the nttd API server
uv run uvicorn nttd.api.app:app --host 0.0.0.0 --port 8000

# 2. Verify it's running (in another terminal)
curl -s http://localhost:8000/health | python3 -m json.tool

# 3. Create a session
SESSION=$(curl -s -X POST http://localhost:8000/admin/sessions/new \
  -H "Content-Type: application/json" \
  -d '{"name": "my-first-run"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")
echo "Session: $SESSION"

# 4. Start the session (spawns an OpenTTD dedicated server)
#    agent_companies=1 creates company 0 for the agent to control
curl -s -X POST "http://localhost:8000/admin/sessions/$SESSION/start" \
  -H "Content-Type: application/json" \
  -d '{"agent_companies": 1}'

# 5. Wait for OpenTTD to initialize and GS to connect (~5s)
sleep 5

# 6. Set runtime mode and unpause
curl -s -X POST "http://localhost:8000/sessions/$SESSION/mode?mode=async_realtime"
curl -s -X POST "http://localhost:8000/sessions/$SESSION/unpause"
sleep 5

# 7. Verify the world is populated
curl -s "http://localhost:8000/sessions/$SESSION/state/compact?company_id=0" | python3 -m json.tool

# 8. Set your LLM API key
export OPENAI_API_KEY=sk-...

# 9. Register an AI agent with the gameloop
curl -s -X POST "http://localhost:8000/sessions/$SESSION/gameloop/agents/register" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "bus_builder",
    "company_id": 0,
    "framework": "openai",
    "model": "gpt-5.2",
    "agent_type": "bus",
    "poll_interval": 15.0,
    "observation_tools": true
  }'

# 10. Start the agent cycle loop
curl -s -X POST "http://localhost:8000/sessions/$SESSION/gameloop/agents/bus_builder/start"

# The agent is now running! It will observe, call tools, decide, and act autonomously.
```

### Monitor the Agent

```bash
# Agent status (cycle count, actions, timing)
curl -s "http://localhost:8000/sessions/$SESSION/gameloop/agents/bus_builder/status" | python3 -m json.tool

# Recent cycle details
curl -s "http://localhost:8000/sessions/$SESSION/gameloop/agents/bus_builder/cycles" | python3 -m json.tool

# Overall gameloop status
curl -s "http://localhost:8000/sessions/$SESSION/gameloop/status" | python3 -m json.tool

# Live game state (company balance, vehicles, stations)
curl -s "http://localhost:8000/sessions/$SESSION/state/compact?company_id=0" | python3 -m json.tool
```

### Spectate in OpenTTD

While agents run, connect to the game to watch:
1. Open OpenTTD
2. Multiplayer > Add server > `127.0.0.1:<game_port>` (shown in session start response)
3. Join as spectator (company 255)
4. Watch AI companies build infrastructure in real time

### Stop Everything

```bash
# Stop the agent
curl -s -X POST "http://localhost:8000/sessions/$SESSION/gameloop/agents/bus_builder/stop"

# Stop the session (kills OpenTTD process)
curl -s -X POST "http://localhost:8000/admin/sessions/$SESSION/stop"

# Stop the server
kill $(lsof -ti :8000)
```

### Run Multiple Agents

Multiple agents can share the same company, each handling a different transport mode:

```bash
# Register 3 agents on company 0
for AGENT_TYPE in rail air water; do
  curl -s -X POST "http://localhost:8000/sessions/$SESSION/gameloop/agents/register" \
    -H "Content-Type: application/json" \
    -d "{
      \"agent_id\": \"${AGENT_TYPE}-agent\",
      \"company_id\": 0,
      \"framework\": \"openai\",
      \"model\": \"gpt-5.2\",
      \"agent_type\": \"${AGENT_TYPE}\"
    }"
done

# Start all 3
for AGENT_TYPE in rail air water; do
  curl -s -X POST "http://localhost:8000/sessions/$SESSION/gameloop/agents/${AGENT_TYPE}-agent/start"
done
```

### Run Tests

```bash
uv run pytest
```

---

## Configuration

### OpenTTD Server

nttd manages OpenTTD server processes automatically. When you start a session (`POST /admin/sessions/{id}/start`), nttd spawns a dedicated OpenTTD server, assigns ports, installs the GameScript, and connects via the admin port. You do not need to start OpenTTD manually.

Base configuration lives in `ottd_config/`:

| File | Purpose | Committed? |
|------|---------|------------|
| `openttd.cfg` | Main server config (ports, game settings) | Yes |
| `secrets.cfg` | Admin password, crypto keys | No (gitignored, auto-created) |
| `private.cfg` | Client/server names | No (auto-generated) |
| `game/nttd-gs/` | nttd GameScript (Squirrel) | Yes |

Each session gets its own copy of the config with unique ports. Ports are allocated from `NTTD_PORT_RANGE_START` (default 4000): game_port, admin_port pairs per session.

The admin password is `openttd`, stored in `secrets.cfg`.

### nttd API Server

Environment variables (all optional, defaults shown):

| Variable | Default | Description |
|----------|---------|-------------|
| `NTTD_OPENTTD_BINARY` | `/Applications/OpenTTD.app/Contents/MacOS/openttd` | Path to OpenTTD binary |
| `NTTD_BASE_CONFIG` | `ottd_config` | Base config directory |
| `NTTD_SESSIONS_DIR` | `runs` | Session data directory |
| `NTTD_DB_PATH` | `nttd.db` | SQLite database path |
| `NTTD_ADMIN_PASSWORD` | `nttd` | OpenTTD admin port password |
| `NTTD_PORT_RANGE_START` | `4000` | First port for sessions |
| `OPENAI_API_KEY` | | Required for `openai` and `langchain` adapters |
| `ANTHROPIC_API_KEY` | | Required for Anthropic models via `langchain` adapter |

---

## GameScript

The nttd GameScript (`ottd_config/game/nttd-gs/`) runs inside OpenTTD and acts as the execution bridge for commands that the admin port can't handle natively. Communication uses JSON messages over the admin port's GameScript channel.

### Protocol

```
Client > nttd API > admin port > GameScript > response > admin port > nttd API > Client
```

Command format:
```json
{"id": "gs_1", "action": "get_towns", "params": {}}
```

Response format:
```json
{"id": "gs_1", "success": true, "result": [...]}
```

Large array responses are automatically chunked (10 items per packet) to stay under the ~1400 byte admin port limit. Chunks include `_chunk` and `_total` fields and are reassembled by the Python client.

### Available Commands

**Queries** (no company_id needed for most):

| Action | Params | Returns |
|--------|--------|---------|
| `ping` | | `{pong: true}` |
| `get_date` | | year, month, day, date |
| `get_map_size` | | size_x, size_y, max_x, max_y |
| `get_tile_info` | `x, y` | height, slope, buildable, water, owner |
| `get_towns` | | Array of {id, name, population, x, y} |
| `get_town_info` | `town_id` | Detailed town: population, houses, growth_rate, is_city |
| `get_industries` | | Array of {id, name, type_id, type_name, x, y} |
| `get_industry_info` | `industry_id` | Detailed industry with production data |
| `get_companies` | | Array of {id, name, money, loan, hq_x, hq_y} |
| `get_company_finance` | `company_id` | balance, loan, max_loan, quarterly income/expenses |
| `get_stations` | `company_id` | Array of stations with type flags |
| `get_vehicles` | `company_id`, `vehicle_type?` | Array of vehicles with profit, state, orders |
| `get_engines` | `vehicle_type?` | Buildable engines with stats |
| `get_cargo_types` | | All cargo types |
| `get_rail_types` | | Available rail types |
| `get_road_types` | | Available road/tram types |
| `get_groups` | `company_id` | Vehicle groups |
| `get_signs` | | Map signs |
| `get_waypoints` | `company_id` | Rail waypoints |

**Smart Queries** (dry-run validated via GSTestMode where noted):

| Action | Params | Returns |
|--------|--------|---------|
| `scan_town_area` | `town_id`, `radius?` | Classified tiles: buildable, roads, buildings, water |
| `find_bus_stop_spots` | `company_id`, `town_id`, `max_results?` | Buildable tiles adjacent to roads, sorted by distance |
| `find_depot_spots` | `company_id`, `town_id`, `max_results?` | Depot-suitable tiles with direction |
| `find_airport_spots` | `company_id`, `town_id`, `airport_type?`, `max_results?` | GSTestMode-validated flat areas for airports |
| `find_dock_spots` | `company_id`, `town_id`, `max_results?` | GSTestMode-validated coast tiles for docks |
| `find_water_depot_spots` | `company_id`, `town_id` or `tile`, `max_results?` | GSTestMode-validated water tiles for ship depots |
| `find_flat_spots` | `tile`, `radius?`, `min_size?`, `max_results?` | Flat buildable tiles near a given tile (for rail) |
| `get_hangars` | `company_id` | Airport hangar/depot tiles for buying aircraft |
| `get_subsidies` | | Active subsidies with cargo, source, destination |
| `get_airport_types` | | Available airport types with dimensions |
| `get_bridge_types` | | Available bridge types with speed limits |
| `get_town_rating` | `company_id`, `town_id` | Local authority rating for company in town |

**Building** (all require `company_id`):

| Action | Key Params |
|--------|------------|
| `build_road` | `from_x, from_y, to_x, to_y` |
| `build_road_line` | `from_x, from_y, to_x, to_y` (straight line, tile by tile) |
| `build_road_depot` | `x, y, direction` |
| `build_road_stop` | `x, y, direction, is_truck_stop?, is_drive_through?` |
| `build_rail` | 3-tile: `prev_x/y, x/y, next_x/y` or 2-tile: `from_x/y, to_x/y` |
| `build_rail_station` | `x, y, direction, num_platforms?, platform_length?` |
| `build_rail_depot` | `x, y, direction` |
| `build_rail_signal` | `x, y, signal_type?` |
| `build_airport` | `x, y, airport_type?` |
| `build_dock` | `x, y` |
| `build_water_depot` | `x, y` |
| `build_canal` | `x, y` |
| `build_lock` | `x, y` |
| `build_buoy` | `x, y` |
| `build_bridge` | `start_x/y, end_x/y, bridge_type?, transport_type?` |
| `build_tunnel` | `x, y, transport_type?` |
| `build_rail_waypoint` | `x, y, rail_type?` |
| `build_sign` | `x, y, text` |
| `build_company_hq` | `x, y` |
| `set_loan` | `amount` |
| `demolish_tile` | `x, y` |

**Vehicles** (all require `company_id`):

| Action | Key Params |
|--------|------------|
| `buy_vehicle` | `depot_x, depot_y, engine_id` |
| `sell_vehicle` | `vehicle_id` |
| `start_vehicle` | `vehicle_id` |
| `stop_vehicle` | `vehicle_id` |
| `send_to_depot` | `vehicle_id` |
| `clone_vehicle` | `vehicle_id, share_orders?` |
| `refit_vehicle` | `vehicle_id, cargo_id` |
| `reverse_vehicle` | `vehicle_id` |
| `rename_vehicle` | `vehicle_id, name` |
| `sell_wagon` | `vehicle_id, wagon_id` |
| `move_wagon` | `source_vehicle_id, dest_vehicle_id, wagon_id` |

**Orders** (require `company_id`):

| Action | Key Params |
|--------|------------|
| `add_order` | `vehicle_id, station_id` or `destination` (tile) |
| `insert_order` | `vehicle_id, position, station_id` |
| `remove_order` | `vehicle_id, position` |
| `skip_to_order` | `vehicle_id, position` |
| `get_orders` | `vehicle_id` |
| `share_orders` | `vehicle_id, main_vehicle_id` |
| `copy_orders` | `vehicle_id, main_vehicle_id` |

**Groups**:

| Action | Key Params |
|--------|------------|
| `create_group` | `company_id, vehicle_type, name` |
| `delete_group` | `group_id` |
| `move_to_group` | `group_id, vehicle_id` |
| `set_auto_replace` | `group_id, old_engine_id, new_engine_id` |

**Town/Deity** (GS-exclusive):

| Action | Key Params |
|--------|------------|
| `found_town` | `x, y, size, is_city?, layout?, name?` |
| `expand_town` | `town_id, times?` |
| `set_town_growth` | `town_id, days_between_growth` |
| `perform_town_action` | `company_id, town_id, action` |
| `change_town_rating` | `company_id, town_id, delta` |
| `create_subsidy` | `cargo_type, from_type, from_id, to_type, to_id` |

### Using GS Commands via the API

All endpoints are session-scoped: `/sessions/{session_id}/...`

Query endpoint (read-only operations):
```bash
curl -X POST "http://localhost:8000/sessions/$SESSION/state/gs/query?action=get_towns"
```

Execute endpoint (actions that modify game state):
```bash
curl -X POST "http://localhost:8000/sessions/$SESSION/actions/gs/execute?action=buy_vehicle" \
  -H 'Content-Type: application/json' \
  -d '{"company_id": 0, "depot_x": 100, "depot_y": 50, "engine_id": 15}'
```

---

## REST API Reference

All session-specific endpoints require a `{session_id}` path parameter.

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Server status + active sessions |

### Session Lifecycle (`/admin`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/admin/sessions/new` | Create a new session |
| GET | `/admin/sessions` | List all sessions |
| GET | `/admin/sessions/{id}` | Session details |
| POST | `/admin/sessions/{id}/start` | Start session (spawns OpenTTD) |
| POST | `/admin/sessions/{id}/stop` | Stop session (kills OpenTTD) |
| DELETE | `/admin/sessions/{id}` | Delete session record |
| POST | `/admin/sessions/{id}/settings` | Update session settings |

### Control (`/sessions/{id}`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/sessions/{id}/status` | Game state (date, mode, paused, speed) |
| POST | `/sessions/{id}/pause` | Pause the game |
| POST | `/sessions/{id}/unpause` | Unpause the game |
| POST | `/sessions/{id}/speed?speed=N` | Set game speed |
| POST | `/sessions/{id}/mode?mode=MODE` | Switch runtime mode |
| POST | `/sessions/{id}/rcon?command=CMD` | Send rcon command to OpenTTD |

### Gameloop / Agent Management (`/sessions/{id}/gameloop`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/sessions/{id}/gameloop/agents/register` | Register agent (JSON body: AgentConfig) |
| POST | `/sessions/{id}/gameloop/agents/{agent_id}/start` | Start agent cycle loop |
| POST | `/sessions/{id}/gameloop/agents/{agent_id}/stop` | Stop agent cycle loop |
| GET | `/sessions/{id}/gameloop/agents` | List all agents with status |
| GET | `/sessions/{id}/gameloop/agents/{agent_id}/status` | Agent details (cycles, actions, timing) |
| GET | `/sessions/{id}/gameloop/agents/{agent_id}/cycles?limit=50` | Recent cycle records |
| GET | `/sessions/{id}/gameloop/status` | Overall gameloop summary |

### Observation (`/sessions/{id}/state`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/sessions/{id}/state/compact?company_id=N` | Compact state for one company |
| GET | `/sessions/{id}/state/full` | Full state snapshot |
| GET | `/sessions/{id}/state/company/{cid}` | Single company details |
| GET | `/sessions/{id}/state/towns` | All towns |
| GET | `/sessions/{id}/state/industries` | All industries |
| GET | `/sessions/{id}/state/stations` | All stations |
| GET | `/sessions/{id}/state/vehicles` | All vehicles |
| POST | `/sessions/{id}/state/gs/query?action=X` | Query GameScript |

### Actions (`/sessions/{id}/actions`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/sessions/{id}/actions/interpret` | Submit actions for validation + execution |
| POST | `/sessions/{id}/actions/gs/execute?action=X` | Execute raw GS command |
| GET | `/sessions/{id}/actions/recent` | Recent action history |

### Metrics and Leaderboard

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/leaderboard/compute/{session_id}` | Compute session leaderboard |
| GET | `/leaderboard/session/{session_id}` | Get session rankings |
| GET | `/leaderboard/global` | Global rankings across sessions |

---

## Runtime Modes

| Mode | Use Case | How It Works |
|------|----------|--------------|
| **heartbeat** | Benchmarks, RL, Gym | Pause > snapshot > notify agents > unpause > wait N days > repeat |
| **async_realtime** | Human co-play | Game runs continuously, periodic snapshots pushed to agents |
| **assisted** | Co-pilot | Human triggers AI; game pauses while AI thinks (skeleton) |

Switch modes at runtime:
```bash
curl -X POST "http://localhost:8000/sessions/$SESSION/mode?mode=heartbeat"
```

---

## Architecture

```
Agent (any framework)
  |  REST / WebSocket
  v
[nttd API Server]     FastAPI
  |  Session management, gameloop, observation, action routes
  |  GS query/execute endpoints, metrics/leaderboard
  v
[Gameloop Manager]    Per-session agent lifecycle
  |  AgentConnection per agent: observe > decide > act > track
  |  31 observation tools, multi-turn LLM calling
  v
[Bridge]              Async TCP admin port client
  |                   Correlation IDs, chunked response reassembly
  v
[OpenTTD Server]      Dedicated server, admin port
  |
  v
[nttd GameScript]     Squirrel VM inside OpenTTD
                      90+ commands: queries, building,
                      vehicles, orders, smart finders (GSTestMode)
```

### Key Files

```
src/nttd/
├── api/
│   ├── app.py               # FastAPI app, lifespan, router wiring
│   ├── admin_routes.py      # /admin/sessions/* lifecycle endpoints
│   ├── gameloop_routes.py   # /sessions/{id}/gameloop/* agent management
│   ├── observation_routes.py # /sessions/{id}/state/* + gs/query
│   ├── action_routes.py     # /sessions/{id}/actions/* + gs/execute
│   ├── metrics_routes.py    # /leaderboard/* session metrics
│   └── dependencies.py      # Shared state singletons
├── bridge/
│   └── admin_client.py      # Async TCP client, GS messaging, chunking
├── runtime/
│   ├── session_manager.py   # Multi-session lifecycle management
│   └── session_runtime.py   # Per-session runtime (admin client, gameloop)
├── gameloop/
│   ├── manager.py           # GameloopManager: agent registration, lifecycle
│   ├── connection.py        # AgentConnection: observe-decide-act cycle
│   ├── observation_tools.py # 31 observation tools (OpenAI function format)
│   ├── schemas.py           # AgentConfig, ConnectionStatus, CycleRecord
│   └── adapters/            # OpenAI, LangChain, Passthrough adapters
├── db/
│   ├── engine.py            # SQLite/async engine setup
│   ├── tables.py            # 27 table definitions
│   ├── recorder.py          # SessionRecorder (batch flush to DB)
│   └── repositories/        # Query functions per domain
├── state/
│   ├── world.py             # In-memory game state
│   └── agent_registry.py    # Agent lifecycle + subscriptions
├── schemas/                 # Pydantic models (game, company, town, ...)
└── actions/
    ├── tracker.py           # Action lifecycle tracking
    └── interpreter.py       # Action validation + GS execution

ottd_config/
├── openttd.cfg              # Server configuration
└── game/nttd-gs/
    ├── info.nut             # GS metadata (name, version, API)
    └── main.nut             # 90+ GS command handlers

scripts/
├── start_openttd_server.sh  # Launch OpenTTD dedicated server
├── test_bridge.py           # Manual bridge connection test
└── generate_diagrams.py     # SVG diagram generator

examples/
├── agent_instructions.py    # Transport-type prompts (bus, rail, air, water)
└── langchain_nttd_agent.py  # Standalone LangChain agent example
```

---

## Development

### Lint

```bash
uv run ruff check src/ tests/
```

### Test

```bash
uv run pytest          # unit tests (no OpenTTD needed)
uv run pytest -v       # verbose
```

### Live Testing

1. Start nttd: `uv run uvicorn nttd.api.app:app --host 0.0.0.0 --port 8000`
2. Create and start a session (see Quick Start above)
3. Test GS commands via curl (see GameScript section)
4. Register and start agents (see Quick Start above)

### Modifying the GameScript

The GameScript lives in `ottd_config/game/nttd-gs/main.nut`. After editing:
1. Stop the session: `curl -s -X POST "http://localhost:8000/admin/sessions/$SESSION/stop"`
2. Start a new session (the new GS is compiled on OpenTTD startup)

OpenTTD compiles the GS on startup. Check the server logs for compilation errors; they show the file path and line number.

Note: `clone` is a reserved keyword in Squirrel. Other Squirrel gotchas: no `null` coalescing, `typeof` returns strings, tables use `rawset()` for dynamic keys.

---

## Docs

- [Architecture Report](docs/nttd_architecture_report.md): full design document with feasibility annotations, gameloop architecture, observation toolkit, agent prompt system, DB tracking
- [Blog: Building AI Agents That Play Transport Tycoon](docs/blog_building_ai_agents.md): how the gameloop works, transport specialist agents, multi-agent test results
- [CLI Guide](docs/cli_guide.md): command reference, HOCON configuration, REST API endpoints, troubleshooting
- [Implementation Plan](plan.md): phased task breakdown with status
- [Diagrams](docs/images/): architecture overview, gameloop cycle, transport modes (SVG)
