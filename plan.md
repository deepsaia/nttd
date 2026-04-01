# nttd Implementation Plan

> **Focus**: Async real-time multiplayer where humans and/or LLM agents play, managed via Admin Console.
> **Reference docs**: `docs/openttd_study_part{1-4}_*.md`, `docs/nttd_architecture_report.md`

---

## Architecture Decisions (Locked)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Database | **SQLite** (fully normalized, ~20+ tables) → PostgreSQL later | Normalized for fast time-series queries, proper FK relationships, space-efficient. No JSON blobs for queryable data. |
| DB middle-layer | **Yes** — all reads from DB, not live state | Decouples ingestion from visualization. Dashboard reads DB. WebSocket = notification only. |
| Frontend | **React + Vite + Yarn (v4) + TypeScript + MUI,Tailwind** | Modern stack, good charting ecosystem (Recharts/Tremor). |
| Transport | **TCP only** (admin port + HTTP + WebSocket) | UDP unnecessary at our data rates (~0.5Hz). Admin port is TCP. Reliable delivery needed for actions. |
| Snapshot storage | **Normalized tables** + compressed JSON blob per snapshot for replay | Metrics/actions/events in proper columns. Full snapshot as parquet for replay only. |
| Concurrency model | **Per-company asyncio.Lock** for action serialization | 15 companies × 10 agents = 150 connections. Cross-company parallel, intra-company serial. |
| Primary runtime | **Async real-time** | Game runs continuously, agents observe and act in real-time. No pause/unpause cycle as of now. But we can define the run-time say 10 minutes or 60 minutes or define a goal, say, until one of the companies reach 1 million revenue. |

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

## Phase 2 — Backend Engine (Current)

> Build the data layer, missing GS commands, admin APIs, and pathfinding.
> **Goal**: Solid backend that the admin console can consume.

### 2.1 Database Layer
**Ref**: `docs/openttd_study_part4...md` §13

- [x] **2.1.1** Create `src/nttd/db/` package with `engine.py` (SQLAlchemy Core + aiosqlite, WAL mode)
- [x] **2.1.2** Schema definition: `src/nttd/db/tables.py` — 25 fully normalized SQLAlchemy tables:
  - `sessions` — id, name, status, settings columns (not JSON), timestamps
  - `session_settings` — key/value pairs per session (map_x, landscape, max_trains, etc.)
  - `participants` — session_id FK, type, participant_id, company_id, name, timestamps
  - `snapshots` — session_id FK, game_date, tick, compressed_json (replay only)
  - `companies` — session_id FK, game_date, company_id, name, balance, loan, income, expenses, value, rating (one row per company per snapshot)
  - `company_expenses` — session_id FK, game_date, company_id, category (13 expense types), amount
  - `towns` — session_id FK, game_date, town_id, name, population, x, y, is_city, growth_rate
  - `industries` — session_id FK, game_date, industry_id, type_name, x, y, production columns
  - `industry_production` — session_id FK, game_date, industry_id, cargo_id, produced, transported_pct
  - `stations` — session_id FK, game_date, station_id, company_id, name, x, y, facility flags
  - `station_cargo` — session_id FK, game_date, station_id, cargo_id, waiting, rating
  - `vehicles` — session_id FK, game_date, vehicle_id, company_id, type, engine_id, profit, speed, running, in_depot
  - `vehicle_orders` — session_id FK, game_date, vehicle_id, order_index, destination_id, order_type, flags
  - `subsidies` — session_id FK, game_date, subsidy_id, cargo_id, src_type, src_id, dst_type, dst_id, remaining
  - `actions` — session_id FK, participant_id, company_id, game_date, action_type, status, error, cost, submitted_at, completed_at
  - `action_parameters` — action_id FK, param_key, param_value (normalized key-value)
  - `events` — session_id FK, game_date, event_type, company_id, columns per event type
  - `messages` — session_id FK, game_date, type, from_id, to_id, company_id, body
  - `metrics` — session_id FK, game_date, company_id (nullable), metric_name, metric_value
  - `finances` — session_id FK, game_date, company_id, balance, loan, max_loan, income, expenses, company_value, performance_rating, cargo_delivered (per-snapshot financial summary — the "balance sheet" row)
  - `finance_revenue` — session_id FK, game_date, company_id, source (train/roadveh/aircraft/ship), amount (revenue broken down by vehicle type)
  - `finance_expenses` — session_id FK, game_date, company_id, category (construction/new_vehicles/train_run/roadveh_run/aircraft_run/ship_run/property/loan_interest/other), amount (maps to 13 GSCompany.ExpensesType values)
  - `finance_quarterly` — session_id FK, quarter_date, company_id, q_income, q_expenses, q_cargo_delivered, q_performance_rating, q_company_value (quarterly aggregated — from GSCompany.GetQuarterly* methods)
  - `cargo_flows` — session_id FK, game_date, company_id, cargo_id, town_or_industry_id, entity_type (town/industry), direction (delivery/pickup), amount (from GSCargoMonitor delta counters)
  - `infrastructure` — session_id FK, game_date, company_id, rail_pieces, road_pieces, water_pieces, station_pieces, airport_pieces, rail_cost, road_cost, water_cost, station_cost, airport_cost
  - `leaderboard` — session_id FK, company_id, participant_id, rank, final_value, final_rating, total_cargo, total_actions, success_rate
- [x] **2.1.3** Migration system: `src/nttd/db/migrations.py` — auto-applies `metadata.create_all` on startup. Wired into `app.py` lifespan.
- [x] **2.1.4** Repository layer: `src/nttd/db/repositories/` — session_repo, metrics_repo, action_repo, event_repo, entity_repo
  - Each repo: `get_*()`, `query_*()`, `list_*()` methods with filters
  - Batch insert via SessionRecorder's background flush
- [x] **2.1.5** Session recorder: `src/nttd/db/recorder.py` — background flush pattern (1s interval, 5000 max buffer)
  - Parquet writer for full snapshots (`src/nttd/db/parquet_writer.py`), zstd compression
  - Normalized data to SQLite, full snapshots to Parquet (no gzip blobs in DB)
  - Wired into `app.py` lifespan (DB init + migrations on startup, close on shutdown)
- [x] **2.1.6** Indexes for query performance:
  - `(session_id, game_date)` on all time-series tables
  - `(session_id, company_id, game_date)` on company-scoped tables
  - `(session_id, participant_id)` on actions and messages

### 2.2 Missing GS Commands
**Ref**: `docs/openttd_study_part3...md` §4-5, `docs/openttd_study_part4...md` §4.3, §9

High priority (needed for realistic gameplay and admin console):

- [x] **2.2.1** `get_game_settings` — read any game setting by key name (`GSGameSettings.GetValue()`)
- [x] **2.2.2** `set_game_setting` — write game setting (`GSGameSettings.SetValue()`) [deity]
- [x] **2.2.3** `get_expense_breakdown` — quarterly financials per company
- [x] **2.2.4** `get_infrastructure_costs` — `GSInfrastructure.GetMonthly*Costs()` + piece counts
- [x] **2.2.5** `get_cargo_flows` — `GSCargoMonitor.Get*Amount()` per company/cargo/town/industry
- [x] **2.2.6** `estimate_cost` — `GSTestMode` + `GSAccounting` wrapper for dry-run cost estimation
- [x] **2.2.7** `get_clients` — `GSClient` methods: list connected clients, their companies, names
- [x] **2.2.8** `change_bank_balance` — `GSCompany.ChangeBankBalance()` [deity]
- [x] **2.2.9** `set_max_loan` — `GSCompany.SetMaxLoanAmountForCompany()` [deity]

Medium priority (advanced gameplay):

- [x] **2.2.10** Conditional orders: `set_order_condition`, `set_order_compare_function`, `set_order_compare_value`
- [x] **2.2.11** Terraform: `raise_tile`, `lower_tile`, `level_tiles` (`GSTile.*`)
- [x] **2.2.12** `plant_tree`, `plant_tree_rectangle` (`GSTile.*`)
- [x] **2.2.13** `build_one_way_road`, `build_one_way_road_full` (`GSRoad.*`)
- [x] **2.2.14** `convert_road_type` (`GSRoad.ConvertRoadType()`)
- [x] **2.2.15** `set_stop_location` — train platform stop position (NEAR/MIDDLE/FAR)
- [x] **2.2.16** `get_engine_details` — running cost, capacity, speed, reliability (`GSEngine.*`)

Query enrichment (extend existing commands):

- [x] **2.2.17** Enrich `get_stations` — added cargo ratings
- [x] **2.2.18** Enrich `get_vehicles` — added running costs, capacity, running state
- [x] **2.2.19** Enrich `get_companies` — added performance rating, quarterly income/expenses/cargo, company value
- [x] **2.2.20** Enrich `get_industries` — added is_raw/is_processing to list; accepted cargo + stockpile to detail

Event monitoring (new GS-side event handler):

- [x] **2.2.21** GS event listener: catch 18 event types, forward via `GSAdmin.Send()`
  - Vehicle crashed/lost/unprofitable/autorenewed, subsidy offered/awarded/expired, industry open/close
  - Company new/in_trouble/bankrupt/merger, town founded, station first vehicle, zeppeliner crash
  - Each event → JSON packet → admin port → nttd

### 2.3 Admin API Endpoints
**Ref**: `docs/openttd_study_part4...md` §11, §12, §16, §18.4

Session management:

- [x] **2.3.1** `POST /admin/sessions/new` — create session, persist to DB
- [x] **2.3.2** `GET /admin/sessions` — list all sessions (active + completed)
- [x] **2.3.3** `GET /admin/sessions/{id}` — session details, participants, settings
- [x] **2.3.4** `POST /admin/sessions/{id}/settings` — update settings + apply via rcon
- [x] **2.3.5** `POST /admin/sessions/{id}/start` — apply settings, AI opponents, newgame/load
- [x] **2.3.6** `POST /admin/sessions/{id}/stop` — end session, pause game
- [x] **2.3.7** `DELETE /admin/sessions/{id}` — archive session

Player/agent management:

- [x] **2.3.8** `GET /admin/clients` — connected game clients via GS get_clients
- [x] **2.3.9** `POST /admin/clients/{id}/move` — move client to company via rcon
- [x] **2.3.10** `POST /admin/clients/{id}/kick` — kick client via rcon
- [ ] **2.3.11** `POST /admin/agents/{id}/launch` — start an agent process (subprocess) [deferred to Phase 4]
- [ ] **2.3.12** `POST /admin/agents/{id}/stop` — stop agent process [deferred to Phase 4]
- [x] **2.3.13** `GET /admin/spectators` — list spectators (company_id=255)

Deity operations:

- [x] **2.3.14** `POST /admin/deity/change_balance` — inject/remove money
- [x] **2.3.15** `POST /admin/deity/set_max_loan` — per-company loan limit
- [x] **2.3.16** `POST /admin/deity/found_town` — create new town
- [x] **2.3.17** `POST /admin/deity/expand_town` — grow town
- [x] **2.3.18** `POST /admin/deity/set_town_growth` — control growth rate
- [x] **2.3.19** `POST /admin/deity/create_subsidy` — offer subsidy
- [x] **2.3.20** `POST /admin/deity/change_town_rating` — modify company town rating
- [x] **2.3.21** `POST /admin/deity/set_setting` — modify game setting at runtime

Metrics/data:

- [x] **2.3.22** `GET /metrics/timeseries` — time-series query with filters
- [x] **2.3.23** `GET /metrics/latest` — current values for all companies
- [x] **2.3.24** `GET /metrics/comparison` — compare companies at a given date
- [x] **2.3.25** `GET /metrics/agent/{id}/performance` — agent action stats
- [x] `GET /metrics/finances` — financial time-series per company
- [x] `GET /metrics/available` — list distinct metric names

Messages:

- [x] **2.3.26** `POST /messages/send` — agent-to-agent or broadcast
- [x] **2.3.27** `GET /messages/history` — paginated message log
- [x] **2.3.28** `GET /messages/inbox/{agent_id}` — poll messages

Leaderboard:

- [x] **2.3.29** `GET /leaderboard/session/{id}` — per-session rankings
- [x] **2.3.30** `GET /leaderboard/global` — cross-session aggregate rankings
- [x] **2.3.31** `POST /leaderboard/compute/{id}` — recompute session rankings

Replay:

- [x] **2.3.32** `GET /replay/sessions/{id}/snapshots` — snapshot metadata for timeline
- [x] **2.3.33** `GET /replay/sessions/{id}/actions` — all actions
- [x] `GET /replay/sessions/{id}/events` — all events
- [ ] **2.3.34** `GET /replay/sessions/{id}/export` — full session export (ZIP) [deferred]

Entity data (for dashboard):

- [x] `GET /admin/data/towns` — latest town snapshot
- [x] `GET /admin/data/industries` — latest industry snapshot
- [x] `GET /admin/data/stations` — latest station snapshot (filterable by company)
- [x] `GET /admin/data/vehicles` — latest vehicle snapshot (filterable by company)
- [x] `GET /admin/data/subsidies` — latest subsidy snapshot

### 2.4 Pathfinding Service
**Ref**: `docs/openttd_study_part4...md` §14

- [x] **2.4.1** Tile cache: `src/nttd/pathfinding/tile_cache.py` — 2D array, batch loading via GS
  - `load_area`, `load_full`, `load_corridor` (with margin), `invalidate_area/tile`
- [x] **2.4.2** A* core: `src/nttd/pathfinding/astar.py` — generic A* with CostFunction protocol
  - Priority queue (heapq), visited set, path reconstruction, max_iterations limit
- [x] **2.4.3** Road pathfinder: `src/nttd/pathfinding/road.py`
  - Cost model: flat=100, slope=+200, crossing=+300, demolish=+500
- [x] **2.4.4** Rail pathfinder: `src/nttd/pathfinding/rail.py`
  - Direction-aware state (x, y, direction), no 180° turns, curve penalties
- [x] **2.4.5** Water pathfinder: `src/nttd/pathfinding/water.py`
  - Water=50, canal=500, lock=800, coast=100
- [x] **2.4.6** GS command: `get_tile_area` — batch tile scan (up to 400 tiles per call)
- [x] **2.4.7** API endpoint: `POST /admin/pathfind` with transport_type, from/to, options
- [x] **2.4.8** Service layer: `src/nttd/pathfinding/service.py` — orchestrates cache + A*

### 2.5 Connection & Concurrency Hardening
**Ref**: `docs/openttd_study_part4...md` §15, §17

- [x] **2.5.1** Auto-reconnect with exponential backoff (already in admin_client.py)
- [ ] **2.5.2** Save/load detection → clear WorldState, notify agents [deferred — needs protocol analysis]
- [x] **2.5.3** Per-company asyncio.Lock: `src/nttd/runtime/company_lock.py` — CompanyLockManager
  - Wired into orchestrator `_execute_actions`, serializes same-company actions
- [x] **2.5.4** WebSocket connection manager (already exists in ws_routes.py, lightweight triggers)
- [ ] **2.5.5** GS query pipeline: send next query while waiting for response [deferred — optimization]
- [x] **2.5.6** Staggered refresh: companies every cycle, towns/industries every 5 cycles
- [x] **2.5.7** Health ping: `admin_client.health_ping()` + GS event forwarding via `on_game_event()`

---

## Phase 3 — Admin Console Frontend

> React + Vite + Yarn + TypeScript + Tailwind
> **Goal**: Full spectate milestone — start AI game, watch from browser.

### 3.1 Project Setup
- [x] **3.1.1** Initialize: `admin-console/` with Vite + React + TypeScript + Tailwind + MUI
- [x] **3.1.2** Yarn v4 (Berry) configuration — per-project, no global changes
- [x] **3.1.3** API client module: typed HTTP client wrapping all nttd endpoints (`src/api/client.ts`)
- [x] **3.1.4** WebSocket hook: `useWebSocket()` — connect to `/ws/admin`, parse triggers, auto-reconnect
- [x] **3.1.5** Zustand store: `gameStore.ts` — real-time game state, companies, events (ring buffer 200)
  - `themeStore.ts` — dark/light mode toggle with localStorage persistence
- [x] **3.1.6** React Router: 4 pages (Session, Players, Metrics, Leaderboard) + Sidebar navigation
- [x] **3.1.7** Vite proxy config for API (`/api` → `:8000`) + WebSocket (`/ws` → `:8000`)

### 3.2 Page 1 — Session Management
**Ref**: `docs/openttd_study_part4...md` §11.2

- [x] **3.2.1** Session creation form: settings grouped by category (Map, Economy, Vehicles, AI)
- [ ] **3.2.2** Session presets: save/load settings configurations [deferred — needs backend preset storage]
- [x] **3.2.3** Session list: active + completed sessions with status badges, select/delete
- [x] **3.2.4** Session controls: Start, Stop, Save, Load + Top bar Pause/Unpause + Speed slider
- [x] **3.2.5** AI opponents selector: count dropdown (0-14) on start
- [x] **3.2.6** Connection info display: server IP, port, map size, landscape

### 3.3 Page 2 — Players & Agents
**Ref**: `docs/openttd_study_part4...md` §11.3

- [x] **3.3.1** Connected agents panel: list with company scope, subscriptions, online status
- [x] **3.3.2** Connected humans panel: list with company, name, client ID
- [x] **3.3.3** Spectators panel (company_id=255 clients)
- [ ] **3.3.4** Agent launch dialog: select type, company, config [deferred to Phase 4]
- [x] **3.3.5** Move/kick controls (with confirmation prompts)
- [x] **3.3.6** Live event feed: scrolling log from WebSocket events (ring buffer 200)
- [x] **3.3.7** Message center: view history + send chat messages

### 3.4 Page 3 — Metrics & Timeline
**Ref**: `docs/openttd_study_part4...md` §12.4

- [x] **3.4.1** Time-series line charts (Recharts): balance, income, value over time per company
- [ ] **3.4.2** Stacked bar charts: revenue by vehicle type [deferred — needs finance_revenue data]
- [ ] **3.4.3** Pie charts: expense breakdown per company [deferred — needs finance_expenses data]
- [x] **3.4.4** Performance rating bar chart + cargo delivered bar chart
- [ ] **3.4.5** Timeline scrubber: drag to any game date, see state at that point [deferred]
- [ ] **3.4.6** Event markers on timeline (crashes, subsidies, bankruptcies) [deferred]
- [x] **3.4.7** Filters: company selector (all or individual)
- [ ] **3.4.8** Data export: CSV download for selected metrics [deferred]

### 3.5 Page 4 — Leaderboard
**Ref**: `docs/openttd_study_part4...md` §16

- [x] **3.5.1** Per-session leaderboard table: rank, company, player, balance, value, rating, cargo, actions, success rate
- [x] **3.5.2** Cross-session leaderboard: aggregate stats per participant (sessions, avg rank, total cargo, avg success)
- [x] **3.5.3** Sortable columns (MUI TableSortLabel)
- [ ] **3.5.4** Participant detail view: session history, per-session performance [deferred]

### 3.6 Top Bar (Global)
- [x] **3.6.1** Game status: current date, speed, paused/playing indicator, company count, mode
- [x] **3.6.2** Connection status: OpenTTD connected/disconnected chip
- [x] **3.6.3** Quick controls: pause/play toggle, speed slider, dark/light mode toggle

---

## Phase 4 — Agent Integration

> After admin console works with AI-only games, integrate LLM agents.

### 4.1 Agent Framework Updates
- [ ] **4.1.1** Update agent base class for async real-time mode (no heartbeat, continuous loop)
- [ ] **4.1.2** Agent authentication (API keys)
- [ ] **4.1.3** Agent self-registration flow
- [ ] **4.1.4** Per-company action serialization with same-company multi-agent support
- [ ] **4.1.5** Agent-to-agent messaging integration

### 4.2 Pathfinding Integration
- [ ] **4.2.1** Agent tools for pathfinding (`POST /pathfind`)
- [ ] **4.2.2** Compound action builder: plan route → pathfind → build → deploy vehicles

### 4.3 Stress Testing
- [ ] **4.3.1** Load test: 15 companies × 10 agents = 150 connections
- [ ] **4.3.2** Action throughput: measure commands/second under load
- [ ] **4.3.3** DB write performance: verify batch inserts keep up at high game speed

---

## Phase 5 — Production & Scale

- [ ] PostgreSQL migration (swap SQLite connection string)
- [ ] TimescaleDB for time-series optimization
- [ ] Multiple concurrent sessions (separate nttd process per session)
- [ ] Tournament mode (queue sessions, aggregate leaderboard)
- [ ] Gym/PettingZoo wrappers for RL training
- [ ] Training data export (Parquet format)
- [ ] OpenTelemetry observability
- [ ] Docker deployment (OpenTTD + nttd + admin-console)

---

## Milestone Targets

| Milestone | Deliverable | Depends On |
|-----------|------------|------------|
| **M1: Backend DB** | DB schema, recorder, metrics API | Phase 2.1 |
| **M2: Missing GS** | All high-priority GS commands, event forwarding | Phase 2.2 |
| **M3: Admin API** | All admin/deity/metrics/leaderboard endpoints | Phase 2.3, M1, M2 |
| **M4: Pathfinding** | A* service for road/rail/water | Phase 2.4 |
| **M5: Console MVP** | Full spectate: start AI game, watch live, replay | Phase 3, M3 |
| **M6: Agents** | LLM agents playing via console, multi-agent same company | Phase 4, M5 |
| **M7: Scale** | 150 connections, PostgreSQL, Docker | Phase 5, M6 |
