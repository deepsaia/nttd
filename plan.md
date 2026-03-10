# nttd Implementation Plan

## Phase 1 — MVP

### 1. OpenTTD Server Setup
- [x] Dedicated server config with admin port enabled (`ottd_config/openttd.cfg`)
- [x] Start script (`scripts/start_openttd_server.sh`)
- [x] `allow_insecure_admin_login = true` for pyopenttdadmin compatibility
- [x] Document server setup/run steps (README.md)
- [ ] GameScript scaffold (Squirrel) — loads into server, basic message handling
- [ ] GS message protocol: correlation IDs, JSON serialization, chunking

### 2. Game Bridge
- [x] Async Python admin port client — connect, auth, subscribe, rcon (`src/nttd/bridge/admin_client.py`)
- [x] Event wiring: admin port packets → WorldState updates (`src/nttd/bridge/bridge.py`)
- [x] Welcome packet → map dimensions, landscape, start date
- [x] Company info + economy subscriptions
- [x] Date tracking from server updates
- [ ] GS message send/receive with correlation-based request/response
- [ ] Reconnect + resync logic (currently: connect once, no auto-reconnect)
- [ ] Detect save/load/newgame and notify agents of world reset

### 3. Observation Layer
- [x] Canonical state model: game, company, town, industry, station, vehicle (`src/nttd/schemas/`)
- [x] Snapshot with epoch tagging: game_date, tick, snapshot_id (`src/nttd/schemas/snapshot.py`)
- [x] WorldState in-memory store, bridge writes, API reads (`src/nttd/state/world.py`)
- [ ] GS query functions for state domains not on admin port (vehicles, stations, industries, towns)
- [ ] Delta detection via snapshot diffing
- [ ] Compressed/summary views for LLMs

### 4. Action Layer
- [x] JSON action envelope schema: action_id, company_id, mode, action_type, parameters (`src/nttd/schemas/action_envelope.py`)
- [x] Action result tracking with status lifecycle (`src/nttd/schemas/action_result.py`, `src/nttd/actions/tracker.py`)
- [ ] Action validation against current game state (currently: stub)
- [ ] Action → GS command translation pipeline
- [ ] Action execution via GameScript (build, buy, order, start/stop)

### 5. Agent Connection API
- [x] `/agents/connect` — register agent, declare company scope
- [x] `/agents/{id}/disconnect`, `/agents/{id}/status`, `/agents/list`
- [x] Subscription registration by entity type, event type, cadence
- [x] WebSocket push (`/ws/{agent_id}`) with snapshot delivery based on subscription cadence
- [x] REST polling fallback (all `/state/*` endpoints)
- [x] Ping/pong keepalive on WebSocket
- [x] Reject WebSocket for unknown agents (code 4004)

### 6. FastAPI Service
- [x] Control API: `/session/status`, `pause`, `unpause`, `speed`, `mode`, `stop`, `heartbeat/interval`, `rcon`
- [x] Observation API: `/state/full`, `/state/company/{id}`, `/state/towns`, `industries`, `stations`, `vehicles`
- [x] Action API: `/actions/submit`, `validate`, `{id}/status`, `recent`
- [x] Health endpoint with OpenTTD connection status
- [x] Async lifespan: connect bridge on startup, disconnect on shutdown
- [x] Offline mode fallback when OpenTTD not available
- [ ] Published JSON schemas (OpenAPI auto-generated, but not explicitly documented/versioned)
- [ ] `/session/save`, `/session/load` endpoints
- [ ] `/actions/batch_submit`, `/actions/{id}/cancel` endpoints

### 7. Runtime Modes
- [x] Heartbeat mode — pause → snapshot → notify observers → unpause → wait N game-days → repeat
- [x] Async real-time mode — game runs continuously, periodic snapshots pushed every 2s
- [x] Game speed control via `/session/speed`
- [x] Orchestrator with observer pattern for snapshot broadcast to WebSocket clients
- [x] Heartbeat interval configurable via `/session/heartbeat/interval`
- [ ] Assisted mode — human triggers AI via command, pause/plan/execute/unpause (skeleton only)
- [ ] Heartbeat mode: collect actions from agents before unpausing (currently: notify only)

### 8. Logging & Observability
- [ ] Structured logging (SQLite or JSON files) — currently: basic Python logging only
- [ ] Log: observations, actions, validation results, execution results, errors
- [ ] Basic dashboard (Streamlit or Dash) — game state, KPIs, action timeline

### 9. Gym Wrapper
- [ ] Single-agent Gym env (heartbeat mode)
- [ ] `reset()`, `step(action)`, observation/action spaces, reward signal

### 10. Example Agent Client
- [x] Plain Python script: connect → subscribe → observe → act (`examples/agent_client.py`)
- [x] REST mode and WebSocket mode (`--ws` flag)
- [x] Demonstrates the full API flow
- [x] Serves as documentation for agent builders

### 11. Tests
- [x] API tests: health, session status, pause/unpause, speed, mode, agent lifecycle, full state, submit action (10 tests)
- [x] WebSocket tests: reject unknown agent, ping/pong
- [x] Live end-to-end test verified: OpenTTD server + nttd API + live game state flowing

---

## Phase 1 — Remaining Work (Priority Order)

1. **GameScript scaffold** — Squirrel script that loads into OpenTTD, handles message protocol with correlation IDs. This unlocks vehicle/station/industry/town queries and action execution.
2. **Action execution pipeline** — translate action envelopes → GS commands, execute, return results.
3. **State enrichment via GS** — query vehicles, stations, industries, towns through GameScript to populate WorldState beyond what the admin port provides.
4. **Assisted mode skeleton** — human triggers AI via chat/command, game pauses, AI plans, human approves, execute, unpause.
5. **Heartbeat action collection** — wait for agent actions after snapshot delivery before unpausing.
6. **Reconnect logic** — auto-reconnect bridge on connection loss, resync state.
7. **Structured logging** — log observations, actions, results to SQLite or JSON.
8. **Gym wrapper** — single-agent heartbeat env with reset/step/reward.
9. **Basic dashboard** — Streamlit prototype showing game state, KPIs, action timeline.
10. **Save/load endpoints** — `/session/save`, `/session/load` via rcon.

---

## Phase 2 — Production Research Platform

- [ ] Per-company isolation (GSCompanyMode orchestration)
- [ ] Advanced subscriptions (region-based, backpressure, coalescing)
- [ ] PettingZoo multi-agent wrapper
- [ ] Event-driven delta detection (GS polling + snapshot diffing)
- [ ] Compound action decomposition (pathfinding, rail corridor builder)
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
