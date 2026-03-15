# nttd Implementation Plan

## Phase 1 — MVP

### 1. OpenTTD Server Setup
- [x] Dedicated server config with admin port enabled (`ottd_config/openttd.cfg`)
- [x] Start script (`scripts/start_openttd_server.sh`)
- [x] `allow_insecure_admin_login = true` for pyopenttdadmin compatibility
- [x] Document server setup/run steps (README.md)
- [x] GameScript scaffold — loads into server, handles admin port events
- [x] GS message protocol: correlation IDs, JSON serialization, chunking (CHUNK_SIZE=10)
- [x] Config patching: start script patches `[game_scripts]` and `secrets.cfg` before launch
- [x] GS symlink into `~/Documents/OpenTTD/game/` for discovery

### 2. Game Bridge
- [x] Async Python admin port client — connect, auth, subscribe, rcon (`src/nttd/bridge/admin_client.py`)
- [x] Event wiring: admin port packets → WorldState updates (`src/nttd/bridge/bridge.py`)
- [x] Welcome packet → map dimensions, landscape, start date
- [x] Company info + economy subscriptions
- [x] Date tracking from server updates
- [x] GS message send/receive with correlation-based request/response
- [x] Null-terminator stripping for GS response JSON parsing
- [x] Chunked response reassembly with `_chunk`/`_total` ordering
- [x] GAMESCRIPT subscription for receiving GS responses
- [ ] Reconnect + resync logic (currently: connect once, no auto-reconnect)
- [ ] Detect save/load/newgame and notify agents of world reset

### 3. GameScript Commands (40+ implemented)
- [x] Query commands: ping, get_date, get_map_size, get_tile_info
- [x] Entity queries: get_towns, get_town_info, get_industries, get_industry_info, get_companies
- [x] Company-scoped queries: get_stations, get_vehicles, get_engines
- [x] Reference queries: get_cargo_types, get_rail_types, get_road_types
- [x] Smart queries: scan_town_area, find_bus_stop_spots, find_depot_spots
- [x] Road building: build_road, build_road_line, build_road_depot, build_road_stop
- [x] Rail building: build_rail (2-tile + 3-tile), build_rail_station, build_rail_depot, build_rail_signal
- [x] Other building: build_airport, build_dock, build_bridge, build_tunnel, demolish_tile
- [x] Vehicles: buy_vehicle, sell_vehicle, start_vehicle, stop_vehicle, send_to_depot, clone_vehicle, refit_vehicle
- [x] Orders: add_order, get_orders
- [x] Error handling with GSError.GetLastErrorString()
- [x] GSCompanyMode for all company-scoped operations
- [x] Automatic response chunking for large arrays
- [x] Live end-to-end verified: all query commands tested against real OpenTTD 15.2 server

### 4. Observation Layer
- [x] Canonical state model: game, company, town, industry, station, vehicle (`src/nttd/schemas/`)
- [x] Snapshot with epoch tagging: game_date, tick, snapshot_id (`src/nttd/schemas/snapshot.py`)
- [x] WorldState in-memory store, bridge writes, API reads (`src/nttd/state/world.py`)
- [x] GS query endpoints for all state domains (`/state/gs/query`)
- [ ] Populate WorldState from GS queries (currently: admin port data only, GS queries are pass-through)
- [ ] Delta detection via snapshot diffing
- [ ] Compressed/summary views for LLMs

### 5. Action Layer
- [x] JSON action envelope schema: action_id, company_id, mode, action_type, parameters (`src/nttd/schemas/action_envelope.py`)
- [x] Action result tracking with status lifecycle (`src/nttd/schemas/action_result.py`, `src/nttd/actions/tracker.py`)
- [x] GS execute endpoint (`/actions/gs/execute`) — direct GameScript command execution
- [ ] Action validation against current game state (currently: stub)
- [ ] Action envelope → GS command translation (currently: agents use GS commands directly)

### 6. Agent Connection API
- [x] `/agents/connect` — register agent, declare company scope
- [x] `/agents/{id}/disconnect`, `/agents/{id}/status`, `/agents/list`
- [x] Subscription registration by entity type, event type, cadence
- [x] WebSocket push (`/ws/{agent_id}`) with snapshot delivery based on subscription cadence
- [x] REST polling fallback (all `/state/*` endpoints)
- [x] Ping/pong keepalive on WebSocket
- [x] Reject WebSocket for unknown agents (code 4004)

### 7. FastAPI Service
- [x] Control API: `/session/status`, `pause`, `unpause`, `speed`, `mode`, `stop`, `heartbeat/interval`, `rcon`
- [x] Observation API: `/state/full`, `/state/company/{id}`, `/state/towns`, `industries`, `stations`, `vehicles`
- [x] Action API: `/actions/submit`, `validate`, `{id}/status`, `recent`
- [x] GS pass-through: `/state/gs/query`, `/actions/gs/execute`
- [x] Health endpoint with OpenTTD connection status
- [x] Async lifespan: connect bridge on startup, disconnect on shutdown
- [x] Offline mode fallback when OpenTTD not available
- [ ] `/session/save`, `/session/load` endpoints
- [ ] `/actions/batch_submit`, `/actions/{id}/cancel` endpoints

### 8. Runtime Modes
- [x] Heartbeat mode — pause → snapshot → notify observers → unpause → wait N game-days → repeat
- [x] Async real-time mode — game runs continuously, periodic snapshots pushed every 2s
- [x] Game speed control via `/session/speed`
- [x] Orchestrator with observer pattern for snapshot broadcast to WebSocket clients
- [x] Heartbeat interval configurable via `/session/heartbeat/interval`
- [ ] Assisted mode — human triggers AI via command, pause/plan/execute/unpause (skeleton only)
- [ ] Heartbeat mode: collect actions from agents before unpausing (currently: notify only)

### 9. Example Agent Client
- [x] Plain Python script: connect → subscribe → observe → act (`examples/agent_client.py`)
- [x] REST mode and WebSocket mode (`--ws` flag)
- [x] Demonstrates the full API flow
- [x] Serves as documentation for agent builders

### 10. Tests
- [x] API tests: health, session status, pause/unpause, speed, mode, agent lifecycle, full state, submit action (10 tests)
- [x] WebSocket tests: reject unknown agent, ping/pong
- [x] Live end-to-end test verified: OpenTTD server + nttd API + GS communication working

### 11. Project Setup
- [x] GitHub repo (private, `deepsaia/nttd`)
- [x] `.gitignore` — Python, OpenTTD runtime files, secrets, save games
- [x] README with full setup, API reference, GS command reference, architecture

---

## Phase 1 — Remaining Work (Priority Order)

1. **State enrichment via GS** — periodically query GS for towns/industries/vehicles/stations and populate WorldState, so `/state/*` endpoints return rich data (not just admin port basics).
2. **Action envelope → GS translation** — map action envelope `action_type` field to GS commands, so agents can use the typed action API instead of raw GS commands.
3. **Heartbeat action collection** — after delivering snapshot, wait for agent actions before unpausing.
4. **Assisted mode** — human triggers AI via chat/command, game pauses, AI plans, human approves, execute, unpause.
5. **Reconnect logic** — auto-reconnect bridge on connection loss, resync state.
6. **Save/load endpoints** — `/session/save`, `/session/load` via rcon.
7. **Structured logging** — log observations, actions, results to SQLite or JSON.
8. **Gym wrapper** — single-agent heartbeat env with reset/step/reward.
9. **Basic dashboard** — A tensorboardx dashboard prototype showing game state, KPIs, action timeline.

---

## Phase 2 — Production Research Platform

- [ ] Per-company isolation (GSCompanyMode orchestration across agents)
- [ ] Advanced subscriptions (region-based, backpressure, coalescing)
- [ ] PettingZoo multi-agent wrapper
- [ ] Event-driven delta detection (GS polling + snapshot diffing)
- [ ] Compound action decomposition (A* pathfinding, rail corridor builder)
- [ ] Idempotency keys + precondition hashes
- [ ] Circuit breakers per company
- [ ] Redis/NATS event bus + Postgres for durable logs
- [ ] Save/load + benchmark packs (config presets, map seeds, reward configs)
- [ ] Observability traces (OpenTelemetry-style)
- [ ] Derived views (cashflow forecast, buildable area scan)
- [ ] Action masking for RL
- [ ] Checkpoint/recovery (savegame + nttd metadata + action queue state)

---

## Phase 3 — Scale & RL

- [ ] Tactical rule-based policy workers for async real-time mode
- [ ] LLM strategic planner with periodic replans
- [ ] Latency class routing (strategic/tactical/execution agents)
- [ ] Distributed experiments (multiple OpenTTD instances)
- [ ] Reward shaping + offline dataset export
- [ ] Full canonical state extraction for large maps
- [ ] Training data pipelines (Parquet, object storage)
- [ ] Benchmark families: growth, efficiency, robustness, competition
