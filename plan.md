# nttd Implementation Plan

> **Focus**: Async real-time multiplayer where humans and/or LLM agents play, managed via Admin Console.
> **Reference docs**: `docs/openttd_study_part{1-4}_*.md`, `docs/nttd_architecture_report.md`

---

## Architecture Decisions (Locked)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **Session = Server** | Each session is its own OpenTTD dedicated server process with unique ports | Full isolation between sessions. Humans/agents connect to a specific session's game port. Multiple simultaneous games. |
| Database | **SQLite** (fully normalized, ~25 tables) → PostgreSQL later | Normalized for fast time-series queries, proper FK relationships, space-efficient. |
| DB middle-layer | **Yes** — all reads from DB, not live state | Decouples ingestion from visualization. Dashboard reads DB. WebSocket = notification only. |
| Frontend | **React + Vite + Yarn (v4) + TypeScript + MUI + Tailwind** | Modern stack, good charting ecosystem. |
| Transport | **TCP only** (admin port + HTTP + WebSocket) | UDP unnecessary at our data rates. Admin port is TCP. |
| Snapshot storage | **Normalized tables** + compressed JSON blob per snapshot for replay | Metrics/actions/events in proper columns. Full snapshot as parquet for replay only. |
| Concurrency model | **Per-company asyncio.Lock** for action serialization | 15 companies × 10 agents = 150 connections. Cross-company parallel, intra-company serial. |
| Primary runtime | **Async real-time** | Game runs continuously, agents observe and act in real-time. |

### Multi-Server Session Architecture

```
nttd (FastAPI)
├── SessionManager (singleton, initialized in app.py lifespan)
│   ├── Session "ses_abc" (active)
│   │   ├── OpenTTD process (PID 12345)
│   │   ├── AdminClient → 127.0.0.1:4001
│   │   ├── WorldState, Bridge, Orchestrator, ActionTracker, AgentRegistry
│   │   ├── game_port = 4000  ← humans/agents connect here via OpenTTD client
│   │   └── config_dir = runs/ses_abc/
│   ├── Session "ses_def" (active)
│   │   ├── OpenTTD process (PID 12346)
│   │   ├── AdminClient → 127.0.0.1:4003
│   │   ├── game_port = 4002
│   │   └── config_dir = runs/ses_def/
│   └── Session "ses_old" (archived, no process)
└── DB (session records, settings, participants, metrics)
```

**Session lifecycle**: `pending` → `active` (server running) → `archived` (server stopped)

**Port allocation**: Even ports for game (4000, 4002, 4004...), odd for admin (4001, 4003, 4005...). Checks both registry and OS availability.

**Orphan recovery**: On nttd restart, checks DB for active sessions with PIDs, reconnects if alive, marks crashed if dead.

**Per-session config**: Each session gets its own config directory under `runs/`, with patched ports and symlinked shared resources (GS, AI, baseset, newgrf).

---

## Phase 1 — Completed (MVP)

> All items below are done from previous work. Kept for reference.

### 1. OpenTTD Server Setup
- [x] Dedicated server config with admin port (`ottd_config/openttd.cfg`)
- [x] Start script (`scripts/start_openttd_server.sh`)
- [x] `allow_insecure_admin_login = true` for pyopenttdadmin
- [x] Config patching: start script patches `[game_scripts]` and `secrets.cfg`
- [x] GS symlink for discovery

### 2. Game Bridge
- [x] Async admin port client — connect, auth, subscribe, rcon (`src/nttd/bridge/admin_client.py`)
- [x] Event wiring: admin packets → WorldState updates (`src/nttd/bridge/bridge.py`)
- [x] Welcome packet → map dimensions, landscape, start date
- [x] Company info + economy subscriptions
- [x] GS message send/receive with correlation IDs
- [x] Null-terminator stripping, chunked response reassembly

### 3. GameScript — 93 Commands
- [x] Protocol: correlation IDs, JSON serialization, auto-chunking
- [x] Error handling via `GSError.GetLastErrorString()`
- [x] All queries, construction, vehicles, orders, groups, signs, subsidies, towns
- [x] Full reference: `ottd_config/README.md`

### 4. Observation Layer
- [x] State model: game, company, town, industry, station, vehicle (`src/nttd/schemas/`)
- [x] WorldState in-memory store (`src/nttd/state/world.py`)
- [x] Snapshot with epoch tagging, route derivation
- [x] Orchestrator refreshes from GS (heartbeat + async_realtime)

### 5. Action Layer
- [x] Action envelope + result tracking (`src/nttd/schemas/`, `src/nttd/actions/tracker.py`)
- [x] `/actions/submit`, `/actions/validate`, `/actions/gs/execute`
- [x] `_KNOWN_ACTIONS` registry, company_id auto-merge

### 6. Agent Connection API
- [x] Agent registration, subscriptions, WebSocket push, REST polling
- [x] Company scope enforcement (403 for out-of-scope)

### 7. FastAPI Service
- [x] Control, observation, action, WebSocket, benchmark routes
- [x] Health endpoint, async lifespan, offline mode fallback

### 8. Runtime Modes
- [x] Heartbeat mode (pause → refresh → snapshot → action window → execute → unpause)
- [x] Async real-time mode (continuous, refresh every 10s, push every 2s)
- [x] Game speed control, heartbeat interval configurable

### 9. Documentation, Tests, CLI
- [x] README, GS docs, architecture report, examples
- [x] API tests (10 passing), WebSocket tests, live E2E verified
- [x] CLI: `nttd run/server/sim/status/results/logs/tensorboard/scenario/agent`

---

## Phase 2 — Backend Engine (Completed)

> Build the data layer, missing GS commands, admin APIs, pathfinding, and multi-server architecture.

### 2.1 Database Layer
**Ref**: `docs/openttd_study_part4...md` §13

- [x] **2.1.1** `src/nttd/db/` package with `engine.py` (SQLAlchemy Core + aiosqlite, WAL mode)
- [x] **2.1.2** Schema: `src/nttd/db/tables.py` — 25 normalized tables (sessions, session_settings, participants, snapshots, companies, towns, industries, stations, vehicles, actions, events, messages, metrics, finances, leaderboard, etc.)
- [x] **2.1.3** Migration system: `src/nttd/db/migrations.py` — auto-applies on startup, ALTER TABLE for new columns (game_port, admin_port, pid)
- [x] **2.1.4** Repository layer: `src/nttd/db/repositories/` — session_repo, metrics_repo, action_repo, event_repo, entity_repo
- [x] **2.1.5** Session recorder: background flush (1s interval, 5000 max buffer) + Parquet writer
- [x] **2.1.6** Indexes on `(session_id, game_date)`, `(session_id, company_id, game_date)`, `(session_id, participant_id)`

### 2.2 Missing GS Commands
**Ref**: `docs/openttd_study_part3...md` §4-5

- [x] All high-priority: `get_game_settings`, `set_game_setting`, `get_expense_breakdown`, `get_infrastructure_costs`, `get_cargo_flows`, `estimate_cost`, `get_clients`, `change_bank_balance`, `set_max_loan`
- [x] All medium-priority: conditional orders, terraform, one-way roads, convert road type, stop location, engine details
- [x] Query enrichment: stations (cargo ratings), vehicles (running costs/capacity), companies (quarterly), industries (accepted cargo)
- [x] Event monitoring: 18 event types forwarded via GS → admin port → nttd

### 2.3 Admin API Endpoints (All Session-Scoped)
**Ref**: `docs/openttd_study_part4...md` §11, §12, §16, §18.4

All routes are session-scoped — each takes `{session_id}` as a path parameter and resolves the per-session runtime.

Session lifecycle:
- [x] `POST /admin/sessions/new` — create session (status=pending, stores all settings including defaults)
- [x] `GET /admin/sessions` — list sessions (enriched with `running` boolean from SessionManager)
- [x] `GET /admin/sessions/{id}` — session details with settings, participants, ports, running state
- [x] `POST /admin/sessions/{id}/settings` — update settings (applies live if session is running)
- [x] `POST /admin/sessions/{id}/start` — spawns OpenTTD server, allocates ports, connects admin client, applies settings, returns game_port/admin_port/pid
- [x] `POST /admin/sessions/{id}/stop` — kills OpenTTD process, auto-archives session
- [x] `DELETE /admin/sessions/{id}` — stops if running, deletes from DB

Session-scoped control (`/sessions/{id}/...`):
- [x] `GET /sessions/{id}/status` — game state (date, paused, mode, speed, map dims)
- [x] `POST /sessions/{id}/pause|unpause|speed|mode|rcon|save|load`
- [x] `POST /sessions/{id}/heartbeat/action|interval|action_window`
- [x] `POST /sessions/{id}/assist|assist/approve|assist/cancel`
- [x] `POST /sessions/{id}/scenario`

Session-scoped players:
- [x] `GET /admin/sessions/{id}/clients` — connected game clients
- [x] `POST /admin/sessions/{id}/clients/{cid}/move|kick`
- [x] `GET /admin/sessions/{id}/spectators`

Session-scoped deity:
- [x] `POST /admin/sessions/{id}/deity/change_balance|set_max_loan|set_setting|found_town|expand_town|set_town_growth|create_subsidy|change_town_rating`

Session-scoped observation (`/sessions/{id}/state/...`):
- [x] `GET /sessions/{id}/state/full|compact|company/{cid}|towns|industries|stations|vehicles|metrics`
- [x] `POST /sessions/{id}/state/gs/query`

Session-scoped actions (`/sessions/{id}/actions/...`):
- [x] `POST /sessions/{id}/actions/submit|validate|gs/execute`
- [x] `GET /sessions/{id}/actions/{aid}/status|recent`

Session-scoped agents (`/sessions/{id}/agents/...`):
- [x] `POST /sessions/{id}/agents/connect|{aid}/disconnect`
- [x] `GET /sessions/{id}/agents/list|{aid}/status|{aid}/subscriptions`

Session-scoped WebSocket:
- [x] `WS /ws/{session_id}/admin` — admin console event notifications
- [x] `WS /ws/{session_id}/{agent_id}` — agent heartbeat push

Session-scoped benchmark (`/sessions/{id}/benchmark/...`):
- [x] `POST /sessions/{id}/benchmark/setup|reset|export`
- [x] `GET /sessions/{id}/benchmark/results`

Session-scoped pathfinding:
- [x] `POST /admin/sessions/{id}/pathfind`

Metrics/messages/leaderboard/replay (session_id as query/path param — DB-backed, no runtime needed):
- [x] `GET /metrics/timeseries|latest|comparison|finances|available`
- [x] `POST /messages/send`, `GET /messages/history|inbox/{agent_id}`
- [x] `GET /leaderboard/session/{id}|global`, `POST /leaderboard/compute/{id}`
- [x] `GET /replay/sessions/{id}/snapshots|actions|events`
- [x] `GET /data/towns|industries|stations|vehicles|subsidies`

### 2.4 Multi-Server Session Architecture
- [x] **2.4.1** DB schema: `game_port`, `admin_port`, `pid` columns on sessions table
- [x] **2.4.2** Config builder: `src/nttd/runtime/config_builder.py` — per-session config dir with patched ports, symlinked shared resources
- [x] **2.4.3** SessionRuntime: `src/nttd/runtime/session_runtime.py` — bundles AdminClient, WorldState, Bridge, Orchestrator, ActionTracker, AgentRegistry, EventLogger, process handle
- [x] **2.4.4** SessionManager: `src/nttd/runtime/session_manager.py` — port allocation, start/stop lifecycle, orphan recovery, shutdown_all
- [x] **2.4.5** Dependencies: `src/nttd/api/dependencies.py` — `session_manager` singleton + `get_runtime(session_id)` helper (replaced all old global singletons)
- [x] **2.4.6** App lifespan: creates SessionManager with env vars (NTTD_OPENTTD_BINARY, NTTD_BASE_CONFIG, NTTD_SESSIONS_DIR, NTTD_PORT_RANGE_START, NTTD_ADMIN_PASSWORD), runs orphan recovery on startup, shutdown_all on exit
- [x] **2.4.7** All route files updated for session scope (admin, control, observation, action, agent, ws, benchmark, pathfinding)

### 2.5 Pathfinding Service
**Ref**: `docs/openttd_study_part4...md` §14

- [x] Tile cache, A* core, road/rail/water pathfinders
- [x] GS batch tile scan, API endpoint, service layer

### 2.6 Connection & Concurrency Hardening
- [x] Auto-reconnect with exponential backoff
- [x] Per-company asyncio.Lock
- [x] Staggered refresh, health ping
- [ ] **2.6.1** Save/load detection → clear WorldState, notify agents [deferred]
- [ ] **2.6.2** GS query pipeline: send next query while waiting for response [deferred — optimization]

---

## Phase 3 — Admin Console Frontend (Current)

> React + Vite + Yarn + TypeScript + Tailwind + MUI
> **Goal**: Full spectate milestone — create session, start game, join from OpenTTD client, watch from browser.

### 3.1 Project Setup
- [x] **3.1.1** Initialize: `admin-console/` with Vite + React + TypeScript + Tailwind + MUI
- [x] **3.1.2** Yarn v4 (Berry) configuration
- [x] **3.1.3** API client module: typed HTTP client wrapping all session-scoped endpoints (`src/api/client.ts`)
- [x] **3.1.4** WebSocket hook: `useWebSocket()` — connects to `/ws/{sessionId}/admin`, session-aware, auto-reconnect
- [x] **3.1.5** Zustand store: `gameStore.ts` — `activeSessionId`, game state, companies, events
- [x] **3.1.6** React Router: 4 pages (Session, Players, Metrics, Leaderboard) + Sidebar navigation
- [x] **3.1.7** Vite proxy config for API (`/api` → `:8000`) + WebSocket (`/ws` → `:8000`)
- [x] **3.1.8** Session-aware poller: `usePoller()` — polls `/health` for connectivity, session-scoped endpoints only when `activeSessionId` is set

### 3.2 Page 1 — Session Management
- [x] **3.2.1** Session creation form: comprehensive settings with 5 groups (World Generation, Towns & Industries, Economy, Vehicles, AI Competitors), ~25 settings
  - All settings use OpenTTD integer values (landscape=0-3, town_name=0-20, etc.)
  - Defaults match OpenTTD game defaults (flat terrain, 64x64 map, medium rivers, etc.)
  - Options ordered with default first in dropdowns
  - Conditional fields (custom height, custom town count, custom industry count, custom sea level)
  - All defaults + user selections stored to DB on create (complete settings snapshot)
- [x] **3.2.2** Session list: shows status badges + green dot for running sessions
- [x] **3.2.3** Session detail view: full settings display (all fields, not just non-defaults), edit mode for pending sessions
- [x] **3.2.4** Session controls: Start Game (spawns OpenTTD server), Stop (kills process + auto-archives)
- [x] **3.2.5** Delete confirmation dialog for archived sessions (no separate archive button)
- [x] **3.2.6** How to Join card: dynamic port from session (`127.0.0.1:{game_port}`), step-by-step instructions
- [x] **3.2.7** Save/Load game for active sessions
- [x] **3.2.8** Loading state during session start (~3-5s while OpenTTD boots)
- [ ] **3.2.9** Session presets: save/load settings configurations [deferred]

### 3.3 Page 2 — Players & Agents
- [x] **3.3.1** Connected agents panel: list with company scope, subscriptions, online status
- [x] **3.3.2** Connected humans panel: list with company, name, client ID
- [x] **3.3.3** Spectators panel (company_id=255 clients)
- [x] **3.3.4** Move/kick controls (session-aware, with confirmation prompts)
- [x] **3.3.5** Live event feed: scrolling log from WebSocket events
- [x] **3.3.6** Message center: view history + send chat messages
- [ ] **3.3.7** Agent launch dialog: select type, company, config [deferred to Phase 4]

### 3.4 Page 3 — Metrics & Timeline
- [x] **3.4.1** Time-series line charts (Recharts): balance, income, value over time per company
- [x] **3.4.2** Performance rating bar chart + cargo delivered bar chart
- [x] **3.4.3** Filters: company selector (all or individual)
- [ ] **3.4.4** Stacked bar charts: revenue by vehicle type [deferred]
- [ ] **3.4.5** Pie charts: expense breakdown per company [deferred]
- [ ] **3.4.6** Timeline scrubber + event markers [deferred]

### 3.5 Page 4 — Leaderboard
- [x] **3.5.1** Per-session leaderboard table
- [x] **3.5.2** Cross-session leaderboard
- [x] **3.5.3** Sortable columns
- [ ] **3.5.4** Participant detail view [deferred]

### 3.6 Top Bar (Global)
- [x] **3.6.1** Game status: date, speed, paused/playing, company count (session-aware, only shows for active session)
- [x] **3.6.2** Connection status: nttd health check (not per-session OpenTTD connection)
- [x] **3.6.3** Quick controls: pause/play toggle, speed slider, dark/light mode toggle (all session-scoped)

### 3.7 Remaining Frontend Work
- [ ] **3.7.1** OpenTTD server log forwarding (pipe subprocess stdout to nttd logger)
- [ ] **3.7.2** AI selection per competitor slot (list available AIs, assign to each slot)
- [ ] **3.7.3** Session reconnect on page reload (persist activeSessionId to localStorage)
- [ ] **3.7.4** Real-time entity data on dashboard (towns, industries, stations, vehicles from DB)

---

## Phase 4 — Agent Integration

> Enable LLM agents to play OpenTTD in async real-time multiplayer mode.
> Game runs continuously — agents observe, decide, act in a loop. No heartbeat/pause-play.
> MCP = observation + validation only (thin layer). Execution via interpreter.
> Gameloop service manages agent connections and drives the cycle.

### 4.1 Fix: AI Opponent Spawning ✅
- [x] **4.1.1** `session_runtime.py`: After `newgame`, wait ~3s, send `start_ai` N times
- [x] **4.1.2** `admin_routes.py`: Wire `StartSessionRequest.ai_opponents` through
- [x] **4.1.3** `session_manager.py`: Add `ai_opponents` param

### 4.2 End Conditions in Async Real-Time Mode ✅
- [x] **4.2.1** `orchestrator.py`: End condition check in `run_async_realtime()` loop
- [x] **4.2.2** `orchestrator.py`: `configure_end_conditions(config)` method
- [x] **4.2.3** `admin_routes.py`: `POST /admin/sessions/{id}/end-conditions` endpoint

### 4.3 Agent Client & Loop ✅
- [x] **4.3.1-7** Session-scoped client, `run_realtime()`, `submit-batch` endpoint, scripted agent updated

### 4.4 MCP Server Layer (Observation + Validation Only) ✅
**Design change**: MCP tools are for observation and validation only — no action execution via MCP. Agents output structured action lists; the interpreter handles execution.

```
src/nttd/mcp/
├── __init__.py, __main__.py
├── server.py           # FastMCP server — registers observation + validation tools
├── client.py           # Async HTTP client wrapping nttd REST API
└── tools/
    ├── __init__.py
    ├── observation.py   # ~28 tools: get_state_compact, get_towns, get_engines, etc.
    ├── pathfinding.py   # 1 tool: pathfind
    └── validation.py    # 2 tools: validate_actions, list_available_actions
```

- [x] **4.4.1** MCP client + server + observation tools + pathfinding tool
- [x] **4.4.2** `pyproject.toml`: `mcp = ["mcp[cli]>=1.9", "httpx>=0.28.0"]`

### 4.5 Action Interpreter ✅
**New component**: Parses agent output (structured action list) → validates against KNOWN_ACTIONS → executes via GS.

- [x] **4.5.1** `src/nttd/constants.py`: Single source of truth for `KNOWN_ACTIONS` + `ACTION_CATEGORIES`
- [x] **4.5.2** `src/nttd/interpreter/`: parser.py, validator.py, executor.py, interpreter.py, action_schema.py
- [x] **4.5.3** REST endpoints: `POST /actions/interpret`, `POST /actions/interpret/validate`, `GET /actions/available`
- [x] **4.5.4** MCP validation tools: `validate_actions`, `list_available_actions`

### 4.6 Example Agents ✅
**Real framework examples** with detailed agent instructions, tool bindings, and the full observe→decide→interpret→execute loop.

- [x] **4.6.1** `examples/agent_instructions.py`: Shared system prompts + action format spec
- [x] **4.6.2** `examples/langchain_nttd_agent.py`: LangChain with tool-calling or single-shot
- [x] **4.6.3** `examples/openai_nttd_agent.py`: OpenAI SDK with native function calling
- [x] **4.6.4** `examples/langgraph_nttd_agent.py`: Planner + executor graph
- [x] **4.6.5** `examples/simple_bus_agent.py`: Scripted no-LLM baseline
- [x] **4.6.6** `examples/agent_client.py`: REST API lifecycle demo (session-scoped)
- [x] **4.6.7** `examples/README.md`: "How to Build Your Agent" guide

### 4.7 CLI-First Architecture ✅
- [x] **4.7.1** CLI docs: `docs/cli_guide.md` — complete guide with REST API workflow, testing section, model support table
- [x] **4.7.2** REST API workflow documented with curl examples for full session + agent lifecycle
- [ ] **4.7.3** `src/nttd/cli.py`: CLI subcommands wrapping REST API [deferred — REST API is primary interface]
- [ ] **4.7.4** HOCON config parser [deferred — manual REST calls work]

### 4.8 Gameloop Service ✅
**The core new system**: Centralized loop inside nttd that manages agent connections, drives the observe→decide→interpret→execute cycle, and tracks everything per `connection_id`.

> **Key principle**: Agents = humans from the game's perspective. The gameloop calls the LLM on behalf of agents using pluggable framework adapters.

> **connection_id** = `"{session_id}:{company_id}:{agent_id}"` — unique tracking key.

> **OpenTTD limits**: 15 companies max, 255 clients max, spectator = company_id 255.

```
src/nttd/gameloop/
├── __init__.py
├── manager.py              # GameloopManager — one per session, manages connections
├── connection.py           # AgentConnection — single agent's cycle loop + tracking
├── adapters/
│   ├── __init__.py
│   ├── base.py             # BaseAdapter — framework interface
│   ├── openai_adapter.py   # OpenAI SDK adapter
│   ├── langchain_adapter.py # LangChain adapter
│   └── passthrough_adapter.py # No LLM — for scripted/rule-based agents
├── schemas.py              # AgentConfig, ConnectionStatus, CycleRecord
└── tracker.py              # ConnectionTracker — per-connection telemetry
```

REST endpoints (back the CLI + future admin UI):
```
POST   /sessions/{sid}/gameloop/agents/register     → register agent, return connection_id
POST   /sessions/{sid}/gameloop/agents/{aid}/start   → start cycle loop
POST   /sessions/{sid}/gameloop/agents/{aid}/stop    → stop cycle loop
GET    /sessions/{sid}/gameloop/agents               → list all connections + status
GET    /sessions/{sid}/gameloop/agents/{aid}/status   → connection detail + metrics
GET    /sessions/{sid}/gameloop/agents/{aid}/cycles   → recent cycle records
GET    /sessions/{sid}/gameloop/status                → overall gameloop status
```

- [x] **4.8.1** `gameloop/schemas.py`: AgentConfig, ConnectionStatus, CycleRecord models
- [x] **4.8.2** `gameloop/adapters/base.py`: BaseAdapter abstract class
- [x] **4.8.3** `gameloop/adapters/openai_adapter.py`: OpenAI SDK adapter with tool calling
- [x] **4.8.4** `gameloop/adapters/langchain_adapter.py`: LangChain adapter (multi-provider: gpt, claude)
- [x] **4.8.5** `gameloop/adapters/passthrough_adapter.py`: Scripted agent adapter
- [x] **4.8.6** `gameloop/tracker.py`: ConnectionTracker (per-cycle telemetry, aggregate metrics)
- [x] **4.8.7** `gameloop/connection.py`: AgentConnection (cycle loop: observe → decide → interpret → execute)
- [x] **4.8.8** `gameloop/manager.py`: GameloopManager (register, start, stop, stop_all)
- [x] **4.8.9** `src/nttd/api/gameloop_routes.py`: REST API for gameloop management
- [x] **4.8.10** `session_runtime.py`: Attach `GameloopManager` to runtime bundle
- [x] **4.8.11** `orchestrator.py`: Wire `on_end` → `gameloop_manager.stop_all()`
- [x] **4.8.12** Multi-turn tool calling: ObservationToolkit (26 GS query tools as OpenAI-format schemas)
- [x] **4.8.13** Conversation memory: deque of last N cycle exchanges for agent learning
- [x] **4.8.14** Default bus agent prompt fallback when instructions empty
- [x] **4.8.15** Field normalization in parser (action→action_type, params→parameters, type→action_type)
- [x] **4.8.16** GS _VehicleTypeEnum accepts both strings and integers

### 4.9 DB Schema for Gameloop Tracking
- [x] **4.9.1** `db/tables.py`: Add `agent_connections` table (connection lifecycle + aggregate metrics)
- [x] **4.9.2** `db/tables.py`: Add `agent_cycles` table (per-cycle timing, action counts)
- [x] **4.9.3** `db/migrations.py`: Auto-create new tables
- [ ] **4.9.4** `db/recorder.py` + `gameloop/connection.py`: Wire SessionRecorder to flush cycle records to DB (tables exist but never written to)

### 4.10 End Conditions Wiring (part of session config)
End conditions are part of the HOCON scenario config — they're stored with the session and applied on session start, alongside map settings, companies, and runtime mode. No separate CLI command needed.

- [ ] **4.10.1** `session_manager.py`: Apply end conditions from HOCON on `session start`
- [ ] **4.10.2** `orchestrator.py`: `on_end` triggers `stop_all()` + leaderboard computation + session archive

### 4.11 Benchmark Runner (CLI)
**All-in-one command**: Create session, apply config, start OpenTTD, register + start agents, wait for end condition, export results.

```bash
nttd benchmark --config config/scenario.conf --speed 3 --output results/
```

- [ ] **4.11.1** `cli.py`: `benchmark` command — full orchestration from HOCON
- [ ] **4.11.2** Results export: JSON/CSV with per-agent and per-company metrics
- [ ] **4.11.3** `agents.json` format as alternative to agents-in-HOCON (for multi-config reuse)

### 4.12 Serialization & Parallelization (Already Handled)
- Per-company `asyncio.Lock` in `company_lock.py`
- 1 agent per company for now → no contention
- Cross-company actions run in parallel
- GS is single-threaded but microseconds per command

### 4.13 Deferred
- [ ] Multi-agent per company (coordination, role assignment)
- [ ] Agent authentication (API keys)
- [ ] Agent-to-agent messaging
- [ ] Compound action builder
- [ ] LLM chat message tracking (defer to Langsmith/Langfuse)
- [ ] Admin console UI for session management, end conditions, agent registration
- [ ] Stress testing (150 connections)

---

## Phase 5 — Multi-Transport Agents, DB Wiring & Documentation

> Expand from bus-only to all 4 transport types, wire the DB recording layer, and produce documentation.
> **Verified working**: Bus agent end-to-end with gpt-5.2 (LangChain adapter, multi-turn tool calling, 13 cycles, 9 successful actions).

### 5.1 Agent Prompts (Rail, Air, Water)

- [ ] **5.1.1** `examples/agent_instructions.py`: Add `SYSTEM_PROMPT_RAIL_AGENT` + `get_rail_agent_prompt(company_id)` — rail strategy (industries via rail, signals, track building)
- [ ] **5.1.2** `examples/agent_instructions.py`: Add `SYSTEM_PROMPT_AIR_AGENT` + `get_air_agent_prompt(company_id)` — airport strategy (largest towns, passenger aircraft)
- [ ] **5.1.3** `examples/agent_instructions.py`: Add `SYSTEM_PROMPT_WATER_AGENT` + `get_water_agent_prompt(company_id)` — dock/ship strategy (coastal towns, water depots)
- [ ] **5.1.4** `examples/agent_instructions.py`: Update `MULTI_TURN_GUIDE` with `get_rail_types`, `get_airport_types`, `get_bridge_types`, `scan_town_area`
- [ ] **5.1.5** `src/nttd/gameloop/schemas.py`: Add `agent_type: str = "bus"` field to AgentConfig
- [ ] **5.1.6** `src/nttd/gameloop/connection.py`: Prompt lookup map (`_PROMPT_MAP`) instead of hardcoded `get_bus_agent_prompt`
- [ ] **5.1.7** Test: Run rail agent session with gpt-5.2, fix GS bugs found
- [ ] **5.1.8** Test: Run air agent session, fix GS bugs found
- [ ] **5.1.9** Test: Run water agent session, fix GS bugs found

### 5.2 Finance in Compact Observation

- [ ] **5.2.1** `src/nttd/gameloop/connection.py`: Add `profit_last_year` to compact `company_dict`
- [ ] **5.2.2** `src/nttd/gameloop/schemas.py`: Add `include_finance: bool = False` to AgentConfig
- [ ] **5.2.3** `src/nttd/gameloop/connection.py`: When `include_finance=True`, fetch `get_company_finance` during observe and merge into company_dict

### 5.3 DB Layer — Wire Agent Tracking

> `agent_connections` and `agent_cycles` tables exist but are never written to. SessionRecorder exists but is never instantiated.

- [ ] **5.3.1** `src/nttd/runtime/session_runtime.py`: Instantiate `SessionRecorder` in `start_server()`, stop in `shutdown()`
- [ ] **5.3.2** `src/nttd/db/recorder.py`: Add `record_agent_cycle(record)` and `record_agent_connection(...)` methods + table map entries
- [ ] **5.3.3** `src/nttd/gameloop/connection.py`: After `tracker.end_cycle()` → call `runtime.recorder.record_agent_cycle(record)`; on start/stop → call `record_agent_connection`
- [ ] **5.3.4** `src/nttd/db/repositories/agent_repo.py` (new): `get_agent_connections(session_id)`, `get_agent_cycles(session_id, agent_id)`, `get_agent_summary(session_id)`
- [ ] **5.3.5** `src/nttd/api/metrics_routes.py`: Extend leaderboard with agent metrics (framework, model, total_cycles, avg_cycle_ms, avg_decide_ms) joined via `(session_id, company_id)`

### 5.4 Documentation

- [ ] **5.4.1** `docs/nttd_architecture_report.md`: Add sections on Gameloop Manager, Observation Toolkit, Agent Prompt System, DB Tracking
- [ ] **5.4.2** `docs/blog_building_ai_agents.md` (new): Blog article with Mermaid diagrams, code snippets, metric tables, screenshot placeholders
- [ ] **5.4.3** `scripts/generate_diagrams.py` (new): SVG diagram generator (architecture overview, gameloop cycle, transport modes)
- [ ] **5.4.4** Update `README.md` with links to blog + updated architecture report

---

## Phase 6 — Production & Scale

- [ ] PostgreSQL migration (swap SQLite connection string)
- [ ] TimescaleDB for time-series optimization
- [ ] Tournament mode (queue sessions, aggregate leaderboard)
- [ ] Gym/PettingZoo wrappers for RL training
- [ ] Training data export (Parquet format)
- [ ] OpenTelemetry observability
- [ ] Docker deployment (OpenTTD + nttd + admin-console)

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NTTD_DB_PATH` | `nttd.db` | SQLite database file path |
| `NTTD_OPENTTD_BINARY` | `/Applications/OpenTTD.app/Contents/MacOS/openttd` | Path to OpenTTD binary |
| `NTTD_BASE_CONFIG` | `ottd_config` | Template config directory |
| `NTTD_SESSIONS_DIR` | `runs` | Where per-session config dirs are created |
| `NTTD_PORT_RANGE_START` | `4000` | Starting port for allocation (even=game, odd=admin) |
| `NTTD_ADMIN_PASSWORD` | `nttd` | Admin password for all sessions |
| `NTTD_URL` | `http://localhost:8000` | MCP server: nttd API base URL |
| `NTTD_SESSION_ID` | — | MCP server: target session ID |
| `NTTD_AGENT_ID` | — | MCP server: agent identifier |
| `NTTD_COMPANY_ID` | `0` | MCP server: company to control |

---

## Milestone Targets

| Milestone | Deliverable | Status |
|-----------|------------|--------|
| **M1: Backend DB** | DB schema, recorder, metrics API | Done |
| **M2: Missing GS** | All GS commands, event forwarding | Done |
| **M3: Admin API** | All admin/deity/metrics/leaderboard endpoints | Done |
| **M4: Pathfinding** | A* service for road/rail/water | Done |
| **M5: Multi-Server** | Each session = own OpenTTD server, port isolation, orphan recovery | Done |
| **M6: Console MVP** | Create session → start game → join from OpenTTD client → spectate/play | Done |
| **M7: Game Loop** | Settings stored, defaults correct, archive on stop, full detail view | Done |
| **M8: Agent Loop** | Gameloop service, LangChain/OpenAI adapters, multi-turn tool calling, bus agent verified | Done |
| **M9: MCP Layer** | All 93+ GS commands as MCP tools, example agents, CLI guide | Done |
| **M10: Multi-Transport** | Rail/air/water agents, DB wiring, documentation | Phase 5 |
| **M11: Scale** | 150 connections, PostgreSQL, Docker | Phase 6 |
