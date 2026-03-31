# OpenTTD Study Part 4: Multiplayer, AI Agents, and System Design

> Companion to Parts 1-3. Covers multiplayer mechanics, LLM agent integration, admin client architecture, game state management, and technical constraint mitigation strategies.
>
> **Primary sources**: OpenTTD C++ source ([openTTD](https://github.com/OpenTTD/OpenTTD)), OpenTTD wiki, nttd codebase, docs.openttd.org GS/AI API references.

---

## Table of Contents

1. [Multiplayer Mechanics](#1-multiplayer-mechanics)
2. [Company Sharing — Multiple Clients, One Company](#2-company-sharing--multiple-clients-one-company)
3. [OpenTTD's Built-in AI vs Our LLM Agents](#3-openttds-built-in-ai-vs-our-llm-agents)
4. [Action Parity — Can Our Agent Do Everything a Human Can?](#4-action-parity--can-our-agent-do-everything-a-human-can)
5. [What the Admin Client Is For](#5-what-the-admin-client-is-for)
6. [Game State — Fetching, Serving, and Storage](#6-game-state--fetching-serving-and-storage)
7. [Technical Constraints Mitigation](#7-technical-constraints-mitigation)
8. [Summary of Key Design Decisions](#8-summary-of-key-design-decisions)
9. [Financial Data — Fetching and Provisioning](#9-financial-data--fetching-and-provisioning)
10. [Message Stream — System, Player, and Agent-to-Agent](#10-message-stream--system-player-and-agent-to-agent)
11. [Admin Console / Dashboard](#11-admin-console--dashboard)
12. [Game Metrics, Visualization, and Replay](#12-game-metrics-visualization-and-replay)
13. [Data Persistence — Local Database Design](#13-data-persistence--local-database-design)
14. [Pathfinding Algorithm Design](#14-pathfinding-algorithm-design)
15. [Command Tracking and Serialization](#15-command-tracking-and-serialization)
16. [Leaderboard System](#16-leaderboard-system)
17. [Performance Architecture](#17-performance-architecture)
18. [Tech Stack — Admin Console Frontend](#18-tech-stack--admin-console-frontend)

---

## 1. Multiplayer Mechanics

### 1.1 How Multiplayer Works

OpenTTD multiplayer uses a **dedicated server model**. One instance runs as the server (headless with `-D` flag, or with GUI), and clients connect over TCP.

| Parameter | Value | Source |
|-----------|-------|--------|
| Game port | 3979 (TCP) | `network/core/config.h` |
| Admin port | 3977 (TCP) | `network/core/config.h` |
| Max companies | 15 (configurable, hard limit 15) | `company_type.h` |
| Max clients | 255 (configurable) | `network_type.h` |
| Max admin connections | 16 | `network_type.h:53` |

**Connection flow:**
1. Client connects to game port 3979
2. Server sends game info (map size, name, companies, clients)
3. Client authenticates (server password if set)
4. Client chooses: create new company, join existing company, or spectate
5. Server synchronizes game state (map download)
6. Client begins receiving game ticks

### 1.2 Pause Mechanics — Global Only

**Critical insight: pause in multiplayer is GLOBAL.** There is no per-client pause. When the game pauses, it pauses for everyone.

OpenTTD defines **8 pause modes** (from `openttd.h:68-77`):

| Mode | Trigger | Description |
|------|---------|-------------|
| `Normal` | Server admin / GS | Manual pause (rcon `pause`) |
| `SaveLoad` | Save/load operation | Auto-pause during save/load |
| `Join` | Client joining | Auto-pause if `pause_on_join = true` |
| `Error` | Critical error | Emergency pause |
| `ActiveClients` | Client count | Auto-pause if clients < `min_active_clients` |
| `GameScript` | GS command | `GSGame.Pause()` from GameScript |
| `LinkGraph` | Link graph lag | Auto-pause if link graph falls behind |
| `CommandDuringPause` | Command execution | Transient pause for command processing |

**Who can pause?**
- Server admin: YES (via rcon or console)
- GameScript: YES (`GSGame.Pause()` / `GSGame.Unpause()`)
- Individual clients: NO — `CmdPause` has `CommandFlag::Server` flag (`misc_cmd.h:36`)
- Admin port: YES — via rcon command `pause` / `unpause`

**Pause modes are independent.** The game is paused if ANY mode is active. Multiple modes can be active simultaneously (e.g., `GameScript` + `Join`). The game resumes only when ALL pause modes are cleared.

### 1.3 Save/Load in Multiplayer

- **Saving**: possible mid-game via rcon `save <name>`. Triggers `PauseMode::SaveLoad` automatically.
- **Loading**: possible via rcon `load <name>`. Disconnects all game clients (they must rejoin). Admin port connections SURVIVE save/load.
- **Autosave**: configurable interval, also triggers `PauseMode::SaveLoad`.

### 1.4 Game Speed

- **Fast-forward is DISABLED** in multiplayer — all clients must stay synchronized.
- **Game speed IS configurable** via rcon: `setting game_speed N`
  - Default: 100 (normal speed)
  - Range: any positive integer (e.g., 50 = half speed, 200 = double speed)
  - Affects ALL clients equally
- nttd exposes this as `POST /speed` endpoint.

### 1.5 Implications for AI Agents

| Aspect | Impact |
|--------|--------|
| Global pause | Heartbeat mode (pause-observe-act-unpause) works perfectly for pure-agent play. Not suitable when humans are co-playing. |
| No per-client pause | In async real-time mode, agents must operate at game pace. Slow game speed gives agents more thinking time. |
| Save/load survives admin | nttd's admin_client persists across save/load cycles — no reconnection needed for the bridge. |
| No fast-forward | Training/benchmarking still possible via `game_speed` setting (e.g., 1000 for 10x speed). |
| Shared timeline | All agents and humans see the same game state at the same time — no synchronization issues between agents. |

---

## 2. Company Sharing — Multiple Clients, One Company

### 2.1 Confirmed: Multiple Clients CAN Share a Company

**YES.** This is confirmed in the OpenTTD source code. Multiple clients can simultaneously control the same company.

**Evidence from source** (`network_server.cpp:1605-1652`):

Each connected client has a `client_playas` field in `NetworkClientInfo` (`network_base.h:28`) that stores which company they're playing as. The code iterates all clients and checks their company membership — there is no restriction preventing multiple clients from having the same `client_playas` value.

When a client sends a command (build road, buy vehicle, etc.), the command executes for the company that client belongs to (`network_server.cpp:1161`). If two clients are in the same company, both can issue commands for that company simultaneously.

### 2.2 Company Authorization

OpenTTD uses **public key-based authorization** (not traditional passwords in modern versions):

```cpp
// company_base.h:83-84
NetworkAuthorizedKeys allow_list{};  // Public keys allowed to join
bool allow_any = false;              // If true, anyone can join
```

**Authorization methods** (`company_cmd.cpp:1008-1030`):
- `CompanyAllowListCtrlAction::AddKey` — add a client's public key to the allow list
- `CompanyAllowListCtrlAction::RemoveKey` — remove a public key
- `CompanyAllowListCtrlAction::AllowAny` — open the company to anyone
- `CompanyAllowListCtrlAction::AllowListed` — restrict to allow list only

**Validation** (`network.cpp:132-146`):
```cpp
bool NetworkClientInfo::CanJoinCompany(CompanyID company_id) const {
    const Company *c = Company::GetIfValid(company_id);
    return c != nullptr && (c->allow_any || c->allow_list.Contains(this->public_key));
}
```

### 2.3 Spectator Mode

Clients can join as spectators (`COMPANY_SPECTATOR = 255`) to observe without controlling any company. Spectators see the full game state but cannot issue commands.

### 2.4 Server-Side Client Movement

The server can relocate clients between companies via the `move` console command:
```
move <client_id> <company_id>
```
This allows the server admin (or nttd via rcon) to programmatically assign clients to companies.

### 2.5 Implications for Multi-Agent Same-Company Play

This is a key finding for the nttd architecture:

**Two or more LLM agents CAN control the same company.** The mechanism:

1. Both agents register with nttd, both with the same `company_scope` (e.g., `[0]`)
2. Both observe the same game state snapshots
3. Both submit actions independently to nttd
4. nttd routes all actions through the single GS bridge using `GSCompanyMode(0)`
5. GS executes actions sequentially (one at a time)

**Coordination concerns:**
- No built-in locking — two agents could try to spend the same money simultaneously
- nttd should serialize actions per company in the action queue
- Agents should observe current state before acting (money available, station capacity, etc.)
- Action validation: nttd can pre-check feasibility before sending to GS

**Current nttd support:**
- `AgentRegistration.company_scope: list[int]` already allows overlapping scopes
- `control_routes.py:95-114` enforces scope per action — just needs to allow multiple agents per company
- The orchestrator's action execution loop (`orchestrator.py:166-212`) processes actions sequentially, which naturally serializes same-company actions

---

## 3. OpenTTD's Built-in AI vs Our LLM Agents

### 3.1 The NoAI Framework

OpenTTD's built-in AI uses the **NoAI framework** — Squirrel scripts with `AI*` API classes (AIVehicle, AIRoad, AIRail, etc.). This is a **completely separate API** from GameScript's `GS*` classes.

| Aspect | Built-in AI (NoAI) | GameScript (GS/NoGo) |
|--------|--------------------|-----------------------|
| API classes | `AI*` (AIVehicle, AIRoad, ...) | `GS*` (GSVehicle, GSRoad, ...) |
| Company scope | Bound to ONE company forever | Deity mode; can switch to any company via `GSCompanyMode` |
| Execution | Per-company `Start()` loop | Single global instance |
| Opcode budget | ~10k opcodes/tick (configurable) | Same budget system (`script_max_opcode_till_suspend`) |
| Lifecycle | Dies when company goes bankrupt | Persists for game duration |
| Language | Squirrel | Squirrel |
| Command system | Same `DoCommand` as humans | Same `DoCommand` via `ScriptObject::Command` |

### 3.2 How AI Scripts Perform Actions

AI scripts use the **exact same DoCommand system** as human players. This is verified in the C++ source:

```cpp
// script_rail.cpp:148 — example of AI/GS building a rail depot
return ScriptObject::Command<Commands::BuildRailDepot>::Do(tile, (::RailType)ScriptObject::GetRailType(), entrance_dir);
```

The execution flow (`script_object.hpp:413-446`):
1. `ScriptObject::DoCommandPrep()` — validates mode and state
2. `::Command<Tcmd>::Unsafe()` — executes the actual game command (same as human click)
3. `ScriptObject::DoCommandProcessResult()` — handles result, suspends if needed

**In multiplayer**, AI commands go through the network command queue like player commands:
```cpp
// script_object.cpp:323-325
if (_networking) {
    throw Script_Suspend(-(int)GetDoCommandDelay(), callback);  // Wait for server confirmation
}
```

### 3.3 AI Execution Model

- **Opcode budget**: `script_max_opcode_till_suspend` opcodes per tick (configurable in settings)
- **Suspension**: when budget exhausted, AI is suspended until next tick
- **Sleep**: `AIController.Sleep(ticks)` voluntarily pauses the script
- **Command delay**: minimum ticks between commands (prevents flooding)
- **Speed throttling**: `difficulty.competitor_speed` controls how often AI GameLoop runs (`ai_core.cpp:80-82`)
- **Event polling**: 35 event types via `AIEventController.IsEventWaiting()` / `GetNextEvent()`
- **Main loop**: `Start()` must loop forever or the AI dies
- **Save/load**: pending events are LOST on save/load

### 3.4 What AI Can Do That GS Cannot (and Vice Versa)

**AI-exclusive capabilities**: None. Everything an AI can do, GS can also do (via `GSCompanyMode`).

**GS-exclusive powers** (AI CANNOT do these):
- `GSCompany.ChangeBankBalance()` — inject/remove money directly
- `GSCompany.SetMaxLoanAmountForCompany()` — per-company loan limits
- `GSTown.SetGrowthRate()`, `ExpandTown()`, `SetName()`, `SetText()`, `ChangeRating()`, `SetCargoGoal()`
- `GSGoal.*` — create, track, and complete goals
- `GSStoryPage.*` — narrative story pages
- `GSSubsidy.Create()` — create subsidies
- `GSGame.Pause()` / `Unpause()` — game flow control
- `GSGameSettings.SetValue()` — modify game settings
- `GSAdmin.Send()` — communicate with admin port
- Cross-company actions from a single control point

### 3.5 How Our LLM Agents Differ

Our LLM-powered agents are **fundamentally different** from OpenTTD's built-in AI:

| Aspect | Built-in AI | Our LLM Agents |
|--------|------------|-----------------|
| Runs where | Inside OpenTTD process (Squirrel VM) | External process (Python, any language) |
| Connection | Direct API calls within game | Via nttd REST/WebSocket API |
| Execution path | AI API → DoCommand | Agent → nttd API → Admin Port → GS → DoCommand |
| Computation | Limited by opcode budget per tick | Unlimited external compute |
| Pathfinding | Must fit in opcode budget | Can use sophisticated algorithms externally |
| State access | Direct memory access to game objects | Snapshot-based observation via GS queries |
| Company control | Exactly one, forever | Configurable via `company_scope` |
| Reasoning | Scripted logic (if/else trees) | LLM-based planning and reasoning |
| Multi-agent | Each AI = one company | Multiple agents can share a company |

**Our approach is MORE powerful** because:
1. GS has deity powers that AI scripts lack
2. No opcode budget constraint (external compute is unlimited)
3. External pathfinding can use sophisticated algorithms (A*, etc.)
4. Multiple agents can cooperate on the same company
5. Agents can reason about long-term strategy using LLM capabilities

### 3.6 Answers to Specific Questions

**Do in-game AI players perform actions on their own?**
Yes. Each AI company runs its own Squirrel script that executes autonomously every tick. The script's `Start()` method runs in an infinite loop, sleeping between actions. The AI observes game state, makes decisions, and issues commands — all without human intervention.

**How do AI players perform complex actions?**
Through multi-step scripted sequences. For example, to build a bus route:
1. Find two towns (using `AITown` list + valuator)
2. Pathfind a road between them (using imported A* library, split across multiple ticks)
3. Build road tiles along the path (`AIRoad.BuildRoad()`)
4. Build bus stops at each end (`AIRoad.BuildRoadStation()`)
5. Buy a bus (`AIVehicle.BuildVehicle()`)
6. Add orders (`AIOrder.AppendOrder()`)
7. Start the vehicle (`AIVehicle.StartStopVehicle()`)

Each step may take multiple ticks due to opcode budget and command delays.

**Can a human control multiple companies?**
No — one company per client at a time. A human can switch companies using the company window or spectate, but cannot simultaneously control two companies. The server's `move` command can reassign a client to a different company.

**Can AI control multiple companies?**
No — each AI script is permanently bound to exactly one company. When the company goes bankrupt, the AI dies.

**How is it possible for AI to perform any action a human can?**
Because both AI scripts and human GUI clicks ultimately go through the same `DoCommand` system in the game engine. Every button click in the GUI maps to a specific `Commands::XXX` enum. AI scripts call `ScriptObject::Command<Commands::XXX>::Do()` which invokes the exact same command. The GS API exposes methods for every command that matters.

**Should we model our GS commands on the AI API?**
Yes — the AI API (`AI*` classes) is the closest analog to "everything a player can do." The method signatures are nearly identical to GS (`GS*` classes). We should audit the full AI API method list and ensure our GS commands cover every action an AI (or human) can take. See Section 4 for the gap analysis.

---

## 4. Action Parity — Can Our Agent Do Everything a Human Can?

### 4.1 The Command Equivalence Chain

```
Human GUI click → Commands::XXX → DoCommand()
AI Script call  → ScriptObject::Command<Commands::XXX>::Do() → DoCommand()
GS Script call  → ScriptObject::Command<Commands::XXX>::Do() → DoCommand()
```

All three paths converge on the same `DoCommand()` function. Therefore: **if the GS API exposes a method for a command, nttd can replicate that human/AI action.**

### 4.2 Current Coverage

| Category | Total Primitives | Implemented in nttd | Coverage |
|----------|-----------------|---------------------|----------|
| Queries (read state) | 28+ | 28 | ~100% |
| Smart queries (heuristic) | 3 | 3 | 100% |
| Road construction | 7 | 7 | 100% |
| Rail construction | 11 | 11 | 100% |
| Marine construction | 8 | 4 | 50% |
| Other construction | 7 | 7 | 100% |
| Company management | 3 | 3 | 100% |
| Town manipulation (deity) | 7 | 7 | 100% |
| Vehicle management | 12 | 12 | 100% |
| Order management | 9 | 9 | 100% |
| Group management | 4 | 4 | 100% |
| Signs | 2 | 2 | 100% |
| Subsidies (deity) | 1 | 1 | 100% |
| **Total** | **~112** | **93** | **~83%** |

### 4.3 Missing Actions — Gap from AI API Comparison

Actions present in the AI API (i.e., things a human player or built-in AI can do) that are NOT yet in our GS commands:

#### High Priority (common gameplay actions)

| Action | GS Method | Why Needed |
|--------|-----------|------------|
| Conditional orders | `GSOrder.SetOrderCondition()`, `SetOrderCompareFunction()`, `SetOrderCompareValue()` | Essential for smart vehicle routing (go to depot if load < 50%, etc.) |
| Terraform (raise/lower) | `GSTile.RaiseTile()`, `LowerTile()`, `LevelTiles()` | Required for construction on uneven terrain |
| Tree planting | `GSTile.PlantTree()`, `PlantTreeRectangle()` | Town authority rating improvement strategy |
| Cargo monitoring | `GSCargoMonitor.GetTownDeliveryAmount()`, `GetIndustryDeliveryAmount()` | Track cargo flow for optimization |
| Game settings read/write | `GSGameSettings.GetValue()`, `SetValue()`, `IsValid()` | Configure game parameters, check limits |
| Cost estimation (test mode) | Execute action in `GSTestMode` | Plan before spending — critical for financial planning |

#### Medium Priority (advanced gameplay)

| Action | GS Method | Why Needed |
|--------|-----------|------------|
| One-way roads | `GSRoad.BuildOneWayRoad()`, `BuildOneWayRoadFull()` | Traffic management in cities |
| Road type conversion | `GSRoad.ConvertRoadType()` | Upgrade roads (e.g., normal → tram) |
| Auto-replace setup | `GSGroup.SetAutoReplace()` | Automated vehicle fleet modernization |
| Nested group hierarchy | `GSGroup.SetParentGroup()`, `GetParentGroup()` | Organizational structure for large fleets |
| Wagon chain manipulation | `GSVehicle.MoveWagon()`, `MoveWagonChain()` | Custom train consist building |
| Train stop location | `GSOrder.SetStopLocation()` (NEAR/MIDDLE/FAR) | Platform alignment for loading efficiency |
| Get vehicle running costs | `GSEngine.GetRunningCost()` | Financial planning |
| Get vehicle capacity | `GSEngine.GetCapacity()` | Route planning |

#### Lower Priority (situational)

| Action | GS Method | Why Needed |
|--------|-----------|------------|
| Livery colors | `GSCompany.SetLiveryColour()` | Cosmetic, but affects visual distinction |
| Auto-renew settings | `GSCompany.SetAutoRenewStatus()`, etc. | Company policy management |
| Infrastructure costs query | `GSInfrastructure.GetMonthlyRailCosts()`, etc. | Financial analysis |
| Noise level check | `GSAirport.GetNoiseLevelIncrease()` | Airport placement feasibility |
| Town effect queries | `GSCargo.GetTownEffect()` | Town growth strategy |

### 4.4 Recommendation

To reach **100% action parity** with human players:
1. Implement all high-priority gaps (6 items) — these are required for realistic gameplay
2. Implement medium-priority gaps (8 items) — these enable advanced strategies
3. Add query enrichment to existing commands (running costs, capacities, infrastructure costs in responses)
4. Build a `get_game_settings` command to expose all configurable limits

Total additional GS commands needed: ~20-25 to cover everything.

---

## 5. What the Admin Client Is For

### 5.1 Architecture Role

The admin port (TCP 3977) is **nttd's ONLY connection** to the OpenTTD server. It serves three critical roles:

```
┌──────────┐     Admin Port (3977)     ┌──────────────┐
│          │◄──── JSON responses ──────│              │
│   nttd   │                           │   OpenTTD    │
│  server  │──── JSON commands ───────►│   Server     │
│          │──── rcon commands ───────►│              │
│          │◄──── state updates ──────│              │
└──────────┘                           └──────────────┘
```

### 5.2 Three Roles

#### Role 1: Transport Layer (GS Bridge)

Sends JSON commands to GameScript, receives JSON responses:
- **Outbound**: `ADMIN_PACKET_ADMIN_GAMESCRIPT` (max 9000 bytes per packet)
- **Inbound**: `ADMIN_PACKET_SERVER_GAMESCRIPT` (max ~1450 bytes per packet, chunked)
- **Protocol**: correlation IDs (`gs_1`, `gs_2`, ...) for request/response matching
- This is how ALL game actions and queries flow through nttd

#### Role 2: State Subscription

Receives push updates from the server without polling:

| Update Type | Available Frequencies | Data Provided |
|------------|----------------------|---------------|
| `DATE` | Poll, Daily, Weekly, Monthly, Quarterly, Annually | Current game date |
| `CLIENT_INFO` | Poll, Automatic | Client name, company, join date |
| `COMPANY_INFO` | Poll, Automatic | Company name, color, AI flag, active status |
| `COMPANY_ECONOMY` | Poll, Weekly, Monthly, Quarterly, Annually | Money, loan, income, quarterly history |
| `COMPANY_STATS` | Poll, Weekly, Monthly, Quarterly, Annually | Vehicle/station counts by type |
| `CHAT` | Automatic only | Chat messages (player, team, server) |
| `CONSOLE` | Automatic only | Console output |
| `CMD_NAMES` | Poll only | List of all DoCommand names |
| `CMD_LOGGING` | Automatic only | Every command executed (player, tile, args) |
| `GAMESCRIPT` | Automatic only | JSON from GS (`GSAdmin.Send()`) |

**nttd currently subscribes to** (`admin_client.py:143-150`):
- DATE (daily) — track game progression
- COMPANY_INFO (automatic) — detect new/removed companies
- COMPANY_ECONOMY (quarterly) — financial updates
- COMPANY_STATS (quarterly) — fleet statistics
- CHAT (automatic) — player communication
- CONSOLE (automatic) — server messages
- GAMESCRIPT (automatic) — GS responses

#### Role 3: Server Control (rcon)

Remote console commands (max 500 bytes per command):
- `pause` / `unpause` — game flow control
- `save <name>` / `load <name>` — game persistence
- `setting <key> <value>` — change game settings (e.g., `setting game_speed 200`)
- `kick <client_id>` / `ban <client_id>` — client management
- `move <client_id> <company_id>` — reassign client to company
- `start_ai <name>` / `stop_ai <company_id>` — AI company management
- `reset_company <company_id>` — remove a company
- `clients` / `companies` — status queries

### 5.3 Why Admin Port Cannot Be Replaced

**GS alone is insufficient** because:
- GS has no way to receive external input without the admin port. `GSEventAdminPort` is the only mechanism for external → GS communication.
- GS cannot send data to external systems except via `GSAdmin.Send()` through the admin port.
- Server control (pause, save, settings) requires rcon, which flows through the admin port.

**The admin port is the bridge.** Without it, nttd has no way to talk to the game.

### 5.4 Connection Limits and Reliability

- **Max 16 simultaneous admin connections** (pool-based, `network_type.h:53`)
- **10-second auth timeout** — must authenticate quickly (`network_admin.cpp:44`)
- **Admin connections survive save/load** — unlike game clients
- **nttd needs exactly 1 connection** — additional connections can be used for monitoring tools
- **Protocol version**: currently v3 (`core/config.h:46`)

---

## 6. Game State — Fetching, Serving, and Storage

### 6.1 Timing Model

| Unit | Ticks | Real Time (normal speed) |
|------|-------|--------------------------|
| 1 tick | 1 | 27 ms |
| 1 day | 74 ticks | ~2 seconds |
| 1 month | ~2220 ticks | ~60 seconds |
| 1 quarter | ~6660 ticks | ~3 minutes |
| 1 year | ~27010 ticks | ~12 minutes |

Source: `timer_game_tick.h:72` — `DAY_TICKS = 74`, `gfx_type.h:370` — `MILLISECONDS_PER_TICK = 27`

Game speed multiplier: `game_speed = N` means `N%` of normal speed. At `game_speed = 200`, a day takes ~1 second. At `game_speed = 1000`, a day takes ~0.2 seconds.

### 6.2 Snapshot Frequency

**Default recommendation: 1 snapshot per game-day** (configurable).

| Mode | Recommended Frequency | Rationale |
|------|----------------------|-----------|
| Heartbeat (RL training) | Per day or per week | Depends on action granularity needed |
| Heartbeat (fast benchmark) | Per week or per month | Reduce overhead at high game speeds |
| Async real-time (human co-play) | Event-driven + periodic full refresh | Real-time events + weekly full state |
| Assisted (co-pilot) | On-demand | Snapshot when human requests AI help |

**Admin port push granularity:**
- Finest periodic push: **DAILY** for date updates
- Event-driven push: **AUTOMATIC** for company changes, chat, GS messages
- No per-tick push exists in the protocol

**GS query frequency:**
- Can query at any rate, but limited by opcode budget
- Heavy queries (all stations + all vehicles for all companies) consume significant opcodes
- Recommendation: stagger queries across ticks (towns tick 1, industries tick 2, companies tick 3, etc.)

### 6.3 Snapshot Structure

A comprehensive game state snapshot in JSON:

```json
{
  "meta": {
    "snapshot_id": "snap_00042",
    "game_date": 730120,
    "game_date_formatted": "2001-03-15",
    "tick": 54028880,
    "timestamp_utc": "2025-03-15T14:30:00Z",
    "game_speed": 100,
    "paused": false,
    "mode": "heartbeat"
  },

  "map": {
    "size_x": 256,
    "size_y": 256,
    "landscape": "temperate",
    "seed": 123456789
  },

  "game_settings": {
    "max_roadveh": 500,
    "max_trains": 500,
    "max_aircraft": 200,
    "max_ships": 300,
    "station_spread": 12,
    "max_loan": 500000
  },

  "companies": {
    "0": {
      "id": 0,
      "name": "AgentCorp",
      "is_ai": false,
      "money": 1250000,
      "loan": 300000,
      "max_loan": 500000,
      "income": 45000,
      "expenses": 32000,
      "company_value": 980000,
      "hq_x": 120, "hq_y": 85,
      "quarterly_history": [
        { "quarter": "2000-Q4", "income": 42000, "expenses": 30000, "value": 920000 }
      ],
      "vehicle_counts": { "trains": 5, "road_vehicles": 12, "ships": 0, "aircraft": 2 },
      "station_count": 8
    }
  },

  "towns": {
    "0": {
      "id": 0,
      "name": "Sindston",
      "population": 3500,
      "x": 100, "y": 80,
      "is_city": true,
      "growth_rate": 120,
      "ratings": { "0": "Good", "1": "Mediocre" }
    }
  },

  "industries": {
    "0": {
      "id": 0,
      "name": "Sindston Coal Mine",
      "type": "coal_mine",
      "x": 95, "y": 72,
      "production": { "coal": 180 },
      "transported_pct": { "coal": 72 },
      "town_id": 0
    }
  },

  "stations": {
    "company_0": [
      {
        "id": 5,
        "name": "Sindston Transfer",
        "x": 101, "y": 81,
        "company_id": 0,
        "facilities": ["bus_stop", "truck_stop"],
        "cargo_waiting": { "passengers": 45, "coal": 0 },
        "cargo_rating": { "passengers": 68 }
      }
    ]
  },

  "vehicles": {
    "company_0": [
      {
        "id": 12,
        "name": "Bus 1",
        "type": "road_vehicle",
        "engine": "Foster Bus",
        "company_id": 0,
        "x": 102, "y": 82,
        "speed": 55,
        "cargo": "passengers",
        "cargo_loaded": 20,
        "cargo_capacity": 31,
        "profit_this_year": 12000,
        "profit_last_year": 15000,
        "age_days": 365,
        "max_age_days": 5475,
        "running": true,
        "in_depot": false,
        "orders": [
          { "type": "go_to", "destination_id": 5, "flags": ["full_load"] },
          { "type": "go_to", "destination_id": 8, "flags": ["unload_all"] }
        ]
      }
    ]
  },

  "subsidies": [
    {
      "id": 0,
      "cargo": "passengers",
      "from_type": "town", "from_id": 0,
      "to_type": "town", "to_id": 3,
      "claimed": false,
      "remaining_months": 8
    }
  ],

  "events_since_last": [
    { "type": "subsidy_offer", "subsidy_id": 0, "tick": 54028800 },
    { "type": "vehicle_profit", "vehicle_id": 12, "profit": 3000, "tick": 54028850 }
  ]
}
```

### 6.4 Fetching Strategy

Three complementary data channels:

#### Channel 1: Admin Port Push Subscriptions
- **Company info** (automatic): new/removed companies, name changes
- **Company economy** (quarterly): financial snapshots with history
- **Company stats** (quarterly): vehicle/station counts by type
- **Date** (daily): game date advancement — triggers snapshot cycle
- **Chat** (automatic): player messages
- **Client info** (automatic): player join/leave events

These arrive passively — no query needed. nttd's `Bridge` class already handles these (`bridge.py:27-73`).

#### Channel 2: GS Queries (Active Polling)
Triggered by nttd on a schedule (e.g., daily or per-heartbeat):

| Query | Data | Approx Response Size |
|-------|------|---------------------|
| `get_towns` | All towns with population, coordinates | ~2-10 KB |
| `get_industries` | All industries with production | ~2-10 KB |
| `get_companies` | All companies with finances | ~1-5 KB |
| `get_company_finance` (per company) | Detailed financial breakdown | ~0.5-1 KB |
| `get_stations` (per company) | All stations with cargo | ~2-20 KB |
| `get_vehicles` (per company) | All vehicles with orders | ~5-50 KB |
| `get_subsidies` | Active subsidies | ~0.5-2 KB |
| `get_cargo_types` | Cargo definitions (static, query once) | ~1-3 KB |

**Current implementation** (`orchestrator.py:113-164`): refreshes all of the above in the `_refresh_world_from_gs()` method.

#### Channel 3: GS Event Stream
GameScript monitors events and reports them via `GSAdmin.Send()`:
- Vehicle crashed / lost
- Subsidy offered / awarded / expired
- Industry opened / closed
- Town council decisions
- Company bankruptcy

These are pushed in real-time as they occur.

### 6.5 Delta Updates

**Yes, delta updates should be implemented** to reduce bandwidth and agent context size.

#### Design

```json
{
  "meta": {
    "snapshot_id": "snap_00043",
    "delta_from": "snap_00042",
    "game_date": 730121,
    "is_delta": true
  },

  "changes": {
    "companies": {
      "0": {
        "modified": { "money": 1255000, "income": 47000 }
      }
    },
    "towns": {
      "0": {
        "modified": { "population": 3520 }
      }
    },
    "vehicles": {
      "company_0": {
        "12": {
          "modified": { "cargo_loaded": 28, "x": 105, "y": 83 }
        }
      }
    },
    "stations": {},
    "industries": {},
    "events": [
      { "type": "vehicle_profit", "vehicle_id": 12, "profit": 500, "tick": 54029000 }
    ]
  },

  "added": {},
  "removed": {}
}
```

#### Implementation Strategy

1. **Entity versioning**: each entity in `WorldState` gets a `_version` counter, incremented on any change
2. **Snapshot diff**: compare current state against previous snapshot, emit only changed fields
3. **Payload reduction**: full snapshot ~50-100 KB → delta ~2-5 KB for a stable game
4. **Client-side reconstruction**: agent maintains local state, applies deltas incrementally
5. **Full snapshot fallback**: client can request full snapshot anytime (on reconnect, on demand)
6. **Ring buffer**: nttd stores last N full snapshots (default 100) for historical queries

### 6.6 Storage Strategy

| Layer | Storage | Purpose | Retention |
|-------|---------|---------|-----------|
| Hot | In-memory `WorldState` | Current state for queries | Always |
| Warm | In-memory ring buffer (100 snapshots) | Recent history for trend analysis | Rolling |
| Cold | Disk JSONL file | Replay data, training corpus | Per game session |

**Cold storage format** (one JSON object per line):
```
{"meta":{"snapshot_id":"snap_00001","game_date":730001,...},"companies":{...},...}
{"meta":{"snapshot_id":"snap_00002","game_date":730002,...},"companies":{...},...}
```

**Agent context delivery** (`agents/base.py`):
- `compact` — LLM-friendly summary (~1-3 KB)
- `history` — last N full snapshots for temporal reasoning
- Configurable depth: 1 (latest only) to 100 (full warm buffer)

### 6.7 Deity Operations in Multiplayer

**Keep deity powers, but gate them.**

| Endpoint Group | Access | Operations |
|---------------|--------|------------|
| `/agent/actions/...` | Agent API | Build, buy, sell, orders — fair-play actions only |
| `/admin/deity/...` | Admin/scenario designer | Town manipulation, subsidy creation, free money, growth control |
| `/admin/server/...` | Admin | Pause, save, load, settings, kick, start/stop AI |

Agents competing in multiplayer should ONLY have access to `/agent/actions/`. Deity operations are for:
- Scenario setup (before game starts)
- Tutorial/training environments
- Research/debugging

This separation ensures fair competition while retaining full control for scenario designers.

---

## 7. Technical Constraints Mitigation

### 7.1 GS Message Size Limit (1450 bytes GS→Admin)

**Constraint**: `GSAdmin.Send()` is limited to ~1450 bytes per packet. Large query responses (e.g., 50 stations) cannot fit in a single message.

**Current mitigation**: Chunk protocol already implemented in `main.nut`:
- `CHUNK_SIZE = 10` items per packet
- Each chunk tagged with `_chunk` (index) and `_total` (count)
- nttd reassembles chunks using correlation IDs

**Further improvements**:
- Compress field names in GS responses (e.g., `n` instead of `name`, `x` instead of `tile_x`) — saves ~20-30% per packet
- Batch small related responses into a single packet (e.g., company finance + company info)
- Note: admin→GS direction has 9000 byte limit (`core/config.h:58`), so commands can be larger

### 7.2 GS Single-Threaded Execution

**Constraint**: Only one GS command executes at a time. All queries and actions are sequential within the GS Squirrel VM.

**Mitigation**:
1. **Minimize GS work**: move computation to nttd Python side (pathfinding, planning, analysis)
2. **Batch queries**: create a `get_full_state` mega-query that returns everything in one call (towns + industries + companies + stations + vehicles), reducing round-trip overhead
3. **Use GSAsyncMode**: for fire-and-forget actions (construction, vehicle commands) where we don't need the result immediately
4. **Pipeline commands**: send the next command while the current one is executing (admin port supports this via correlation IDs)
5. **Prioritize**: process agent actions before state queries; queries can be deferred but actions are time-sensitive

### 7.3 GSCompanyMode Sequential

**Constraint**: `GSCompanyMode` is RAII-pattern — only one company context active at a time. Switching companies requires creating a new `GSCompanyMode` object.

**Mitigation**:
1. **Sort actions by company**: pre-sort the action queue by `company_id` to minimize context switches
2. **Batch per company**: execute all actions for company 0, then switch to company 1, etc.
3. **Round-robin queries**: query company 0's stations on tick 1, company 1's on tick 2, etc.
4. **Avoid unnecessary switches**: cache company data, only query companies that have pending actions

### 7.4 GS Opcode Budget Per Tick

**Constraint**: `script_max_opcode_till_suspend` limits how many operations GS can perform per tick. Heavy queries (iterating 100+ stations) may exhaust the budget.

**Mitigation**:
1. **Increase budget**: set `script_max_opcode_till_suspend` to a higher value (default varies, can set to 100000+)
2. **Split heavy operations**: if scanning all stations, do 20 per tick, resume next tick
3. **Monitor consumption**: add opcode tracking to GS (count operations per query type)
4. **Optimize hot paths**: use efficient iteration patterns, avoid redundant lookups
5. **Adjust game speed**: slower game speed = more ticks per real second = more total opcodes available

### 7.5 No Pathfinding in GS

**Constraint**: GS API provides no built-in pathfinding. Building a road/rail route between two points requires external path computation.

**Mitigation layers**:

| Layer | Approach | Complexity | Latency |
|-------|----------|------------|---------|
| **Agent-side** | LLM or external A* computes path | High accuracy | High (LLM reasoning time) |
| **nttd Python service** | A* on cached tile data | Good accuracy | Medium (Python computation) |
| **GS heuristic** | `scan_town_area`, `find_bus_stop_spots` | Approximate | Low (in-game) |
| **GS A* (Squirrel)** | Port from openttd-mcp reference | Good accuracy | Medium (opcode-limited) |

**Recommended approach**: Implement A* in nttd Python as a pathfinding service module:
1. Cache tile data from `get_tile_info` scans at game start
2. Build a graph representation of the map (walkable tiles, terrain costs)
3. A* with terrain cost heuristics (avoid water, prefer flat, minimize bridges)
4. Return path as list of tile coordinates
5. Agent calls `/pathfind?from_x=10&from_y=20&to_x=50&to_y=60&type=road`
6. nttd executes `build_road` for each tile in the path

### 7.6 No Industry Creation via GS

**Constraint**: GS cannot create or destroy industries. Industries are placed by the map generator or prospecting mechanic.

**Mitigation**:
- Use scenario editor pre-game to place industries where needed
- Use `GSGameSettings.SetValue()` to influence map generation parameters
- Accept as a game constraint — players (human or AI) also cannot create industries
- GS CAN control industry production rates (`GSIndustry` methods) and monitor cargo flow

### 7.7 Admin Port Fire-and-Forget

**Constraint**: Messages sent via admin port have no delivery guarantee. A message could be lost if the connection drops mid-send.

**Current mitigation** (already in `admin_client.py`):
- Correlation IDs for request/response matching
- Timeout per command (default 10s)
- Auto-reconnect with exponential backoff (2s–30s)

**Further improvements**:
- **Health check ping**: periodic `ADMIN_PACKET_ADMIN_PING` / `PONG` to detect connection loss early
- **Retry with idempotency**: retry failed commands if safe (queries are always safe; mutations need idempotency keys)
- **Dead letter queue**: log failed commands for later retry or manual intervention
- **Circuit breaker**: if N consecutive commands fail, pause agent actions and alert

### 7.8 Multiplayer Global Pause

**Constraint**: Pause affects ALL connected clients. Using pause/unpause for AI synchronization disrupts human players.

**Mode-specific mitigation**:

| Runtime Mode | Strategy |
|-------------|----------|
| **Heartbeat (pure agent)** | Pause IS the sync primitive. This is fine — no humans to disrupt. |
| **Async real-time (human co-play)** | DON'T pause. Use game speed control instead. Set `game_speed = 25` to give agents 4x more real-time per game-day. |
| **Assisted (co-pilot)** | Pause only when human explicitly requests AI analysis. Brief pause acceptable as it's user-initiated. |

**For async real-time specifically**:
- Agents operate in real-time, processing snapshots as they arrive
- If agent is slow, it misses some game-days — this is acceptable
- Game speed is the tuning knob: slower = more agent thinking time, faster = more challenging

### 7.9 Full Map Scan Expensive

**Constraint**: A 256x256 map has 65,536 tiles. A 1024x1024 map has 1,048,576 tiles. Scanning all tiles via `get_tile_info` is prohibitively expensive.

**Mitigation**:
1. **Scan once at game start**: cache the full tile map in nttd (takes ~1-5 minutes for large maps, but only once)
2. **Incremental updates**: only re-scan areas where construction occurred (track via command logging)
3. **Zone-based scanning**: divide map into 16x16 sectors, scan one sector per tick
4. **Agent-scoped scanning**: only scan tiles near the agent's existing infrastructure (within N tiles of stations/routes)
5. **Lazy loading**: don't scan until an agent needs tile data for pathfinding or construction planning
6. **Cache invalidation**: when a build/demolish command succeeds, invalidate affected tiles in cache

### 7.10 Vehicle and Station Limits

**Constraint**: Default limits per company (configurable via settings):

| Limit | Default | Setting Key |
|-------|---------|-------------|
| Road vehicles | 500 | `max_roadveh` |
| Trains | 500 | `max_trains` |
| Aircraft | 200 | `max_aircraft` |
| Ships | 300 | `max_ships` |
| Station spread | 12 tiles | `station_spread` |

**Mitigation**:
- Include limits in game settings snapshot so agents can plan accordingly
- Pre-check limits before buy/build commands: `GSGameSettings.GetValue("max_trains")` vs current count
- GS can report current vehicle counts per company in state queries
- nttd can reject actions that would exceed limits (fail-fast before sending to GS)

### 7.11 Additional Constraints

#### Admin Port Max 16 Connections
- nttd needs only 1 connection for the bridge
- Reserve others for monitoring/debugging tools (Grafana adapter, log viewer, etc.)
- If multiple nttd instances needed (e.g., sharding), implement a connection proxy/multiplexer

#### No Per-Tick Admin Updates
- Finest admin push granularity is DAILY
- For sub-day resolution, use GS queries triggered by nttd timer
- For tick-level state: GS can buffer changes per tick and report on demand (custom `get_tick_events` command)

#### Save/Load Connection Behavior
- **Admin connections SURVIVE** save/load — no reconnection needed
- **Game client connections do NOT survive** — clients must rejoin
- nttd's `admin_client.py` already handles reconnection with exponential backoff as a safety net

#### GS JSON Null Terminator
- Already handled: `GameScriptPacket.json` includes `\x00` — stripped before `json.loads()` in `admin_client.py`

#### Squirrel Reserved Keywords
- Already documented: avoid `clone`, `parent`, `delete`, `in` as table keys
- Use `parent_id`/`parent_gid`, `cid`, etc.

---

## 8. Summary of Key Design Decisions

### 8.1 Architecture Answers

| Question | Answer |
|----------|--------|
| Can multiple humans share a company? | **YES** — confirmed in OpenTTD source. Multiple clients can have the same `client_playas`. |
| Can multiple LLM agents share a company? | **YES** — via nttd's `company_scope` mechanism. Actions serialized through GS. |
| Does pause work per-player? | **NO** — pause is global. Use game speed control for human co-play scenarios. |
| Can our agent do everything a human can? | **YES** — GS API covers all DoCommands. Currently 83% implemented (93/112), needs ~20 more commands for 100%. |
| Do in-game AI scripts perform actions? | **YES** — autonomously via NoAI framework (different API, same DoCommand system). |
| Why do we need the admin client? | It's the ONLY bridge between nttd and OpenTTD. Carries GS messages, state subscriptions, and rcon. |
| How should we serve game state? | JSON snapshots at configurable frequency (default daily). Delta updates for efficiency. Three storage tiers. |
| Should agents have deity powers? | **NO** — gate deity operations behind admin role. Agents use fair-play actions only. |

### 8.2 Priority Implementation Roadmap

#### Phase 1: Complete Action Parity
1. Implement 6 high-priority missing GS commands (conditional orders, terraform, tree planting, cargo monitoring, game settings, cost estimation)
2. Add 8 medium-priority commands (one-way roads, road conversion, auto-replace, nested groups, wagon manipulation, stop location, running costs, capacity)
3. Enrich existing queries with missing fields

#### Phase 2: Game State Management
1. Implement delta snapshot system
2. Add cold storage (JSONL replay files)
3. Build configurable snapshot frequency
4. Add game settings to snapshot

#### Phase 3: Multi-Agent Support
1. Verify overlapping `company_scope` works for same-company multi-agent
2. Add action queue serialization per company
3. Implement action conflict detection
4. Add agent coordination primitives (if needed)

#### Phase 4: Bottleneck Mitigation
1. Implement Python-side A* pathfinding service
2. Build tile cache with incremental updates
3. Optimize GS response format (compressed field names)
4. Add `get_full_state` mega-query for reduced round-trips
5. Implement pre-flight action validation in nttd

### 8.3 The Big Picture

```
┌─────────────────────────────────────────────────────────┐
│                    LLM Agent(s)                         │
│  Observe state → Reason → Plan → Submit actions         │
└──────────────┬──────────────────────────┬───────────────┘
               │ WebSocket (snapshots)    │ REST (actions)
               ▼                          ▼
┌─────────────────────────────────────────────────────────┐
│                      nttd Server                        │
│  ┌──────────┐  ┌──────────┐  ┌────────────────────┐    │
│  │ State    │  │ Action   │  │ Agent Registry      │    │
│  │ Manager  │  │ Queue    │  │ (company_scope,     │    │
│  │ (world,  │  │ (sorted  │  │  subscriptions)     │    │
│  │  cache,  │  │  by co.) │  │                     │    │
│  │  deltas) │  │          │  │                     │    │
│  └────┬─────┘  └────┬─────┘  └─────────────────────┘    │
│       │              │                                   │
│  ┌────▼──────────────▼──────────────────────┐           │
│  │         Admin Client (TCP 3977)           │           │
│  │  GS JSON ←→ │ State subscriptions │ rcon  │           │
│  └──────────────┬───────────────────────────┘           │
└─────────────────┼───────────────────────────────────────┘
                  │ Admin Port Protocol
                  ▼
┌─────────────────────────────────────────────────────────┐
│              OpenTTD Dedicated Server                    │
│  ┌────────────────┐  ┌──────────────────────┐           │
│  │ GameScript      │  │ Game Engine           │          │
│  │ (nttd-gs)       │  │ (DoCommand system)    │          │
│  │ 93+ commands    │  │ Same as human clicks  │          │
│  └────────────────┘  └──────────────────────┘           │
│  ┌────────────────┐  ┌──────────────────────┐           │
│  │ Built-in AI(s) │  │ Human Players         │          │
│  │ (NoAI scripts) │  │ (GUI clients)         │          │
│  │ Compete with   │  │ Compete/cooperate     │          │
│  │ our agents     │  │ with our agents       │          │
│  └────────────────┘  └──────────────────────┘           │
└─────────────────────────────────────────────────────────┘
```

All participants — human players, built-in AI, and our LLM agents — compete on the same playing field using the same DoCommand system. The difference is the intelligence driving the decisions.

---

## 9. Financial Data — Fetching and Provisioning

### 9.1 Available Financial Data Sources

OpenTTD tracks finances at multiple granularities. Here is every data point available via GS API:

#### Per-Company Balance Sheet (GSCompany)

| Method | Data | Notes |
|--------|------|-------|
| `GetBankBalance(company)` | Current cash | Real-time |
| `GetLoanAmount()` | Current loan | Inside GSCompanyMode |
| `GetMaxLoanAmount()` | Maximum borrowable | Inside GSCompanyMode |
| `GetLoanInterval()` | Loan increment step | Global setting |
| `GetQuarterlyIncome(company, quarter)` | Income for quarter 0-3 | 0 = current, 3 = oldest |
| `GetQuarterlyExpenses(company, quarter)` | Expenses for quarter 0-3 | Same indexing |
| `GetQuarterlyCargoDelivered(company, quarter)` | Cargo units delivered | Per quarter |
| `GetQuarterlyPerformanceRating(company, quarter)` | Performance score 0-1000 | Per quarter |
| `GetQuarterlyCompanyValue(company, quarter)` | Company valuation | Per quarter |

#### Expense Categories (GSCompany.ExpensesType)

OpenTTD tracks 13 expense categories:

| Enum | Category | Description |
|------|----------|-------------|
| `EXPENSES_CONSTRUCTION` | Construction | Road, rail, stations, depots |
| `EXPENSES_NEW_VEHICLES` | Vehicle purchase | Buying vehicles |
| `EXPENSES_TRAIN_RUN` | Train running costs | Fuel, maintenance |
| `EXPENSES_ROADVEH_RUN` | Road vehicle running | Fuel, maintenance |
| `EXPENSES_AIRCRAFT_RUN` | Aircraft running | Fuel, maintenance |
| `EXPENSES_SHIP_RUN` | Ship running | Fuel, maintenance |
| `EXPENSES_PROPERTY` | Property maintenance | Station/infrastructure upkeep |
| `EXPENSES_TRAIN_REVENUE` | Train income | Cargo delivery revenue |
| `EXPENSES_ROADVEH_REVENUE` | Road vehicle income | Cargo delivery revenue |
| `EXPENSES_AIRCRAFT_REVENUE` | Aircraft income | Cargo delivery revenue |
| `EXPENSES_SHIP_REVENUE` | Ship income | Cargo delivery revenue |
| `EXPENSES_LOAN_INTEREST` | Loan interest | Periodic interest payments |
| `EXPENSES_OTHER` | Other | Miscellaneous |

#### Infrastructure Costs (GSInfrastructure)

| Method | Data |
|--------|------|
| `GetMonthlyRailCosts()` | Monthly rail maintenance |
| `GetMonthlyRoadCosts()` | Monthly road maintenance |
| `GetMonthlyWaterCosts()` | Monthly canal/lock maintenance |
| `GetMonthlyStationCosts()` | Monthly station maintenance |
| `GetMonthlyAirportCosts()` | Monthly airport maintenance |
| `GetRailPieceCount()` | Total rail tile count |
| `GetRoadPieceCount()` | Total road tile count |
| `GetWaterPieceCount()` | Total water infrastructure count |
| `GetStationPieceCount()` | Total station tile count |
| `GetAirportPieceCount()` | Total airport tile count |

Note: infrastructure costs scale non-linearly — larger networks have proportionally higher costs per piece.

#### Cargo Flow Monitoring (GSCargoMonitor)

| Method | Data |
|--------|------|
| `GetTownDeliveryAmount(company, cargo, town, keep)` | Cargo delivered to town since last query |
| `GetIndustryDeliveryAmount(company, cargo, industry, keep)` | Cargo delivered to industry since last query |
| `GetTownPickupAmount(company, cargo, town, keep)` | Cargo picked up from town since last query |
| `GetIndustryPickupAmount(company, cargo, industry, keep)` | Cargo picked up from industry since last query |

These are **delta counters** — they return the amount since the last query and reset. The `keep_monitoring` parameter controls whether monitoring continues after the query.

#### Cost Estimation (GSTestMode + GSAccounting)

```squirrel
// Dry-run: estimate cost without executing
local accounting = GSAccounting();
{
    local test = GSTestMode();
    GSRoad.BuildRoad(from_tile, to_tile);  // Not actually built
}
local estimated_cost = accounting.GetCosts();
// Returns: cost in game currency, or negative if action would fail
```

### 9.2 Financial Data in the API

#### Proposed Financial Endpoints

```
GET  /state/company/{id}/finances          → Full financial breakdown
GET  /state/company/{id}/finances/history  → Quarterly history (last 4 quarters)
GET  /state/company/{id}/infrastructure    → Infrastructure costs breakdown
GET  /state/cargo/flows?company_id=N       → Cargo delivery/pickup deltas
POST /actions/estimate                     → Cost estimation (dry-run)
```

#### Financial Snapshot Structure

```json
{
  "company_id": 0,
  "balance": 1250000,
  "loan": 300000,
  "max_loan": 500000,
  "loan_interval": 10000,

  "current_quarter": {
    "income": 45000,
    "expenses": 32000,
    "cargo_delivered": 1200,
    "performance_rating": 650,
    "company_value": 980000
  },

  "quarterly_history": [
    { "quarter": -1, "income": 42000, "expenses": 30000, "cargo": 1100, "rating": 640, "value": 920000 },
    { "quarter": -2, "income": 38000, "expenses": 28000, "cargo": 950, "rating": 610, "value": 870000 },
    { "quarter": -3, "income": 35000, "expenses": 27000, "cargo": 800, "rating": 580, "value": 820000 }
  ],

  "expenses_breakdown": {
    "construction": 5000,
    "new_vehicles": 8000,
    "train_run": 3000,
    "roadveh_run": 2500,
    "aircraft_run": 1500,
    "ship_run": 0,
    "property": 4000,
    "loan_interest": 3000,
    "other": 0
  },

  "revenue_breakdown": {
    "train": 20000,
    "roadveh": 15000,
    "aircraft": 8000,
    "ship": 0
  },

  "infrastructure": {
    "rail_pieces": 450, "rail_monthly_cost": 2200,
    "road_pieces": 320, "road_monthly_cost": 800,
    "water_pieces": 0, "water_monthly_cost": 0,
    "station_pieces": 45, "station_monthly_cost": 1500,
    "airport_pieces": 12, "airport_monthly_cost": 3000
  }
}
```

### 9.3 GS Commands Needed

| Command | Status | Implementation |
|---------|--------|---------------|
| `get_company_finance` | Exists | Extend with expense categories, infrastructure |
| `get_infrastructure_costs` | New | `GSInfrastructure.GetMonthly*Costs()` per company |
| `get_cargo_flows` | New | `GSCargoMonitor.Get*Amount()` per company/cargo |
| `estimate_cost` | New | `GSTestMode` + `GSAccounting` wrapper |
| `set_loan` | Exists | Already implemented |
| `get_expense_breakdown` | New | Loop over `ExpensesType` enum |

### 9.4 Deity Financial Operations (Admin Only)

For mid-game financial modifications (admin console only, not agents):

| Operation | GS Method | Use Case |
|-----------|-----------|----------|
| Inject money | `GSCompany.ChangeBankBalance(company, delta, expenses_type)` | Scenario setup, debugging |
| Set max loan | `GSCompany.SetMaxLoanAmountForCompany(company, amount)` | Per-company loan limits |
| Set loan | `set_loan` command (already exists) | Adjust loan level |

These are gated behind `/admin/deity/` endpoints in the API.

---

## 10. Message Stream — System, Player, and Agent-to-Agent

### 10.1 OpenTTD's Built-in Messaging

OpenTTD has three messaging layers:

#### News/Events (System Messages)

GS can create news items visible to all players:

| News Type | GS Enum | Description |
|-----------|---------|-------------|
| Economy news | `GSNews.NT_ECONOMY` | Financial events |
| Subsidy news | `GSNews.NT_SUBSIDIES` | Subsidy offers/awards |
| General news | `GSNews.NT_GENERAL` | Custom GS announcements |

Each news item can reference a game object (tile, station, industry, town) so the player can click to navigate.

#### Chat Messages (Multiplayer)

OpenTTD multiplayer has built-in chat with three scopes:
- **All**: visible to everyone (`DESTTYPE_BROADCAST`)
- **Team**: visible to same company only (`DESTTYPE_TEAM`)
- **Client**: private to a specific client (`DESTTYPE_CLIENT`)

Admin port can:
- **Receive** all chat messages via `ADMIN_UPDATE_CHAT` subscription
- **Send** chat as the server via `ADMIN_PACKET_ADMIN_CHAT`
- **Send external chat** via `ADMIN_PACKET_ADMIN_EXTERNAL_CHAT` (appears as external source)

#### Console Output

Server console messages (joins, leaves, rcon output) are available via `ADMIN_UPDATE_CONSOLE` subscription.

### 10.2 Agent-to-Agent Messaging Design

We can build agent-to-agent messaging on top of these primitives:

#### Architecture

```
Agent A                    nttd Server                    Agent B
   │                          │                              │
   │  POST /messages/send     │                              │
   │  { to: "agent_b",       │                              │
   │    body: "..." }        │                              │
   │─────────────────────────>│                              │
   │                          │  Store in message queue      │
   │                          │  Push via WebSocket          │
   │                          │─────────────────────────────>│
   │                          │                              │
   │                          │  Optional: relay via         │
   │                          │  OpenTTD team chat           │
   │                          │  (visible in-game)           │
```

#### Message Types

| Type | Scope | Delivery | Use Case |
|------|-------|----------|----------|
| `agent_direct` | Agent → Agent | nttd WebSocket | Coordination between agents sharing a company |
| `agent_broadcast` | Agent → All agents | nttd WebSocket | General announcements |
| `team_chat` | Agent → Same company | OpenTTD team chat + nttd | Visible to humans in same company |
| `public_chat` | Agent → All | OpenTTD broadcast chat + nttd | Visible to all players |
| `system` | nttd → All agents | nttd WebSocket | Game events, state changes, warnings |

#### Proposed Message Endpoints

```
POST /messages/send              → Send a message
GET  /messages/inbox/{agent_id}  → Poll messages (fallback)
WS   /ws/{agent_id}              → Real-time push (extend existing WebSocket)
GET  /messages/history?session_id=...&limit=100  → Message log
```

#### Message Schema

```json
{
  "message_id": "msg_abc123",
  "timestamp": "2025-03-15T14:30:00Z",
  "game_date": 730120,
  "type": "agent_direct",
  "from": "agent_a",
  "to": "agent_b",
  "company_id": 0,
  "body": "I'm building a train route to Sindston. Can you handle bus feeder services?",
  "metadata": {}
}
```

#### System Message Events

nttd should auto-generate system messages for:
- Vehicle crashed / lost
- Company bankruptcy
- Subsidy offered / awarded / expired
- Industry opened / closed
- New company joined
- Player connected / disconnected
- Game saved / loaded
- End condition approaching (warning)

These flow through the same message stream so agents can react to them.

### 10.3 Message Persistence

All messages are persisted to the session database (see Section 13) for:
- Replay analysis (what did agents communicate?)
- Debugging agent coordination
- Admin console message viewer
- Training data for future agent improvements

---

## 11. Admin Console / Dashboard

> **Primary focus**: Async real-time multiplayer where humans and/or LLM agents play together, managed via this console.

### 11.1 Overview

The Admin Console is a web-based dashboard for managing OpenTTD multiplayer sessions with LLM agents. It is the **control plane** for nttd — everything an administrator needs to set up, monitor, and manage games.

```
┌─────────────────────────────────────────────────────────────────┐
│                     Admin Console (React)                        │
│                                                                  │
│  ┌─────────────┐ ┌──────────────┐ ┌──────────────┐ ┌─────────┐│
│  │ Session     │ │ Players &    │ │ Metrics &    │ │ Leader- ││
│  │ Management  │ │ Agents       │ │ Timeline     │ │ board   ││
│  │ (Page 1)   │ │ (Page 2)     │ │ (Page 3)     │ │ (Page 4)││
│  └──────┬──────┘ └──────┬───────┘ └──────┬───────┘ └────┬────┘│
│         └────────────────┼───────────────┼───────────────┘     │
│                          │               │                      │
│                    REST API + WebSocket                          │
└──────────────────────────┼───────────────┼──────────────────────┘
                           │               │
                    ┌──────▼───────────────▼──────┐
                    │        nttd Server          │
                    │   (FastAPI + SQLite DB)     │
                    └─────────────┬───────────────┘
                                  │
                           Admin Port (3977)
                                  │
                    ┌─────────────▼───────────────┐
                    │    OpenTTD Dedicated Server  │
                    └─────────────────────────────┘
```

### 11.2 Page 1: Session Management

#### Session Creation (New Game)

The admin configures and starts a new multiplayer game session. All settings are sent to OpenTTD before starting.

**Map Settings** (via rcon `setting` or scenario config):

| Setting | Key | Values | Default |
|---------|-----|--------|---------|
| Map size X | `map_x` | 6-12 (64-4096 tiles, power of 2) | 8 (256) |
| Map size Y | `map_y` | 6-12 (64-4096 tiles, power of 2) | 8 (256) |
| Landscape | `landscape` | temperate, arctic, tropical, toyland | temperate |
| Terrain type | `terrain_type` | very_flat, flat, hilly, mountainous | flat |
| Sea level | `quantity_sea_lakes` | very_low, low, medium, high, custom | low |
| Variety distribution | `variety` | none, low, medium, high, custom | none |
| Map seed | `generation_seed` | 0-4294967295 | random |
| Starting year | `starting_year` | 0-5000000 | 1950 |
| Snow line height | `snow_line_height` | 2-13 (arctic only) | 7 |

**Town Settings**:

| Setting | Key | Values | Default |
|---------|-----|--------|---------|
| Number of towns | `number_towns` | none, very_low, low, normal, high, custom | normal |
| Number of cities | `larger_towns` | 0, 1 in 2, 1 in 3, 1 in 4 | 1 in 4 |
| City size multiplier | `initial_city_size` | 1-5 | 2 |
| Town layout | `town_layout` | original, better_roads, 2x2_grid, 3x3_grid, random | original |
| Town growth speed | `town_growth_rate` | none, slow, normal, fast, very_fast | normal |
| Town council tolerance | `town_council_tolerance` | permissive, tolerant, hostile | permissive |

**Industry Settings**:

| Setting | Key | Values | Default |
|---------|-----|--------|---------|
| Number of industries | `number_industries` | none, very_low, low, normal, high | normal |
| Industry density | `industry_density` | funding_only, minimal, very_low, low, normal, high | normal |
| Economy type | `economy` | original, smooth | smooth |
| Allow multiple same industries per town | `multiple_industry_per_town` | true/false | false |

**Financial Settings**:

| Setting | Key | Values | Default |
|---------|-----|--------|---------|
| Initial loan | `max_loan` | £100K - £2M | £300K |
| Interest rate | `interest_rate` | 2-4% | 2% |
| Inflation | `inflation` | true/false | false |
| Infrastructure maintenance | `infrastructure_maintenance` | true/false | true |
| Build while paused | `build_on_slopes` | true/false | true |

**Vehicle Limits** (per company):

| Setting | Key | Range | Default |
|---------|-----|-------|---------|
| Max trains | `max_trains` | 0-5000 | 500 |
| Max road vehicles | `max_roadveh` | 0-5000 | 500 |
| Max aircraft | `max_aircraft` | 0-5000 | 200 |
| Max ships | `max_ships` | 0-5000 | 300 |

**Network/Multiplayer Settings**:

| Setting | Key | Values | Default |
|---------|-----|--------|---------|
| Server name | `server_name` | string | "nttd session" |
| Max companies | `max_companies` | 1-15 | 15 |
| Max clients | `max_clients` | 2-255 | 25 |
| Game speed | `game_speed` | 1-10000 (percent) | 100 |
| Pause on join | `pause_on_join` | true/false | false |
| Min active clients | `min_active_clients` | 0-255 | 0 |
| Autoclean companies | `autoclean_companies` | true/false | false |

**Difficulty Settings**:

| Setting | Key | Values | Default |
|---------|-----|--------|---------|
| Competitor speed | `competitor_speed` | very_slow, slow, medium, fast, very_fast | medium |
| Number of AI opponents | `max_no_competitors` | 0-14 | 0 |
| AI in multiplayer | `ai_in_multiplayer` | true/false | true |
| Station spread | `station_spread` | 4-64 tiles | 12 |
| Disasters | `disasters` | true/false | false |
| Vehicle breakdowns | `vehicle_breakdowns` | none, reduced, normal | none |
| Subsidy multiplier | `subsidy_multiplier` | 1.5x, 2x, 3x, 4x | 3x |

**Signal & Rail Settings**:

| Setting | Key | Values | Default |
|---------|-----|--------|---------|
| Default signal type | `default_signal_type` | normal, entry, exit, combo, path, one_way_path | path |
| Train reversing | `train_acceleration_model` | original, realistic | realistic |
| Forbid 90-degree turns | `forbid_90_deg` | true/false | true |

#### Session Actions

| Action | API Call | Description |
|--------|---------|-------------|
| Create new game | `POST /session/new` → rcon `newgame` | Generate new map with settings |
| Load saved game | `POST /session/load` → rcon `load` | Resume from savefile |
| Save current game | `POST /session/save` → rcon `save` | Create savefile |
| Pause / Unpause | `POST /session/pause` / `unpause` | Global pause control |
| Set game speed | `POST /session/speed` | Adjust real-time speed |
| Stop session | `POST /session/stop` | Shutdown game |

#### Session Presets

The admin can save and load session configurations as presets (HOCON/JSON files):
```json
{
  "name": "4-Agent Competition",
  "description": "4 LLM agents compete on temperate 512x512",
  "map": { "size_x": 9, "size_y": 9, "landscape": "temperate", "terrain_type": "hilly" },
  "companies": { "max_companies": 4 },
  "vehicles": { "max_trains": 200, "max_roadveh": 200 },
  "economy": { "inflation": false, "infrastructure_maintenance": true },
  "game_speed": 50,
  "ai_opponents": 0
}
```

### 11.3 Page 2: Players and Agents

#### Connection Limits

| Resource | Hard Limit | Configurable | Notes |
|----------|-----------|--------------|-------|
| Companies | 15 max | `max_companies` (1-15) | Each needs at least one client |
| Clients (game port) | 255 max | `max_clients` (2-255) | Humans connecting via OpenTTD client |
| Admin connections | 16 max | Not configurable | nttd uses 1; 15 available for tools |
| Agents via nttd | Limited by nttd server capacity | No hard limit | Each agent = 1 WebSocket + HTTP calls |

**How many humans can share a company?** Theoretically up to `max_clients` humans can all join the same company. The practical limit is coordination — with >3-4 people issuing commands simultaneously, conflicts become frequent. The same applies to LLM agents.

**Factors affecting connection capacity:**
- Network bandwidth (each client syncs game state)
- Server CPU (more clients = more commands per tick)
- GS opcode budget (more companies = more queries per cycle)
- nttd server memory (each agent snapshot ~50-100 KB)

#### Agent Management Panel

| Feature | Action | API |
|---------|--------|-----|
| View connected agents | List all | `GET /agents/list` |
| Connect new agent | Register + assign company | `POST /agents/connect` |
| Disconnect agent | Remove | `POST /agents/{id}/disconnect` |
| Assign to company | Set company_scope | Update agent registration |
| View agent actions | Recent history | `GET /actions/recent?agent_id=X` |
| View agent state | Current context | `GET /state/compact?company_id=N` |

**Agent connection modes:**
1. **From admin console**: Admin clicks "Add Agent", selects agent type (scripted, LangChain, LangGraph, custom), configures company scope, and launches
2. **Self-registration**: Agent connects to nttd API with authentication token, registers itself with `POST /agents/connect`. The admin console shows it in the connected list.

**Authentication**: Agents include an API key in their request headers. The admin console generates and manages API keys per agent.

#### Human Player Management

| Feature | Action | API |
|---------|--------|-----|
| View connected players | List clients | `GET /session/clients` (via rcon `clients`) |
| Move player to company | Reassign | `POST /session/rcon` → `move <client_id> <company_id>` |
| Kick player | Remove | `POST /session/rcon` → `kick <client_id>` |
| Ban player | Block | `POST /session/rcon` → `ban <client_id>` |

**How humans connect:**
1. Launch OpenTTD client
2. Go to Multiplayer → Add Server → enter `server_ip:3979`
3. Join a company (or create new) with company password if set
4. Play normally — their actions appear in the admin console alongside agent actions

#### Spectator Management

| Feature | Action | Notes |
|---------|--------|-------|
| View spectators | List clients with `COMPANY_SPECTATOR` | Filter from client list |
| Limit spectators | Use `max_clients` setting | Shared limit with players |
| Move to spectator | rcon `move <client_id> 255` | 255 = COMPANY_SPECTATOR |

**How spectators connect:**
1. **Via OpenTTD client**: Join server → choose "Spectate" instead of joining a company
2. **Via admin console**: Admin can move any player to spectator mode
3. Spectators see the full game but cannot issue any commands

### 11.4 Page 3: Metrics and Timeline (see Section 12)

### 11.5 Page 4: Leaderboard (see Section 16)

### 11.6 Admin Console — Additional Features

#### Real-time Game Event Feed

A live scrolling log showing:
- Agent actions (build, buy, sell) with success/fail status
- Human player actions (from `CMD_LOGGING` subscription)
- Chat messages (from `CHAT` subscription)
- System events (company created, vehicle crashed, subsidy offered)
- Connection events (agent/player join/leave)

Each entry is timestamped with both real time and game date.

#### Message Center

Admin can:
- View all chat messages (public, team, private)
- Send server messages (broadcast to all players)
- View agent-to-agent messages
- Filter by company, agent, or message type

#### Deity Operations Panel (Admin Only)

| Operation | Description | API |
|-----------|-------------|-----|
| Change company balance | Add/remove money | `POST /admin/deity/change_balance` |
| Set max loan | Per-company loan limit | `POST /admin/deity/set_max_loan` |
| Found town | Create new town | `POST /admin/deity/found_town` |
| Expand town | Grow town instantly | `POST /admin/deity/expand_town` |
| Set town growth | Control growth rate | `POST /admin/deity/set_town_growth` |
| Create subsidy | Offer new subsidy | `POST /admin/deity/create_subsidy` |
| Change town rating | Modify company's town rating | `POST /admin/deity/change_town_rating` |
| Modify game settings | Runtime setting changes | `POST /admin/deity/set_setting` |

---

## 12. Game Metrics, Visualization, and Replay

### 12.1 Metrics Categories

Every metric should be tracked per-company and globally, at every snapshot interval.

#### Financial Metrics (per company)

| Metric | Source | Frequency |
|--------|--------|-----------|
| Cash balance | `GSCompany.GetBankBalance()` | Per snapshot |
| Loan amount | `GSCompany.GetLoanAmount()` | Per snapshot |
| Income (quarterly) | `GSCompany.GetQuarterlyIncome()` | Quarterly |
| Expenses (quarterly) | `GSCompany.GetQuarterlyExpenses()` | Quarterly |
| Company value | `GSCompany.GetQuarterlyCompanyValue()` | Quarterly |
| Performance rating | `GSCompany.GetQuarterlyPerformanceRating()` | Quarterly |
| Infrastructure costs | `GSInfrastructure.GetMonthly*Costs()` | Per snapshot |
| Revenue by vehicle type | Expense category breakdown | Per snapshot |

#### Operational Metrics (per company)

| Metric | Source | Frequency |
|--------|--------|-----------|
| Vehicle count by type | `get_vehicles` query | Per snapshot |
| Station count | `get_stations` query | Per snapshot |
| Cargo delivered (units) | `GSCompany.GetQuarterlyCargoDelivered()` | Quarterly |
| Cargo waiting (total) | Sum of station cargo | Per snapshot |
| Route count | Derived from vehicle orders | Per snapshot |
| Average vehicle profit | Computed from vehicle list | Per snapshot |
| Vehicles in depot | Count from vehicle list | Per snapshot |
| Vehicle age distribution | From vehicle list | Per snapshot |

#### World Metrics (global)

| Metric | Source | Frequency |
|--------|--------|-----------|
| Total population | Sum of town populations | Per snapshot |
| Town growth rates | From town list | Per snapshot |
| Industry production | From industry list | Per snapshot |
| Transport coverage % | Produced vs transported | Per snapshot |
| Active subsidies | From subsidy list | Per snapshot |
| Total companies | Company roster | Per snapshot |

#### Agent-Specific Metrics

| Metric | Source | Frequency |
|--------|--------|-----------|
| Actions submitted | Action tracker | Per action |
| Action success rate | Action tracker | Rolling window |
| Action latency (ms) | Timestamp diff | Per action |
| Response time (decision time) | Agent → action submission | Per snapshot cycle |
| Commands per snapshot cycle | Count | Per cycle |
| Errors encountered | Action failures | Per action |

### 12.2 Time-Series Data Pipeline

```
OpenTTD                     nttd Server                      Database
   │                           │                                │
   │  Admin push updates       │                                │
   │──────────────────────────>│  Bridge processes              │
   │                           │                                │
   │  GS query responses       │                                │
   │──────────────────────────>│  WorldState updated            │
   │                           │                                │
   │                           │  Snapshot created              │
   │                           │─────────────────────────────>  │
   │                           │  INSERT INTO snapshots         │
   │                           │  INSERT INTO metrics           │
   │                           │  INSERT INTO events            │
   │                           │                                │
   │                           │  WebSocket push to             │
   │                           │  Admin Console + Agents        │
   │                           │                                │
                               │  Admin Console queries         │
                               │<─────────────────────────────  │
                               │  GET /metrics/timeseries       │
                               │  ?metric=balance               │
                               │  &company_id=0                 │
                               │  &from=730000&to=730365        │
```

### 12.3 Metrics API Endpoints

```
GET /metrics/timeseries
    ?metric=balance|income|expenses|value|vehicles|stations|cargo|rating|population
    &company_id=0,1,2          (optional, all if omitted)
    &from_date=730000          (game date start)
    &to_date=730365            (game date end)
    &resolution=daily|weekly|monthly|quarterly
    → Returns: [{ "game_date": 730001, "value": 125000 }, ...]

GET /metrics/latest
    → Returns: current values of all metrics for all companies

GET /metrics/comparison
    ?metric=balance
    &game_date=730120
    → Returns: { "company_0": 125000, "company_1": 98000, ... }

GET /metrics/agent/{agent_id}/performance
    → Returns: action counts, success rates, response times

GET /metrics/session/summary
    → Returns: game duration, total actions, per-company rankings
```

### 12.4 Visualization in Admin Console (Page 3)

#### Dashboard Layout

```
┌─────────────────────────────────────────────────────────────┐
│  Game: Day 120, Year 1951  │  Speed: 50%  │  ▶ Playing     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Company Balance Over Time (line chart)               │   │
│  │  — Company 0 (blue)  — Company 1 (red)               │   │
│  │  ═══════════════════════════════════════              │   │
│  │  Y: £0 ... £500K    X: Day 1 ... Day 120             │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  ┌────────────────────┐  ┌───────────────────────────────┐  │
│  │ Vehicle Counts     │  │ Revenue by Type (stacked bar) │  │
│  │ (bar chart)        │  │ Train | Road | Air | Ship     │  │
│  └────────────────────┘  └───────────────────────────────┘  │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Timeline Scrubber                                    │   │
│  │  |====●========================|                      │   │
│  │  Day 1            Day 60          Day 120             │   │
│  │                                                       │   │
│  │  Events: ▲ Vehicle crashed  ★ Subsidy offered         │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  Filters: [Company ▼] [Metric ▼] [Resolution ▼] [Apply]    │
└─────────────────────────────────────────────────────────────┘
```

#### Timeline Scrubber

The timeline scrubber allows the admin to:
- **Scrub through game history** by dragging the slider to any game date
- **See event markers** (crashes, subsidies, bankruptcies) as clickable points
- **Compare snapshots** at two different points in time
- **Filter by company, metric type, or event type**
- **Zoom in/out** on time ranges (day, week, month, quarter, year)
- **Export data** as CSV for external analysis

#### Chart Types

| Chart | Metrics | Interaction |
|-------|---------|-------------|
| Line chart | Balance, income, value, population over time | Hover for values, click for details |
| Stacked bar | Revenue by vehicle type per company | Toggle categories |
| Pie chart | Expense breakdown for selected company | Click slice for drill-down |
| Heatmap | Station cargo ratings across all stations | Color = rating % |
| Bar chart | Vehicle counts by type per company | Side-by-side comparison |
| Scatter | Vehicle profit vs age | Identify underperformers |

### 12.5 Game Session Replay

#### Recording

Every game session automatically records:
1. **Snapshots** — full state at every snapshot interval (stored in DB)
2. **Actions** — every command from every agent/player with timestamps
3. **Events** — every game event (crashes, subsidies, bankruptcies)
4. **Messages** — all chat and agent-to-agent messages

#### Replay Mode

```
GET /replay/sessions                     → List all recorded sessions
GET /replay/sessions/{id}                → Session metadata
GET /replay/sessions/{id}/snapshots      → All snapshots for scrubbing
GET /replay/sessions/{id}/actions        → All actions with timestamps
GET /replay/sessions/{id}/events         → All events
GET /replay/sessions/{id}/export         → Full session export (JSON/ZIP)
```

The admin console's timeline scrubber works in replay mode exactly like live mode — the data comes from the database instead of live queries.

#### Export Format

```json
{
  "session": {
    "id": "sess_abc123",
    "name": "4-Agent Competition",
    "started_at": "2025-03-15T10:00:00Z",
    "ended_at": "2025-03-15T14:30:00Z",
    "game_start_date": 730000,
    "game_end_date": 730365,
    "settings": { ... },
    "participants": [
      { "type": "agent", "id": "agent_a", "company_id": 0, "name": "GPT-Agent" },
      { "type": "human", "id": "client_5", "company_id": 1, "name": "Player1" }
    ]
  },
  "snapshots": [ ... ],
  "actions": [ ... ],
  "events": [ ... ],
  "messages": [ ... ]
}
```

---

## 13. Data Persistence — Local Database Design

### 13.1 Why a Database?

Currently nttd stores everything in-memory (`WorldState`, `ActionTracker`, `EventLogger` JSONL). This is insufficient for:
- Time-series metrics queries with filtering
- Game session replay
- Leaderboard across multiple sessions
- Surviving server restarts
- Admin console dashboard queries

### 13.2 Technology: SQLite → PostgreSQL Migration Path

**Start with SQLite** because:
- Zero infrastructure (single file, no server process)
- Python stdlib `sqlite3` or `aiosqlite` for async
- Good enough for single-server nttd deployments
- JSON column support via `json_extract()`

**Migration to PostgreSQL** when needed for:
- Multiple nttd instances (shared DB)
- Heavy concurrent read/write (multiple dashboards)
- Advanced time-series queries (TimescaleDB extension)
- Production deployment

**Abstraction layer**: Use SQLAlchemy Core (not ORM) for both backends. Same query syntax, swap connection string.

### 13.3 Schema Design

```sql
-- Sessions table: one row per game session
CREATE TABLE sessions (
    id              TEXT PRIMARY KEY,        -- "sess_abc123"
    name            TEXT NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at        TIMESTAMP,
    status          TEXT DEFAULT 'active',   -- active, completed, aborted
    game_start_date INTEGER,                 -- OpenTTD date int
    game_end_date   INTEGER,
    settings_json   TEXT,                    -- Full session config as JSON
    end_reason      TEXT                     -- "time_limit", "manual", etc.
);

-- Participants: agents and humans in a session
CREATE TABLE participants (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT REFERENCES sessions(id),
    participant_type TEXT NOT NULL,           -- "agent", "human", "ai_builtin"
    participant_id  TEXT NOT NULL,            -- agent_id or client_id
    name            TEXT,
    company_id      INTEGER,
    joined_at       TIMESTAMP,
    left_at         TIMESTAMP,
    config_json     TEXT,                    -- Agent config, model name, etc.
    UNIQUE(session_id, participant_id)
);

-- Snapshots: full game state at each interval
CREATE TABLE snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT REFERENCES sessions(id),
    snapshot_id     TEXT NOT NULL,            -- "snap_00042"
    game_date       INTEGER NOT NULL,
    tick            INTEGER,
    captured_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    state_json      TEXT NOT NULL             -- Full StateSnapshot as JSON
);
CREATE INDEX idx_snapshots_session_date ON snapshots(session_id, game_date);

-- Metrics: time-series data points (denormalized for fast queries)
CREATE TABLE metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT REFERENCES sessions(id),
    game_date       INTEGER NOT NULL,
    company_id      INTEGER,                 -- NULL for global metrics
    metric_name     TEXT NOT NULL,            -- "balance", "income", "vehicles", etc.
    metric_value    REAL NOT NULL,
    captured_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_metrics_query ON metrics(session_id, metric_name, company_id, game_date);

-- Actions: every command from every participant
CREATE TABLE actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT REFERENCES sessions(id),
    action_id       TEXT NOT NULL,            -- "hb_abc123" or "rt_abc123"
    participant_id  TEXT,                     -- Who issued it
    company_id      INTEGER,
    game_date       INTEGER,
    action_type     TEXT NOT NULL,            -- "build_road", "buy_vehicle", etc.
    parameters_json TEXT,
    status          TEXT NOT NULL,            -- "success", "failed", "rejected"
    error           TEXT,
    result_json     TEXT,
    submitted_at    TIMESTAMP,
    completed_at    TIMESTAMP
);
CREATE INDEX idx_actions_session ON actions(session_id, game_date);
CREATE INDEX idx_actions_participant ON actions(session_id, participant_id);

-- Events: game events (crashes, subsidies, bankruptcies, etc.)
CREATE TABLE events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT REFERENCES sessions(id),
    game_date       INTEGER NOT NULL,
    tick            INTEGER,
    event_type      TEXT NOT NULL,            -- "vehicle_crashed", "subsidy_offered", etc.
    company_id      INTEGER,                 -- NULL for global events
    data_json       TEXT,
    captured_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_events_session ON events(session_id, game_date);

-- Messages: chat and agent-to-agent messages
CREATE TABLE messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT REFERENCES sessions(id),
    message_id      TEXT NOT NULL,
    game_date       INTEGER,
    message_type    TEXT NOT NULL,            -- "agent_direct", "team_chat", "system", etc.
    from_id         TEXT,
    to_id           TEXT,                    -- NULL for broadcasts
    company_id      INTEGER,
    body            TEXT,
    metadata_json   TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_messages_session ON messages(session_id, game_date);

-- Leaderboard: aggregated per-session per-company results
CREATE TABLE leaderboard (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT REFERENCES sessions(id),
    company_id      INTEGER NOT NULL,
    participant_id  TEXT,
    participant_type TEXT,
    final_balance   REAL,
    final_value     REAL,
    final_rating    REAL,
    total_cargo     INTEGER,
    total_vehicles  INTEGER,
    total_stations  INTEGER,
    total_actions   INTEGER,
    action_success_rate REAL,
    game_days_played INTEGER,
    rank            INTEGER,
    computed_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, company_id)
);
```

### 13.4 Data Ingestion Pipeline

```python
class SessionRecorder:
    """Writes game data to SQLite during active session."""

    def __init__(self, db_path: str, session_id: str):
        self.db = aiosqlite.connect(db_path)
        self.session_id = session_id
        self._write_queue: asyncio.Queue = asyncio.Queue()
        self._batch_size = 50  # Batch inserts for performance

    async def record_snapshot(self, snapshot: StateSnapshot):
        """Called every snapshot interval."""
        # Insert full snapshot
        await self._insert("snapshots", ...)
        # Extract and insert individual metrics
        for company in snapshot.companies:
            await self._insert_metric("balance", company.id, company.money)
            await self._insert_metric("income", company.id, company.income)
            await self._insert_metric("value", company.id, company.value)
            await self._insert_metric("vehicles", company.id, len(vehicles))
            # ... more metrics

    async def record_action(self, envelope: ActionEnvelope, result: ActionResult):
        """Called after every action execution."""
        await self._insert("actions", ...)

    async def record_event(self, event_type: str, data: dict):
        """Called for every game event."""
        await self._insert("events", ...)

    async def record_message(self, message: dict):
        """Called for every message."""
        await self._insert("messages", ...)

    async def _flush_batch(self):
        """Batch INSERT for performance."""
        # Collect up to batch_size items, executemany()
```

### 13.5 Storage Estimates

| Data Type | Per Snapshot | Per Day (normal speed) | Per Game-Year |
|-----------|-------------|----------------------|---------------|
| Snapshot JSON | ~50-100 KB | ~50-100 KB | ~18-36 MB |
| Metrics rows | ~20-50 rows | ~20-50 rows | ~7-18K rows |
| Action rows | ~5-20 rows | ~5-20 rows | ~2-7K rows |
| Events | ~2-10 rows | ~2-10 rows | ~700-3600 rows |

**Estimated DB size per game-year**: ~50-100 MB (mostly snapshot JSON).

**Optimization**: Store snapshots as compressed blobs (gzip, ~5-10x reduction). Only decompress on read.

---

## 14. Pathfinding Algorithm Design

### 14.1 Transport Type Requirements

| Transport | Pathfinding Needed | Complexity |
|-----------|-------------------|------------|
| Road | A* on road-buildable tiles | Medium — slopes, bridges, tunnels |
| Rail | A* with trackdir states | High — directions, signals, junctions |
| Water | A* on water tiles + canals | Medium — locks, aqueducts |
| Air | No pathfinding | None — point-to-point between airports |

### 14.2 Architecture: Python-side Pathfinding Service

```
Agent                    nttd Server                       GS
  │                         │                               │
  │ POST /pathfind          │                               │
  │ { from, to, type }     │                               │
  │────────────────────────>│                               │
  │                         │  Check tile cache             │
  │                         │  If miss: query GS            │
  │                         │──────────────────────────────>│
  │                         │  get_tile_info (batch)        │
  │                         │<──────────────────────────────│
  │                         │  Update tile cache            │
  │                         │                               │
  │                         │  Run A* on cached graph       │
  │                         │                               │
  │ { path: [...tiles],    │                               │
  │   cost: 15000,         │                               │
  │   bridges: [...],      │                               │
  │   tunnels: [...] }     │                               │
  │<────────────────────────│                               │
  │                         │                               │
  │ POST /actions/submit    │                               │
  │ (build_road per tile)  │                               │
  │────────────────────────>│  Execute via GS               │
```

### 14.3 Tile Cache

```python
class TileCache:
    """In-memory cache of map tile data for pathfinding."""

    def __init__(self, map_width: int, map_height: int):
        # 2D array: tiles[x][y] = TileData
        self.tiles: list[list[TileData | None]] = [[None] * map_height for _ in range(map_width)]
        self.version: int = 0

    @dataclass
    class TileData:
        tile_type: str      # "ground", "water", "road", "rail", "station", "industry", "town"
        height: int         # 0-15
        slope: int          # slope flags
        owner: int          # company ID or -1
        buildable: bool     # can build on this tile
        has_road: bool
        has_rail: bool
        road_type: int
        rail_type: int
        is_bridge_head: bool
        is_tunnel_head: bool
        water_class: str    # "none", "sea", "canal", "river"

    async def load_full(self, gs_client, batch_size=100):
        """Scan entire map in batches via GS get_tile_info."""
        for x in range(0, self.map_width, batch_size):
            for y in range(0, self.map_height, batch_size):
                area = await gs_client.send_gamescript("get_tile_area", {
                    "x1": x, "y1": y,
                    "x2": min(x + batch_size, self.map_width),
                    "y2": min(y + batch_size, self.map_height)
                })
                self._apply(area)

    def invalidate_area(self, x1, y1, x2, y2):
        """Mark tiles as stale after construction."""
        for x in range(x1, x2):
            for y in range(y1, y2):
                self.tiles[x][y] = None
```

### 14.4 A* Implementation

#### Cost Model (aligned with YAPF)

Using YAPF's cost ratios normalized to integer costs:

| Factor | Road Cost | Rail Cost | Water Cost | Notes |
|--------|-----------|-----------|------------|-------|
| Flat tile (diagonal) | 100 | 100 | 100 | Base cost |
| Flat tile (non-diagonal) | 71 | 71 | 71 | √2 ratio |
| 45-degree curve | 100 | 100 | 100 | Turn penalty |
| 90-degree curve | 300 | 600 | 600 | Sharper turn |
| Uphill slope | 200 | 200 | N/A | Height change |
| Bridge (per tile) | 150 | 150 | 150 | Bridge premium |
| Tunnel (per tile) | 120 | 120 | N/A | Tunnel premium |
| Level crossing | 300 | 300 | N/A | Road/rail intersection |
| Demolish existing | 500 | 500 | 500 | Clearing a tile |

#### Bridge/Tunnel Handling

The pathfinder must consider bridges and tunnels as options:

```python
def get_neighbors(self, node: PathNode) -> list[PathNode]:
    neighbors = []

    # Standard 4-directional movement
    for dx, dy in [(0,1), (0,-1), (1,0), (-1,0)]:
        nx, ny = node.x + dx, node.y + dy
        if self.is_buildable(nx, ny, transport_type):
            neighbors.append(PathNode(nx, ny, cost=self.tile_cost(nx, ny)))

    # Bridge option: if facing water or valley
    if self.can_bridge_from(node.x, node.y, direction):
        bridge_end = self.find_bridge_end(node.x, node.y, direction)
        if bridge_end:
            bx, by, length = bridge_end
            cost = length * 150 + self.bridge_construction_cost(length)
            neighbors.append(PathNode(bx, by, cost=cost, is_bridge=True))

    # Tunnel option: if facing a hill
    if self.can_tunnel_from(node.x, node.y, direction):
        tunnel_end = self.find_tunnel_end(node.x, node.y, direction)
        if tunnel_end:
            tx, ty, length = tunnel_end
            cost = length * 120 + self.tunnel_construction_cost(length)
            neighbors.append(PathNode(tx, ty, cost=cost, is_tunnel=True))

    return neighbors
```

#### Direction-Aware Pathfinding (Rail)

Rail requires tracking direction because trains can't make arbitrary turns:

```python
@dataclass
class RailPathNode:
    x: int
    y: int
    direction: int  # 0=NE, 1=SE, 2=SW, 3=NW (entry direction)

    @property
    def state_key(self) -> int:
        """Pack into single int for hash map: (x << 14) | (y << 2) | dir"""
        return (self.x << 14) | (self.y << 2) | self.direction
```

For road pathfinding, direction is less important (vehicles can turn freely), so a simpler `(x, y)` state suffices.

#### Heuristic Function

Octile distance (admissible for grid with diagonal movement):

```python
def heuristic(self, x1: int, y1: int, x2: int, y2: int) -> int:
    dx = abs(x1 - x2)
    dy = abs(y1 - y2)
    d_min = min(dx, dy)
    d_max = max(dx, dy)
    return d_min * 71 + (d_max - d_min) * 50  # diagonal + straight
```

### 14.5 Water Pathfinding

Water pathfinding has unique considerations:

1. **Ships travel on existing water** — no construction needed on sea/river tiles
2. **Canals/locks/aqueducts** must be built for connecting disconnected water bodies
3. **Hierarchical approach** (like YAPF): coarse region-level routing, then fine tile-level

```python
class WaterPathfinder:
    def find_route(self, from_tile, to_tile):
        # Phase 1: Check if connected via existing water
        if self.water_region_connected(from_tile, to_tile):
            return self.find_water_path(from_tile, to_tile)  # Simple A* on water tiles

        # Phase 2: Find shortest canal to connect water bodies
        # A* where buildable land tiles are valid but expensive
        return self.find_canal_path(from_tile, to_tile)
```

### 14.6 Air Routes

No pathfinding needed. Aircraft fly point-to-point:

```python
def plan_air_route(from_airport_id, to_airport_id):
    # Just validate airports exist and can handle the aircraft type
    return {
        "from": from_airport_id,
        "to": to_airport_id,
        "distance": manhattan_distance(from_tile, to_tile),
        "estimated_cost": aircraft_purchase + airport_fees
    }
```

### 14.7 Pathfinding API

```
POST /pathfind
{
    "from_x": 10, "from_y": 20,
    "to_x": 50, "to_y": 60,
    "transport_type": "road",        // "road", "rail", "water"
    "company_id": 0,                 // For cost estimation
    "options": {
        "avoid_demolish": true,      // Don't path through existing structures
        "max_bridges": 3,            // Limit bridge count
        "prefer_flat": true,         // Weight against slopes
        "rail_type": "electric"      // For rail: which rail type
    }
}

Response:
{
    "path": [
        { "x": 10, "y": 20, "action": "start" },
        { "x": 11, "y": 21, "action": "build_road" },
        { "x": 12, "y": 22, "action": "build_bridge", "bridge_type": 0, "end_x": 15, "end_y": 25 },
        { "x": 15, "y": 25, "action": "build_road" },
        ...
        { "x": 50, "y": 60, "action": "end" }
    ],
    "total_cost": 15000,
    "total_tiles": 42,
    "bridges": 1,
    "tunnels": 0,
    "estimated_time_ms": 45
}
```

---

## 15. Command Tracking and Serialization

### 15.1 Per-Agent Command Tracking

Every command from every agent and human is tracked with:

```json
{
    "command_id": "cmd_abc123",
    "session_id": "sess_xyz",
    "participant_id": "agent_a",
    "participant_type": "agent",
    "company_id": 0,
    "game_date": 730120,
    "tick": 54028880,

    "action_type": "build_road",
    "parameters": { "from_x": 10, "from_y": 20, "to_x": 11, "to_y": 21 },

    "submitted_at": "2025-03-15T14:30:00.123Z",
    "executed_at": "2025-03-15T14:30:00.456Z",
    "completed_at": "2025-03-15T14:30:00.789Z",

    "status": "success",
    "error": null,
    "cost": 1500,
    "result": { "tile": 2570 },

    "context": {
        "balance_before": 125000,
        "balance_after": 123500,
        "preceding_state_snapshot_id": "snap_00042"
    }
}
```

### 15.2 Serialization Model: Per-Agent Sequential, Cross-Agent Parallel

**Critical design**: For a single agent/human, state fetching and action execution MUST be serialized. For different agents/humans, they CAN run in parallel.

```
Agent A (Company 0)          Agent B (Company 1)
    │                            │
    ├─ Fetch state ──────┐      ├─ Fetch state ──────┐
    │                    │      │                    │     ← These run in PARALLEL
    ├─ Submit action ◄───┘      ├─ Submit action ◄───┘       (different companies)
    │                            │
    ├─ Fetch state ──────┐      ├─ Fetch state ──────┐
    │                    │      │                    │
    ├─ Submit action ◄───┘      ├─ Submit action ◄───┘
    │                            │
    ▼                            ▼
```

**Why serialized per-agent?**
- Agent must see the result of its last action before deciding the next one
- If state fetch and action overlap, agent may act on stale data
- Financial state changes after each action (balance decreases)

**Why parallel cross-agent?**
- Different companies are independent contexts in GSCompanyMode
- No shared state conflicts (each company has separate balance, vehicles, etc.)
- Maximizes throughput — N agents can act simultaneously

#### Same-Company Multi-Agent (Special Case)

When multiple agents share a company, their actions must be serialized within that company:

```python
class CompanyActionQueue:
    """Serializes actions for agents sharing the same company."""

    def __init__(self):
        self._locks: dict[int, asyncio.Lock] = {}  # Per-company locks

    async def execute(self, company_id: int, action: ActionEnvelope):
        if company_id not in self._locks:
            self._locks[company_id] = asyncio.Lock()

        async with self._locks[company_id]:
            # Only one action per company at a time
            result = await self.gs_client.send_gamescript(action.action_type, action.parameters)
            return result
```

### 15.3 Async Real-Time Flow

In async real-time mode (our primary focus), the flow is:

```
Game Running (not paused)
    │
    ├─ nttd polls GS every N seconds (configurable, default 2s)
    │   └─ Refreshes WorldState
    │   └─ Pushes snapshot to all agents via WebSocket
    │
    ├─ Agent A receives snapshot
    │   └─ Decides actions (async, takes variable time)
    │   └─ Submits action via POST /actions/submit
    │   └─ nttd executes immediately via GS (no action window)
    │   └─ Result returned to agent
    │   └─ Agent fetches updated state
    │   └─ Repeats
    │
    ├─ Agent B receives snapshot (same time as A)
    │   └─ Same flow, parallel to A
    │
    └─ Human players act via OpenTTD GUI (parallel to agents)
```

**Key difference from heartbeat mode**: No pause/unpause cycle. No action window. Actions execute immediately when submitted. Agents must handle the fact that the game state is continuously changing.

### 15.4 Performance Considerations for Command Tracking

| Concern | Mitigation |
|---------|------------|
| DB write latency | Batch inserts (queue + flush every 50 records or 1 second) |
| Lock contention (same company) | Per-company asyncio.Lock, not global lock |
| GS round-trip time (~100-500ms) | Pipeline: send next query while waiting for response |
| Snapshot size for many agents | Compact snapshots (~1-3 KB) for agent context; full snapshots to DB only |
| WebSocket backpressure | Drop stale snapshots (maxsize=1 queue), only latest matters |

---

## 16. Leaderboard System

### 16.1 Leaderboard Design

The leaderboard shows performance comparison across players in a session and across sessions.

#### Per-Session Leaderboard

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Session: "4-Agent Competition" │ Map: 256x256 Temperate │ 365 days    │
├──────┬──────────┬──────────┬────────┬────────┬──────────┬──────────────┤
│ Rank │ Player   │ Type     │ Value  │ Rating │ Cargo    │ Vehicles     │
├──────┼──────────┼──────────┼────────┼────────┼──────────┼──────────────┤
│  1   │ GPT-4o   │ Agent    │ £980K  │  720   │ 12,000   │ 45           │
│  2   │ Claude   │ Agent    │ £850K  │  680   │ 10,500   │ 38           │
│  3   │ Player1  │ Human    │ £720K  │  640   │  8,200   │ 32           │
│  4   │ Gemini   │ Agent    │ £500K  │  520   │  6,100   │ 25           │
└──────┴──────────┴──────────┴────────┴────────┴──────────┴──────────────┘
```

#### Ranking Metrics

| Metric | Weight | Description |
|--------|--------|-------------|
| Company value | Primary | Final company valuation (£) |
| Performance rating | Secondary | OpenTTD's 0-1000 score |
| Total cargo delivered | Tertiary | Cumulative cargo units |
| Action success rate | Bonus | % of successful actions |
| Efficiency | Derived | Value per action submitted |

#### Cross-Session Leaderboard

Aggregates performance across multiple sessions for the same agent/player:

```
┌──────────────────────────────────────────────────────────────────┐
│  All-Time Leaderboard (last 30 sessions)                         │
├──────┬──────────┬─────────┬──────────┬──────────┬───────────────┤
│ Rank │ Player   │ Games   │ Avg Rank │ Avg Value│ Win Rate      │
├──────┼──────────┼─────────┼──────────┼──────────┼───────────────┤
│  1   │ Claude   │   15    │  1.4     │ £900K    │ 73%           │
│  2   │ GPT-4o   │   12    │  1.8     │ £820K    │ 58%           │
│  3   │ Player1  │    8    │  2.1     │ £750K    │ 38%           │
└──────┴──────────┴─────────┴──────────┴──────────┴───────────────┘
```

### 16.2 Leaderboard API

```
GET /leaderboard/session/{session_id}
    → Per-session rankings with all metrics

GET /leaderboard/global
    ?participant_type=agent|human|all
    &sessions=30                          (last N sessions)
    → Cross-session aggregated rankings

GET /leaderboard/participant/{id}/history
    → All sessions played by this participant with rankings

POST /leaderboard/compute/{session_id}
    → Recompute rankings for a session (admin action)
```

### 16.3 Score Computation

```python
def compute_session_rankings(session_id: str) -> list[LeaderboardEntry]:
    """Compute rankings from final snapshot of a session."""
    final_snapshot = db.get_latest_snapshot(session_id)
    actions = db.get_actions(session_id)

    entries = []
    for company in final_snapshot.companies:
        participant = db.get_participant(session_id, company.id)
        company_actions = [a for a in actions if a.company_id == company.id]
        success_rate = sum(1 for a in company_actions if a.status == "success") / max(len(company_actions), 1)

        entries.append(LeaderboardEntry(
            company_id=company.id,
            participant_id=participant.participant_id,
            participant_type=participant.participant_type,
            final_balance=company.money,
            final_value=company.value,
            final_rating=get_performance_rating(company),
            total_cargo=get_quarterly_cargo_sum(company),
            total_vehicles=count_vehicles(final_snapshot, company.id),
            total_stations=count_stations(final_snapshot, company.id),
            total_actions=len(company_actions),
            action_success_rate=success_rate,
        ))

    # Sort by company value (primary), then rating
    entries.sort(key=lambda e: (e.final_value, e.final_rating), reverse=True)
    for rank, entry in enumerate(entries, 1):
        entry.rank = rank

    return entries
```

---

## 17. Performance Architecture

### 17.1 System Bottlenecks and Budgets

| Component | Bottleneck | Budget | Mitigation |
|-----------|-----------|--------|------------|
| GS round-trip | ~100-500ms per command | ~2s per snapshot cycle | Pipeline commands, batch queries |
| Admin port bandwidth | ~1450 bytes/packet GS→admin | N/A | Chunking already handles this |
| Snapshot generation | ~50-200ms for full state | <500ms target | Cache intermediate results |
| DB writes | ~1-5ms per INSERT | <50ms per batch | Batch inserts, WAL mode |
| WebSocket push | ~1-5ms per client | <10ms total | Async broadcast, drop stale |
| Pathfinding | ~10-500ms per route | <1s target | Cache tile data, prune search space |
| Agent decision time | ~1-30s (LLM dependent) | Agent's problem | Timeout with fallback |

### 17.2 Async Real-Time Performance Model

At normal game speed (1 day ≈ 2 seconds):

```
Time budget per game-day: 2000ms

Breakdown:
  GS state refresh:     400ms  (4 queries × 100ms each)
  Snapshot creation:    100ms  (serialize WorldState)
  DB persistence:        50ms  (batch write)
  WebSocket broadcast:   10ms  (push to all agents)
  Agent processing:   1400ms  (remaining time for agent decisions)

  Total:              1960ms  (40ms margin)
```

At reduced game speed (game_speed=50, 1 day ≈ 4 seconds):
- Agent processing budget doubles to ~3400ms
- Comfortable margin for LLM reasoning

### 17.3 Optimization Strategies

#### GS Query Optimization

```python
# Instead of 7 separate queries per cycle:
# get_towns, get_industries, get_companies,
# get_company_finance × N, get_stations × N, get_vehicles × N, get_subsidies

# Implement a single mega-query in GS:
# get_full_state → returns everything in one call
# Reduces round-trips from 7+3N to 1
```

Stagger non-critical queries:
- **Every cycle**: companies, finances (fast, small)
- **Every 5 cycles**: towns, industries (change slowly)
- **Every 10 cycles**: subsidies, cargo types (change rarely)

#### Database Write Optimization

```python
# Use WAL mode for concurrent reads during writes
await db.execute("PRAGMA journal_mode=WAL")

# Batch inserts
async def flush_metrics(self, batch: list[dict]):
    await db.executemany(
        "INSERT INTO metrics (session_id, game_date, company_id, metric_name, metric_value) "
        "VALUES (?, ?, ?, ?, ?)",
        [(m["session_id"], m["game_date"], m["company_id"], m["name"], m["value"]) for m in batch]
    )
```

#### WebSocket Optimization

```python
# Don't send full snapshot via WebSocket — only a lightweight trigger
trigger = {
    "type": "state_update",
    "game_date": snapshot.game.game_date,
    "companies": len(snapshot.companies),
    "version": snapshot.game.snapshot_id
}
# Agent fetches full/compact state via REST if needed
```

#### Memory Management

- Ring buffer with fixed size (100 snapshots × ~100KB = ~10MB)
- Tile cache: ~256×256×64 bytes = ~4MB for typical map
- DB connection pooling (aiosqlite with WAL allows concurrent reads)

### 17.4 Scaling Considerations

| Scale | Architecture | Notes |
|-------|-------------|-------|
| 1-4 agents, 1 session | Single process, SQLite | Default deployment |
| 5-15 agents, 1 session | Single process, SQLite WAL | May need game_speed reduction |
| Multiple concurrent sessions | Separate nttd process per session, shared PostgreSQL | Each session = 1 OpenTTD + 1 nttd |
| Tournament (many sessions) | Session orchestrator + PostgreSQL + shared leaderboard | Queue-based session scheduling |

---

## 18. Tech Stack — Admin Console Frontend

### 18.1 Recommended Stack: React + Vite + pnpm

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Framework | **React 18+** | Component model, large ecosystem, real-time UI |
| Build tool | **Vite** | Fast dev server, HMR, optimized builds |
| Package manager | **pnpm** | Faster than yarn, strict dependency resolution |
| Language | **TypeScript** | Type safety for API schemas |
| Styling | **Tailwind CSS** | Utility-first, fast iteration |
| Charts | **Recharts** or **Tremor** | React-native charts, time-series support |
| Tables | **TanStack Table** | Sorting, filtering, pagination for leaderboard |
| WebSocket | **Native WebSocket** or **socket.io-client** | Real-time updates |
| State | **Zustand** or **TanStack Query** | Lightweight, good for server-state |
| Routing | **React Router v6** | Multi-page admin console |
| HTTP client | **ky** or **fetch** | API calls to nttd backend |

> Note: pnpm is preferred over yarn for strictness and speed. If the team prefers yarn, yarn v4 (berry) with PnP is also fine.

### 18.2 Project Structure

```
admin-console/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── tailwind.config.ts
├── index.html
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── api/
│   │   ├── client.ts              # HTTP client wrapper
│   │   ├── websocket.ts           # WebSocket connection manager
│   │   └── types.ts               # TypeScript types matching nttd schemas
│   ├── pages/
│   │   ├── SessionPage.tsx         # Page 1: Session management
│   │   ├── PlayersPage.tsx         # Page 2: Players & agents
│   │   ├── MetricsPage.tsx         # Page 3: Metrics & timeline
│   │   └── LeaderboardPage.tsx     # Page 4: Leaderboard
│   ├── components/
│   │   ├── SessionConfig.tsx       # Session creation form
│   │   ├── AgentPanel.tsx          # Agent list & management
│   │   ├── PlayerPanel.tsx         # Human player list
│   │   ├── SpectatorPanel.tsx      # Spectator list
│   │   ├── EventFeed.tsx           # Live event log
│   │   ├── MessageCenter.tsx       # Chat & messages
│   │   ├── DeityPanel.tsx          # Deity operations
│   │   ├── TimelineChart.tsx       # Time-series chart with scrubber
│   │   ├── FinancialBreakdown.tsx  # Expense/revenue pie charts
│   │   ├── VehicleChart.tsx        # Vehicle counts bar chart
│   │   ├── LeaderboardTable.tsx    # Sortable ranking table
│   │   └── GameStatus.tsx          # Top bar: date, speed, status
│   ├── hooks/
│   │   ├── useWebSocket.ts         # WebSocket connection hook
│   │   ├── useMetrics.ts           # Time-series data fetching
│   │   ├── useSession.ts           # Session state management
│   │   └── useAgents.ts            # Agent list management
│   └── stores/
│       └── gameStore.ts            # Zustand store for real-time state
└── public/
    └── favicon.ico
```

### 18.3 Real-Time Data Flow

```
nttd Server                         Admin Console (React)
    │                                      │
    │  WebSocket /ws/admin                 │
    │─────────────────────────────────────>│  useWebSocket() hook
    │  { type: "state_update",            │
    │    game_date: 730120, ... }         │  Updates Zustand store
    │                                      │  Triggers re-renders
    │                                      │
    │  GET /metrics/timeseries            │
    │<─────────────────────────────────────│  useMetrics() hook
    │  [{ date: 730001, value: ... }]     │  Feeds Recharts
    │─────────────────────────────────────>│
    │                                      │
    │  GET /state/full                    │
    │<─────────────────────────────────────│  Periodic poll (fallback)
    │  { companies: [...], ... }          │
    │─────────────────────────────────────>│
```

### 18.4 Backend API Extensions for Admin Console

New endpoints needed beyond existing nttd API:

```
POST /admin/sessions/new              → Create session with settings
GET  /admin/sessions                  → List all sessions
GET  /admin/sessions/{id}             → Session details
POST /admin/sessions/{id}/settings    → Update settings mid-game

GET  /admin/clients                   → Connected game clients (human players)
POST /admin/clients/{id}/move         → Move client to company/spectator
POST /admin/clients/{id}/kick         → Kick client

POST /admin/agents/{id}/launch       → Launch an agent process
POST /admin/agents/{id}/stop         → Stop an agent process

GET  /admin/events/stream             → SSE or WebSocket event stream
GET  /admin/events/history            → Paginated event log

POST /admin/deity/*                   → All deity operations (section 11.6)

GET  /metrics/*                       → All time-series endpoints (section 12.3)
GET  /leaderboard/*                   → All leaderboard endpoints (section 16.2)
GET  /replay/*                        → All replay endpoints (section 12.5)
GET  /messages/*                      → All message endpoints (section 10.2)

POST /pathfind                        → Pathfinding service (section 14.7)
```

### 18.5 Development Workflow

```bash
# Backend (nttd)
cd /Users/228496/exp/nttd
uv run uvicorn nttd.api.app:app --reload --port 8000

# Frontend (admin console)
cd admin-console
pnpm install
pnpm dev    # Vite dev server on port 5173, proxies API to :8000
```

Vite config for API proxy:
```typescript
// vite.config.ts
export default defineConfig({
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true, rewrite: (path) => path.replace(/^\/api/, '') },
      '/ws': { target: 'ws://localhost:8000', ws: true }
    }
  }
})
```
