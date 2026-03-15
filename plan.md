# nttd Implementation Plan

## Phase 1 — MVP

### 1. OpenTTD Server Setup
- [x] Dedicated server config with admin port enabled (`ottd_config/openttd.cfg`)
- [x] Start script (`scripts/start_openttd_server.sh`)
- [x] `allow_insecure_admin_login = true` for pyopenttdadmin compatibility
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
- [ ] Reconnect + resync logic (currently: connect once, no auto-reconnect)
- [ ] Detect save/load/newgame and notify agents of world reset

### 3. GameScript — Full OpenTTD GS API Coverage (90+ commands)
- [x] Protocol: correlation IDs, JSON serialization, auto-chunking (CHUNK_SIZE=10)
- [x] Error handling via `GSError.GetLastErrorString()` + Squirrel exception catch
- [x] `GSCompanyMode` for all company-scoped operations
- [x] Queries: ping, get_date, get_map_size, get_tile_info
- [x] Entity queries: get_towns, get_town_info, get_industries, get_industry_info
- [x] Company: get_companies, get_company_finance, build_company_hq, set_loan, rename_company
- [x] Stations: get_stations, get_station_info, get_waypoints
- [x] Vehicles: get_vehicles, get_vehicle_info, get_engines
- [x] Reference: get_cargo_types, get_rail_types, get_road_types, get_airport_types, get_bridge_types
- [x] Smart queries: scan_town_area, find_bus_stop_spots, find_depot_spots
- [x] Road: build/remove road, road_line, road_depot, road_stop
- [x] Rail: build/remove rail (2-tile + 3-tile), rail_track, rail_station, rail_depot, rail_signal, rail_waypoint; convert_rail
- [x] Marine: build/remove canal, lock, buoy, water_depot
- [x] Other infra: build/remove airport, open_close_airport, dock, bridge, tunnel, demolish_tile
- [x] Town (GS-exclusive): found_town, expand_town, set_town_growth, perform_town_action, get_town_rating, change_town_rating, set_cargo_goal
- [x] Subsidies (GS-exclusive): get_subsidies, create_subsidy
- [x] Signs: build_sign, remove_sign, get_signs
- [x] Vehicle groups: get_groups, create_group, delete_group, move_to_group, set_auto_replace
- [x] Vehicles: buy, sell, sell_wagon, move_wagon, start, stop, send_to_depot, send_to_depot_service, clone, refit, reverse, rename
- [x] Orders: add, insert, remove, skip_to, move, set_flags, share, copy, get_orders
- [x] GS documentation: `ottd_config/README.md` — all commands, params, dev guide

### 4. Observation Layer
- [x] Canonical state model: game, company, town, industry, station, vehicle (`src/nttd/schemas/`)
- [x] Snapshot with epoch tagging (`src/nttd/schemas/snapshot.py`)
- [x] WorldState in-memory store, bridge writes, API reads (`src/nttd/state/world.py`)
- [x] `WorldState.apply_gs_*()` methods — populate all entities from GS query results
- [x] Orchestrator refreshes WorldState from GS before each heartbeat step
- [x] Orchestrator refreshes WorldState from GS every 10s in async_realtime mode
- [ ] Delta detection via snapshot diffing
- [ ] Compressed/summary views for LLMs

### 5. Action Layer
- [x] JSON action envelope schema (`src/nttd/schemas/action_envelope.py`)
- [x] Action result tracking with full status lifecycle (`src/nttd/actions/tracker.py`)
- [x] `/actions/submit` executes GS command immediately, returns success/failed with changed_entities
- [x] `/actions/validate` validates action_type against known command set
- [x] `/actions/gs/execute` — raw GS command passthrough (bypasses tracking)
- [x] `_KNOWN_ACTIONS` registry — unknown action_types rejected before execution
- [x] `company_id` from envelope auto-merged into GS params
- [ ] Action validation against current game state (pre-execution checks)
- [ ] `/actions/batch_submit`, `/actions/{id}/cancel`

### 6. Agent Connection API
- [x] `/agents/connect`, `/agents/{id}/disconnect`, `/{id}/status`, `/list`
- [x] Subscription registration by entity type, event type, cadence
- [x] WebSocket push (`/ws/{agent_id}`) with snapshot delivery
- [x] REST polling fallback (all `/state/*` endpoints)
- [x] Ping/pong keepalive; reject unknown agents (code 4004)

### 7. FastAPI Service
- [x] Control API: pause, unpause, speed, mode, stop, heartbeat/interval, rcon
- [x] Observation API: `/state/full`, company, towns, industries, stations, vehicles, `/state/gs/query`
- [x] Action API: submit, validate, status, recent, `/actions/gs/execute`
- [x] Health endpoint; async lifespan; offline mode fallback
- [ ] `/session/save`, `/session/load` via rcon
- [ ] `/actions/batch_submit`, `/actions/{id}/cancel`

### 8. Runtime Modes
- [x] Heartbeat mode — pause → GS refresh → snapshot → action window → execute actions → unpause → wait
- [x] Async real-time mode — game runs, GS refresh every 10s, snapshots pushed every 2s
- [x] Game speed control; heartbeat interval configurable
- [x] Heartbeat action collection window (agents submit during window before unpause)
- [ ] Assisted mode — human triggers AI via command, pause/plan/execute/unpause
- [ ] Completed heartbeat action execution integration (wiring from API → orchestrator queue)

### 9. Documentation & Tooling
- [x] `README.md` — full setup, API reference, GS command reference, architecture
- [x] `ottd_config/README.md` — complete GS command docs, param tables, dev guide
- [x] `examples/agent_client.py` — REST + WebSocket mode example
- [x] `scripts/test_bridge.py` — live bridge diagnostic
- [x] `docs/nttd_architecture_report.md` — full architecture design doc

### 10. Tests
- [x] API tests: health, session, pause/unpause, speed, mode, agents, snapshot, submit action (10 passing)
- [x] WebSocket tests: reject unknown agent, ping/pong
- [x] Live end-to-end: OpenTTD + nttd + GS pipeline verified

### 11. Project Setup
- [x] GitHub repo (private, `deepsaia/nttd`)
- [x] `.gitignore` — Python, OpenTTD runtime files, secrets, save games

---

## Phase 1 — Remaining Work (Priority Order)

1. **Reconnect logic** — auto-reconnect bridge on connection loss, resync state.
2. **Save/load endpoints** — `/session/save`, `/session/load` via rcon.
3. **Heartbeat action API wiring** — expose `orchestrator.submit_heartbeat_action()` via an API endpoint so agents can push actions during the window.
4. **Assisted mode** — human triggers AI via chat/command, game pauses, AI plans, human approves, execute, unpause.
5. **Structured logging** — log observations, actions, results to SQLite or JSON.
6. **Gym wrapper** — single-agent heartbeat env with `reset()`, `step(action)`, observation/action spaces, reward signal.
7. **Basic dashboard** — TensorboardX or Streamlit showing game state, KPIs, action timeline.

---

## Phase 2 — Production Research Platform

- [ ] Per-company isolation (GSCompanyMode orchestration across agents)
- [ ] Advanced subscriptions (region-based, backpressure, coalescing)
- [ ] PettingZoo multi-agent wrapper
- [ ] Event-driven delta detection (GS polling + snapshot diffing)
- [ ] A* pathfinding in GameScript (rail corridor builder)
- [ ] High-level compound actions (connect_towns_rail, etc.)
- [ ] Idempotency keys + precondition hashes
- [ ] Circuit breakers per company
- [ ] Redis/NATS event bus + Postgres for durable logs
- [ ] Save/load + benchmark packs (config presets, map seeds, reward configs)
- [ ] Observability traces (OpenTelemetry-style)
- [ ] Action masking for RL
- [ ] Checkpoint/recovery (savegame + nttd metadata + action queue state)

---

## Phase 3 — Scale & RL

- [ ] Tactical rule-based policy workers for async real-time mode
- [ ] LLM strategic planner with periodic replans
- [ ] Latency class routing (strategic/tactical/execution agents)
- [ ] Distributed experiments (multiple OpenTTD instances)
- [ ] Reward shaping + offline dataset export
- [ ] Training data pipelines (Parquet, object storage)
- [ ] Benchmark families: growth, efficiency, robustness, competition
