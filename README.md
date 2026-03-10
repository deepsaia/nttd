# nttd

Agent-agnostic API server for OpenTTD AI simulation. Agents connect via REST/WebSocket, subscribe to game observations, and submit actions — no framework lock-in.

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
uv sync
```

### Run

**Terminal 1** — Start OpenTTD dedicated server:
```bash
./scripts/start_openttd_server.sh
```

This script:
- Patches `ottd_config/openttd.cfg` to select the nttd GameScript
- Ensures the admin password is set in `ottd_config/secrets.cfg`
- Symlinks the GameScript into `~/Documents/OpenTTD/game/` for discovery
- Launches OpenTTD as a dedicated server with a new random game

To load a savegame instead:
```bash
./scripts/start_openttd_server.sh path/to/save.sav
```

**Terminal 2** — Start nttd API server:
```bash
uv run uvicorn nttd.api.app:app --reload
```

The API starts on `http://localhost:8000`. If OpenTTD is running, it auto-connects to the admin port on startup.

**Terminal 3** (optional) — Join as a human player:
Open OpenTTD normally → Multiplayer → Add server `127.0.0.1:3979` → Join

### Verify Everything Works

```bash
# Check health (should show openttd_connected: true)
curl -s http://localhost:8000/health | python -m json.tool

# Query towns via GameScript
curl -s -X POST 'http://localhost:8000/state/gs/query?action=get_towns' | python -m json.tool

# Query industries
curl -s -X POST 'http://localhost:8000/state/gs/query?action=get_industries' | python -m json.tool
```

### Try the Example Agent

```bash
# REST mode — connect, observe, act, disconnect
uv run python examples/agent_client.py

# WebSocket mode — real-time snapshot streaming
uv run python examples/agent_client.py --ws
```

### Run Tests

```bash
uv run pytest
```

### Test the Bridge Directly

```bash
uv run python scripts/test_bridge.py
```

---

## Configuration

### OpenTTD Server

Config lives in `ottd_config/`. Key files:

| File | Purpose | Committed? |
|------|---------|------------|
| `openttd.cfg` | Main server config (ports, game settings) | Yes |
| `secrets.cfg` | Admin password, crypto keys | No (gitignored) |
| `private.cfg` | Client/server names | No (auto-generated) |
| `game/nttd-gs/` | nttd GameScript (Squirrel) | Yes |
| `scripts/autoexec.scr` | Commands run on server start | Yes |

Key settings in `openttd.cfg`:
- `server_admin_port = 3977` — admin port for nttd to connect to
- `server_port = 3979` — game port for human players
- `allow_insecure_admin_login = true` — required for pyopenttdadmin

The admin password is `nttd`, stored in `secrets.cfg` (auto-created on first run if missing).

### nttd API Server

Environment variables (all optional, defaults shown):

| Variable | Default | Description |
|----------|---------|-------------|
| `NTTD_ADMIN_HOST` | `127.0.0.1` | OpenTTD admin port host |
| `NTTD_ADMIN_PORT` | `3977` | OpenTTD admin port |
| `NTTD_ADMIN_PASSWORD` | `nttd` | Admin password |

---

## GameScript

The nttd GameScript (`ottd_config/game/nttd-gs/`) runs inside OpenTTD and acts as the execution bridge for commands that the admin port can't handle natively. Communication uses JSON messages over the admin port's GameScript channel.

### Protocol

```
Client → nttd API → admin port → GameScript → response → admin port → nttd API → Client
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
| `ping` | — | `{pong: true}` |
| `get_date` | — | year, month, day, date |
| `get_map_size` | — | size_x, size_y, max_x, max_y |
| `get_tile_info` | `x, y` | height, slope, buildable, water, owner |
| `get_towns` | — | Array of {id, name, population, x, y} |
| `get_town_info` | `town_id` | Detailed town: population, houses, growth_rate, is_city |
| `get_industries` | — | Array of {id, name, type_id, type_name, x, y} |
| `get_industry_info` | `industry_id` | Detailed industry with production data |
| `get_companies` | — | Array of {id, name, money, loan, hq_x, hq_y} |
| `get_stations` | `company_id` | Array of stations with type flags |
| `get_vehicles` | `company_id`, `vehicle_type?` | Array of vehicles with profit, state, orders |
| `get_engines` | `vehicle_type?` | Buildable engines with stats |
| `get_cargo_types` | — | All cargo types |
| `get_rail_types` | — | Available rail types |
| `get_road_types` | — | Available road/tram types |

**Smart Queries**:

| Action | Params | Returns |
|--------|--------|---------|
| `scan_town_area` | `town_id`, `radius?` | Classified tiles: buildable, roads, buildings, water |
| `find_bus_stop_spots` | `town_id`, `radius?`, `max_results?` | Buildable tiles adjacent to roads, sorted by distance |
| `find_depot_spots` | `town_id`, `radius?`, `max_results?` | Depot-suitable tiles with direction |

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
| `build_bridge` | `start_x/y, end_x/y, bridge_type?, transport_type?` |
| `build_tunnel` | `x, y, transport_type?` |
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

**Orders** (require `company_id`):

| Action | Key Params |
|--------|------------|
| `add_order` | `vehicle_id, station_id, order_flags?` |
| `get_orders` | `vehicle_id` |

### Using GS Commands via the API

Query endpoint (for read-only operations):
```bash
curl -X POST 'http://localhost:8000/state/gs/query?action=get_towns'
```

Execute endpoint (for actions that modify game state):
```bash
curl -X POST 'http://localhost:8000/actions/gs/execute?action=buy_vehicle' \
  -H 'Content-Type: application/json' \
  -d '{"company_id": 0, "depot_x": 100, "depot_y": 50, "engine_id": 15}'
```

---

## REST API Reference

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Server + OpenTTD connection status |

### Control (`/session`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/session/status` | Current game state (date, mode, paused, speed) |
| POST | `/session/pause` | Pause the game |
| POST | `/session/unpause` | Unpause the game |
| POST | `/session/speed?speed=N` | Set game speed |
| POST | `/session/mode?mode=MODE` | Switch runtime mode |
| POST | `/session/stop` | Stop the orchestrator |
| POST | `/session/heartbeat/interval?days=N` | Set heartbeat interval |
| POST | `/session/rcon?command=CMD` | Send rcon command to OpenTTD |

### Agent Connection (`/agents`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/agents/connect` | Register agent with company scope |
| POST | `/agents/{id}/disconnect` | Disconnect agent |
| GET | `/agents/{id}/status` | Agent status and subscriptions |
| GET | `/agents/list` | List all connected agents |
| POST | `/agents/{id}/subscriptions` | Subscribe to observation channel |
| DELETE | `/agents/{id}/subscriptions/{channel}` | Unsubscribe |
| GET | `/agents/{id}/subscriptions` | List agent's subscriptions |

### Observation (`/state`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/state/full` | Full state snapshot |
| GET | `/state/company/{id}` | Single company |
| GET | `/state/towns` | All towns |
| GET | `/state/industries` | All industries |
| GET | `/state/stations` | All stations |
| GET | `/state/vehicles` | All vehicles |
| POST | `/state/gs/query?action=X` | Query GameScript (body: params JSON) |

### Actions (`/actions`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/actions/submit` | Submit an action envelope |
| POST | `/actions/validate` | Validate without executing |
| GET | `/actions/{id}/status` | Check action result |
| GET | `/actions/recent` | Recent actions |
| POST | `/actions/gs/execute?action=X` | Execute GameScript command (body: params JSON) |

### WebSocket (`/ws`)

| Endpoint | Description |
|----------|-------------|
| `ws://host/ws/{agent_id}` | Real-time snapshot stream for connected agent |

Agents must first register via `POST /agents/connect`, then open a WebSocket at `/ws/{agent_id}`. The server pushes `{"type": "snapshot", "data": {...}}` based on subscription cadence. Send `{"type": "ping"}` to receive `{"type": "pong"}`.

---

## Runtime Modes

| Mode | Use Case | How It Works |
|------|----------|--------------|
| **heartbeat** | Benchmarks, RL, Gym | Pause → snapshot → notify agents → unpause → wait N days → repeat |
| **async_realtime** | Human co-play | Game runs continuously, periodic snapshots pushed to agents |
| **assisted** | Co-pilot | Human triggers AI; game pauses while AI thinks (skeleton) |

Switch modes at runtime:
```bash
curl -X POST 'http://localhost:8000/session/mode?mode=heartbeat'
```

---

## Architecture

```
Agent (any framework)
  |  REST / WebSocket
  v
[nttd API Server]  ── FastAPI ──────────────────────────────
  |  Control, Observation, Action, Agent routes
  |  GS query/execute endpoints
  v
[State Layer]      ── WorldState, AgentRegistry, ActionTracker
  |
  v
[Bridge]           ── Async TCP admin port client ──────────
  |                   Subscriptions, rcon, GS messaging
  |                   Chunked response reassembly
  v
[OpenTTD Server]   ── Dedicated server, admin port 3977 ───
  |
  v
[nttd GameScript]  ── Squirrel VM inside OpenTTD ──────────
                      40+ commands: queries, building,
                      vehicles, orders
```

### Key Files

```
src/nttd/
├── api/
│   ├── app.py              # FastAPI app, lifespan, router wiring
│   ├── control_routes.py   # /session/* endpoints
│   ├── agent_routes.py     # /agents/* endpoints
│   ├── observation_routes.py # /state/* + /state/gs/query
│   ├── action_routes.py    # /actions/* + /actions/gs/execute
│   ├── ws_routes.py        # WebSocket /ws/{agent_id}
│   └── dependencies.py     # Shared state singletons
├── bridge/
│   ├── admin_client.py     # Async TCP client, GS messaging, chunking
│   └── bridge.py           # Admin packets → WorldState updates
├── runtime/
│   └── orchestrator.py     # Heartbeat + async_realtime loops
├── state/
│   ├── world.py            # In-memory game state
│   └── agent_registry.py   # Agent lifecycle + subscriptions
├── schemas/                # Pydantic models (game, company, town, ...)
└── actions/
    └── tracker.py          # Action lifecycle tracking

ottd_config/
├── openttd.cfg             # Server configuration
└── game/nttd-gs/
    ├── info.nut            # GS metadata (name, version, API)
    └── main.nut            # GS command handlers

scripts/
├── start_openttd_server.sh # Launch OpenTTD dedicated server
└── test_bridge.py          # Manual bridge connection test

examples/
└── agent_client.py         # Example agent (REST + WebSocket)
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

1. Start OpenTTD: `./scripts/start_openttd_server.sh`
2. Start nttd: `uv run uvicorn nttd.api.app:app --reload`
3. Test bridge: `uv run python scripts/test_bridge.py`
4. Test GS commands via curl (see examples above)

### Modifying the GameScript

The GameScript lives in `ottd_config/game/nttd-gs/main.nut`. After editing:
1. Stop the OpenTTD server (Ctrl+C)
2. Restart: `./scripts/start_openttd_server.sh`

OpenTTD compiles the GS on startup. Check the server output for compilation errors — they show the file path and line number.

Note: `clone` is a reserved keyword in Squirrel. Other Squirrel gotchas: no `null` coalescing, `typeof` returns strings, tables use `rawset()` for dynamic keys.

---

## Docs

- [Architecture Report](docs/nttd_architecture_report.md) — full design document with feasibility annotations
- [Implementation Plan](plan.md) — phased task breakdown with status
