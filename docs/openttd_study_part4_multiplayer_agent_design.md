# OpenTTD Study Part 4: Multiplayer, AI Agents, and System Design

> Companion to Parts 1-3. Covers multiplayer mechanics, LLM agent integration, admin client architecture, game state management, and technical constraint mitigation strategies.
>
> **Primary sources**: OpenTTD C++ source (`[openTTD](https://github.com/OpenTTD/OpenTTD)`), OpenTTD wiki, nttd codebase, docs.openttd.org GS/AI API references.

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
