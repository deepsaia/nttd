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

> After admin console works with human + AI games, integrate LLM agents.

### 4.1 Agent Framework Updates
- [ ] **4.1.1** Update agent base class for async real-time mode
- [ ] **4.1.2** Agent authentication (API keys)
- [ ] **4.1.3** Agent self-registration flow (connects to specific session)
- [ ] **4.1.4** Per-company action serialization with same-company multi-agent support
- [ ] **4.1.5** Agent-to-agent messaging integration

### 4.2 Pathfinding Integration
- [ ] **4.2.1** Agent tools for pathfinding (`POST /sessions/{id}/pathfind`)
- [ ] **4.2.2** Compound action builder: plan route → pathfind → build → deploy vehicles

### 4.3 Stress Testing
- [ ] **4.3.1** Load test: 15 companies × 10 agents = 150 connections
- [ ] **4.3.2** Action throughput: measure commands/second under load
- [ ] **4.3.3** DB write performance: verify batch inserts keep up at high game speed

---

## Phase 5 — Production & Scale

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
| **M8: Agents** | LLM agents playing via console, multi-agent same company | Phase 4 |
| **M9: Scale** | 150 connections, PostgreSQL, Docker | Phase 5 |
