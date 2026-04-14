# Rail Agent Pipeline Report

Session: `ses_20260413_155400_27d6537d` | Model: gpt-5.2 | Framework: langchain
Date: 2026-04-13 | Duration: 20:06 | Map: 256x256 hilly temperate

---

## 1. End-to-End Data Flow

### 1.1 Session Startup

```
CLI: nttd benchmark --config config/scenario_20min_rail_only.conf
  |
  v
benchmark_command.py
  |-- POST /admin/sessions/new
  |     body: { name, settings: { map_x=8, map_y=8, landscape=0, ... } }
  |     returns: session_id
  |
  |-- POST /admin/sessions/{id}/end-conditions
  |     body: { logic: "any", time_limit: { enabled: true, wall_minutes: 20 } }
  |
  |-- POST /admin/sessions/{id}/start
  |     body: { mode: "newgame", ai_opponents: 0, agent_companies: 1 }
  |     -> Spawns OpenTTD server process (headless -D mode)
  |     -> AdminClient connects to admin port (TCP)
  |     -> AdminClient subscribes to: DATE, COMPANY_INFO, COMPANY_ECONOMY,
  |        COMPANY_STATS, CHAT, CONSOLE, GAMESCRIPT updates
  |     returns: { game_port, pid }
  |
  |-- POST /sessions/{id}/speed?speed=1
  |-- POST /sessions/{id}/mode?mode=async_realtime
  |
  |-- POST /sessions/{id}/gameloop/agents/register      <-- agent registration
  |     body: AgentConfig (see 1.2)
  |
  |-- POST /sessions/{id}/gameloop/agents/rail_agent/start  <-- starts cycle loop
```

### 1.2 Agent Registration

Registration creates the agent's runtime objects:

```
API route: gameloop_routes.py:register_agent()
  |
  v
GameloopManager.register_agent(config: AgentConfig)
  |
  |-- Validate: company_id in [0,14], agent_id unique
  |
  |-- Create adapter (based on config.framework):
  |     "langchain" -> LangChainAdapter(model="gpt-5.2", api_key_env="OPENAI_API_KEY")
  |     "openai"    -> OpenAIAdapter(...)
  |     "passthrough" -> PassthroughAdapter()
  |
  |-- Create AgentConnection:
  |     connection_id = "ses_xxx:0:rail_agent"
  |     |
  |     |-- Load default instructions (if not provided):
  |     |     agent_type="rail" -> get_rail_agent_prompt(company_id=0)
  |     |
  |     |-- Create ConnectionTracker (cycle telemetry)
  |     |
  |     |-- Create _action_history deque(maxlen=10)
  |     |
  |     |-- Create ObservationToolkit (if observation_tools=true):
  |           ObservationToolkit(admin_client, company_id=0, agent_type="rail",
  |                              map_width=256, map_height=256)
  |           -> _vehicle_types = {"train"}
  |           -> _station_filter = lambda s: s.get("has_rail")
  |           -> _tool_map = { 32 tools mapped by name }
  |
  |-- Register in agent_registry for visibility
  |
  returns: connection_id
```

**AgentConfig payload** (from scenario config):
```
agent_id          = "rail_agent"
company_id        = 0
framework         = "langchain"
model             = "gpt-5.2"
agent_type        = "rail"
instructions_file = "examples/agent_instructions.py:get_rail_agent_prompt"
observation_mode  = "agent"       # maps to snapshot class "agent"
poll_interval     = 10.0          # seconds between cycles
observation_tools = true          # enable 32 observation tools
max_actions_per_cycle = 5         # truncate if agent proposes more
max_history_cycles = 10           # rolling action history depth
api_key_env       = "OPENAI_API_KEY"
```

### 1.3 Agent Start

```
AgentConnection.start()
  |-- Sets _running = True
  |-- Spawns asyncio.Task: _run() loop
  |-- Records event "agent_start" to parquet database
  |-- Records agent connection metadata to parquet database
```

---

## 2. The Agent Cycle (Observe -> Decide -> Execute)

Every `poll_interval` seconds (10s in this session):

```
_run_one_cycle()
  |
  |-- [1] OBSERVE   (~1.5ms)
  |     _observe() -> dict (~14,200 bytes)
  |
  |-- [2] DECIDE    (~4,500ms)
  |     adapter.decide(observation, instructions, tool_schemas, tool_executor)
  |     -> LLM call with multi-turn tool calling (up to 8 rounds)
  |     -> Returns raw JSON string: '[{"action_type":..., "parameters":...}, ...]'
  |
  |-- [3] PARSE & VALIDATE  (<1ms)
  |     parse_action_list(raw_output) -> list[AgentAction]
  |     validate_actions(actions) -> errors dict
  |     Truncate to max_actions_per_cycle (5)
  |
  |-- [4] EXECUTE   (~50ms per action)
  |     _execute(valid_actions, game_date)
  |     -> Sends each action to GS via admin port TCP
  |     -> Records each action + result to parquet database
  |
  |-- [5] POST-EXECUTE
  |     Record successful actions to _action_history
  |     Store cycle_results as _last_cycle_results
  |     Record cycle telemetry (observe_ms, decide_ms, execute_ms, balance, etc.)
  |
  |-- [6] SLEEP poll_interval seconds
```

### 2.1 Observe Phase

**Snapshot class "agent" includes these sections:**
`company`, `vehicles_detail`, `stations_detail`, `top_towns`, `industries`, `routes`, `route_planning`

**Plus always-appended sections:**
`route_status`, `previous_actions`, `action_history`

**Observation dict structure with typical values from this session:**

```json
{
  "game_date": 716232,
  "paused": false,

  "company": {
    "id": 0,
    "name": "Agent Transport",
    "balance": 131870,
    "loan": 200000,
    "income": 0,
    "company_value": 1,
    "profit_last_year": -1676
  },

  "vehicles": [
    {
      "id": 4,
      "type": "train",
      "name": "Train #1",
      "running": true,
      "in_depot": false,
      "profit_this_year": -838,
      "profit_last_year": -1676,
      "current_speed": 64,
      "age": 517,
      "order_count": 2,
      "orders": [
        {"destination": 39976, "flags": 0, "is_goto_station": true, "is_goto_depot": false},
        {"destination": 45584, "flags": 0, "is_goto_station": true, "is_goto_depot": false}
      ]
    },
    {
      "id": 5,
      "type": "train",
      "name": "Train #2",
      "running": true,
      "in_depot": false,
      "profit_this_year": -228,
      "profit_last_year": 0,
      "current_speed": 48,
      "age": 200,
      "order_count": 2,
      "orders": [...]
    }
  ],

  "stations": [
    {
      "id": 0,
      "name": "Brudingville Transfer",
      "x": 155, "y": 124,
      "has_rail": true, "has_bus": false, "has_truck": false,
      "has_airport": false, "has_dock": false,
      "cargo_waiting": [
        {"cargo_label": "COAL", "waiting": 0}
      ],
      "cargo_acceptance": [
        {"cargo_label": "COAL", "accepts": false, "produces": true}
      ]
    }
  ],

  "top_towns": [
    {"id": 5, "name": "Brudingville", "population": 1234, "x": 155, "y": 120}
  ],
  "total_towns": 22,

  "industries": [
    {
      "id": 0, "name": "Brudingville Coal Mine", "type_name": "Coal Mine",
      "x": 150, "y": 125, "is_raw": true,
      "production": [{"cargo_label": "COAL", "last_month": 72}],
      "accepted": []
    }
  ],

  "routes": [
    {
      "route_id": "r0", "vehicle_type": "train",
      "station_ids": [0, 1], "vehicle_count": 1,
      "profit_this_year": -838
    }
  ],

  "route_planning": {
    "top_unserved_cargo": [
      {
        "source": "Coal Mine", "dest": "Power Station",
        "cargo": "COAL", "distance": 12, "monthly_production": 72,
        "source_x": 150, "source_y": 125, "dest_x": 162, "dest_y": 130
      }
    ]
  },

  "route_status": {
    "total_stations": 4,
    "stations_with_vehicles": 4,
    "orphan_stations": 0,
    "orphan_station_ids": []
  },

  "previous_actions": [
    {"action": "reverse_vehicle", "status": "success", "result": {"vehicle_id": 4}}
  ],

  "action_history": [
    [
      {"action_type": "set_loan", "parameters": {"amount": 200000}},
      {"action_type": "build_rail_station", "parameters": {"x": 155, "y": 124, "num_platforms": 1}}
    ],
    [
      {"action_type": "connect_rail", "parameters": {"from_x": 155, "from_y": 124, "to_x": 162, "to_y": 130}},
      {"action_type": "buy_vehicle", "parameters": {"depot_tile": 39720, "engine_id": 2}}
    ]
  ]
}
```

**Filtering by agent_type="rail":**
- `vehicles`: only `type == "train"` shown
- `stations`: only `has_rail == true` shown
- `routes`: only `vehicle_type == "train"` shown

**Actual observation size in this session: ~14,200 bytes per cycle** (consistent across all 84 cycles).

### 2.2 Decide Phase (LLM Invocation)

```
LangChainAdapter.decide(observation, instructions, tool_schemas, tool_executor)
  |
  |-- Get/create LLM:
  |     ChatOpenAI(model="gpt-5.2", api_key=OPENAI_API_KEY, temperature=0.2)
  |
  |-- Bind observation tools (32 tool schemas) to LLM:
  |     bound_llm = llm.bind_tools(observation_tools)
  |
  |-- Build message list:
  |     messages = [
  |       SystemMessage(content=instructions),     # ~5,900 tokens (see 3.1)
  |       HumanMessage(content=                    # ~4,000-5,000 tokens
  |         "Current game state:\n"
  |         + json.dumps(observation, indent=2)    # ~14,200 bytes -> ~3,500 tokens
  |         + "\n\nAnalyze the state. Use observation tools..."
  |       )
  |     ]
  |
  |-- Multi-turn tool calling loop (max 8 rounds):
  |     for round in range(8):
  |       response = await bound_llm.ainvoke(messages)
  |       messages.append(response)  # AIMessage
  |       |
  |       |-- If response.tool_calls is empty:
  |       |     return response.content  # Final action JSON
  |       |
  |       |-- For each tool_call in response.tool_calls:
  |             tool_name = tool_call["name"]
  |             tool_args = tool_call["args"]
  |             |
  |             |-- tool_executor(tool_name, tool_args)
  |             |     ObservationToolkit.execute()
  |             |       |-- Look up tool in _tool_map
  |             |       |-- If custom_handler == "pathfind":
  |             |       |     _handle_pathfind(args) -> pathfinding service
  |             |       |-- Else:
  |             |       |     gs_action = tool_def["gs_action"]
  |             |       |     params = {**args}
  |             |       |     if inject_company_id: params["company_id"] = 0
  |             |       |     result = admin_client.send_gamescript(gs_action, params)
  |             |       |     result = _filter_by_agent_type(tool_name, result)
  |             |       |     return json.dumps(result, indent=2)
  |             |
  |             messages.append(ToolMessage(content=result, tool_call_id=id))
  |
  |-- If 8 rounds exhausted: return last response.content or "[]"
```

**Typical tool calling pattern in this session** (from agent cycles):

Round 1: LLM calls `get_engines(vehicle_type=0)` and `get_industries()`
Round 2: LLM calls `find_flat_spots(tile=..., radius=10, min_size=3)`
Round 3: LLM returns final action JSON

**Total tokens per LLM call (estimated):**

| Component | Tokens |
|-----------|--------|
| System prompt (instructions) | ~5,900 |
| Observation JSON (HumanMessage) | ~3,500 |
| Tool schemas (32 tools, auto-bound) | ~2,000 |
| Tool call round 1 (request + response) | ~500-2,000 |
| Tool call round 2 (request + response) | ~500-2,000 |
| LLM final response | ~200-500 |
| **Total input tokens per cycle** | **~12,000-16,000** |

**Timing:** Average decide_ms = 4,550ms (min 1,800ms, max 6,000ms)

### 2.3 Parse and Validate Phase

```
raw_output = '[ {"action_type":"build_rail_station","parameters":{...}}, ... ]'
  |
  v
parse_action_list(raw_output)
  |-- _extract_raw_list():
  |     Try 1: json.loads(text) -> list[dict]  (usually succeeds)
  |     Try 2: Extract from ```json ... ``` code block
  |     Try 3: Regex extract any [...] from text
  |
  |-- For each item in raw list:
  |     _normalize_action_fields():
  |       "action" -> "action_type"  (alias)
  |       "params" -> "parameters"   (alias)
  |       "type"   -> "action_type"  (alias)
  |     AgentAction.model_validate(normalized)
  |       -> AgentAction(action_type="build_rail_station", parameters={...})
  |
  v
validate_actions(actions)
  |-- For each action:
  |     Check action_type in KNOWN_ACTIONS (90+ known types)
  |     Check required params (e.g., build_bridge needs start_x/y, end_x/y)
  |
  v
Truncate to max_actions_per_cycle (5)
```

### 2.4 Execute Phase

```
_execute(valid_actions, game_date)
  |
  For each action:
  |
  |-- params = {**action.parameters, "company_id": 0}
  |
  |-- timeout = 120s if action_type.startswith("connect_") else 10s
  |
  |-- admin_client.send_gamescript(action_type, params, timeout)
  |     |
  |     |-- Build GS command:
  |     |     {"id": "gs_42", "action": "build_rail_station", "params": {"x":155, "y":124, ...}}
  |     |
  |     |-- Serialize to JSON + \x00 null terminator
  |     |
  |     |-- Send via TCP admin port as AdminGameScriptPacket:
  |     |     [2-byte length][1-byte type=0x06][json\x00]
  |     |
  |     |-- GS (Squirrel) receives in HandleRequest():
  |     |     switch(action) -> CmdBuildRailStation(params)
  |     |       -> GSCompanyMode(company_id)
  |     |       -> GSRail.BuildRailStation(tile, track, platforms, length, STATION_NEW)
  |     |       -> Return: {"id":"gs_42", "success":true, "result":{...}}
  |     |
  |     |-- If response > ~1400 bytes, GS chunks it:
  |     |     chunk 0: {"id":"gs_42", "result":[...], "_chunk":0, "_total":3}
  |     |     chunk 1: {"id":"gs_42", "result":[...], "_chunk":1, "_total":3}
  |     |     chunk 2: {"id":"gs_42", "result":[...], "_chunk":2, "_total":3}
  |     |     AdminClient reassembles by correlation ID
  |     |
  |     |-- GS response arrives as GameScriptPacket on admin port
  |     |     -> _handle_gs_response() matches by correlation ID
  |     |     -> Signals asyncio.Event when all chunks received
  |     |
  |     returns: {"id":"gs_42", "success":true, "result":{"tile":[155,124], "station_id":0}}
  |
  |-- Record to parquet database:
  |     ActionEnvelope(action_id, action_type, parameters, company_id, metadata)
  |     ActionResult(action_id, status=SUCCESS|FAILED, error="")
  |
  returns: [{"status":"success", "result":{...}}, ...]
```

### 2.5 Post-Execute Phase

```
After execution completes:
  |
  |-- Build _last_cycle_results (for next cycle's "previous_actions"):
  |     [{"action": "build_rail_station", "status": "success", "result": {...}}, ...]
  |
  |-- Record successful actions to _action_history:
  |     successful_actions = [
  |       {"action_type": "build_rail_station", "parameters": {"x":155, "y":124, ...}}
  |     ]
  |     _action_history.append(successful_actions)  # deque maxlen=10
  |
  |-- Record cycle telemetry:
  |     CycleRecord(observe_ms, decide_ms, execute_ms, total_ms,
  |                 actions_proposed, executed, succeeded, failed,
  |                 observation_size_bytes, balance, income, company_value,
  |                 balance_delta, vehicles_running)
```

---

## 3. Instructions Structure

### 3.1 System Prompt Composition

The rail agent prompt is assembled from 5 templates, in this order:

```
get_rail_agent_prompt(company_id=0) returns:

  SYSTEM_PROMPT_RAIL_AGENT.format(
    company_id=0,
    tile_system=TILE_SYSTEM_DOCS,
    multi_turn_guide=MULTI_TURN_GUIDE,
    action_format=ACTION_FORMAT_INSTRUCTIONS,
    action_reference=ACTION_REFERENCE,
  )
```

**Final prompt layout (top to bottom):**

| # | Section | Source | Chars | ~Tokens | Content |
|---|---------|--------|-------|---------|---------|
| 1 | Goal + role | SYSTEM_PROMPT_RAIL_AGENT | 300 | 75 | "You are the rail transport manager for company 0..." |
| 2 | EVERY CYCLE -- CHECK FIRST | SYSTEM_PROMPT_RAIL_AGENT | 600 | 150 | Check action_history, check orphan stations |
| 3 | PHASE 1 -- SCOUT | SYSTEM_PROMPT_RAIL_AGENT | 900 | 225 | route_planning, find_flat_spots, get_engines, get_rail_types |
| 4 | PHASE 2 -- BUILD STATIONS | SYSTEM_PROMPT_RAIL_AGENT | 400 | 100 | build_rail_station, build_rail_depot |
| 5 | PHASE 3 -- CONNECT TRACK | SYSTEM_PROMPT_RAIL_AGENT | 500 | 125 | connect_rail between stations |
| 6 | PHASE 4 -- BUY VEHICLE | SYSTEM_PROMPT_RAIL_AGENT | 600 | 150 | buy_vehicle, add_order, start_vehicle |
| 7 | PHASE 5 -- VERIFY | SYSTEM_PROMPT_RAIL_AGENT | 500 | 125 | Check train movement, cargo_waiting |
| 8 | PHASE 6 -- EXPAND | SYSTEM_PROMPT_RAIL_AGENT | 300 | 75 | Clone profitable trains, new routes |
| 9 | RAIL CONSTRUCTION | SYSTEM_PROMPT_RAIL_AGENT | 636 | 159 | min_size=3, direction, rail_type |
| 10 | IMPORTANT RULES | SYSTEM_PROMPT_RAIL_AGENT | 1,859 | 464 | Agent-type filtering, cargo checks |
| 11 | TILE COORDINATE SYSTEM | TILE_SYSTEM_DOCS | 3,173 | 793 | How tile IDs work, workflow example |
| 12 | MULTI_TURN_GUIDE | MULTI_TURN_GUIDE | 7,051 | 1,762 | Tool list, action history, loans, patience, leave-running |
| 13 | ACTION FORMAT | ACTION_FORMAT_INSTRUCTIONS | ~500 | 125 | JSON array output format |
| 14 | ACTION REFERENCE | ACTION_REFERENCE | 4,783 | 1,195 | All 90+ action types with params |
| | **TOTAL** | | **23,570** | **~5,900** | |

**Plus runtime injection** (connection.py line 228-233):
```
"\n\nIMPORTANT: You may output at most 5 actions per cycle.
 Any actions beyond 5 will be discarded."
```

### 3.2 What the LLM Sees Per Cycle

```
[SystemMessage]     ~5,900 tokens  -- instructions (constant, never changes)
[HumanMessage]      ~3,500 tokens  -- "Current game state:\n" + observation JSON
[Tool calls]        ~500-4,000 tokens  -- if agent calls observation tools
[ToolMessages]      ~500-4,000 tokens  -- tool results
                    ─────────────────
                    ~10,000-18,000 tokens total input per cycle
```

### 3.3 Observation Tools Available (32 tools)

All tools go through GS bridge (admin port TCP -> Squirrel) except `pathfind` (custom handler).

| Category | Tools |
|----------|-------|
| **Towns** | get_towns, get_town_info, get_town_rating, scan_town_area |
| **Industries** | get_industries, get_industry_info |
| **Companies** | get_companies, get_company_finance |
| **Vehicles** | get_engines, get_vehicles, get_vehicle_info, get_orders |
| **Stations** | get_stations, get_station_info |
| **Spot finding** | find_bus_stop_spots, find_depot_spots, find_flat_spots, find_airport_spots, find_dock_spots, find_water_depot_spots, get_hangars |
| **Map/Tile** | get_tile_info, get_map_size |
| **Infrastructure** | get_cargo_types, get_rail_types, get_road_types, get_bridge_types, get_airport_types |
| **Other** | get_subsidies, get_groups, get_date, pathfind |

Tools with `inject_company_id`: get_company_finance, get_engines, get_vehicles, get_stations, find_bus_stop_spots, find_depot_spots, find_airport_spots, find_dock_spots, find_flat_spots, find_water_depot_spots, get_hangars, get_groups, get_town_rating.

Tool results for `get_vehicles` and `get_stations` are filtered by agent_type (rail agent only sees trains and rail stations).

---

## 4. Action History Pipeline

### 4.1 How It Works

```
Cycle N:
  Agent outputs: [action1, action2, action3]
  Execution results: [success, failed, success]
  |
  successful_actions = [
    {"action_type": "build_rail_station", "parameters": {"x":155, ...}},
    {"action_type": "buy_vehicle", "parameters": {"depot_tile":39720, ...}}
  ]
  _action_history.append(successful_actions)

Cycle N+1:
  observation["action_history"] = [
    [cycle N-9 successful actions],
    [cycle N-8 successful actions],
    ...
    [cycle N successful actions]    <-- most recent
  ]
```

### 4.2 Verification From This Session

- `_action_history` is a `collections.deque(maxlen=10)` -- stores up to 10 cycles
- Only successful actions are included (failed actions are excluded)
- Actions retain their original agent output format: `{"action_type": ..., "parameters": ...}`
- Chronological order is preserved (infrastructure before vehicles)
- Configurable via `max_history_cycles` in scenario config (default: 10)

### 4.3 What Changed From Previous Design

**Before (conversation history):**
- Stored full observation + LLM response pairs (2 cycles)
- ~10,000-20,000 tokens of stale, bloated context
- Adapter was stateful (maintained _history deque)

**After (action history):**
- Stores only successful action lists (10 cycles)
- ~500-1,000 tokens of compact, relevant context
- Adapter is stateless -- all memory flows through observation

---

## 5. Session Results

### 5.1 Summary

| Metric | Previous Run | This Run | Change |
|--------|-------------|----------|--------|
| Duration | 20:12 | 20:06 | - |
| Game days | 599 | 596 | - |
| Total actions | 74 | 65 | -12% |
| Success rate | 78.4% | 98.5% | +20pp |
| Vehicles bought | 1 | 2 | +1 |
| Vehicles at end | 0 | 2 | +2 |
| Income | 0 | 0 | same |
| Cargo delivered | 0 | 0 | same |
| Stations built | 17 (58.6%) | 4 (100%) | quality up |
| Orphan stations | 17 | 0 | fixed |
| Route completion | never | 2 routes | fixed |

### 5.2 What Improved

1. **No more infrastructure build loop**: 4 stations (all with vehicles) vs 17 orphan stations
2. **Route completion**: 2 complete routes (stations + track + vehicles + orders) vs 0
3. **98.5% action success rate** vs 78.4% -- far fewer wasted actions
4. **No vehicles sold**: Both trains still running at end vs 1 bought then sold

### 5.3 What Still Fails

1. **Zero income / zero cargo**: Both trains ran for 596 game days but delivered nothing
2. **reverse_vehicle spam**: 31 out of 65 actions (47.7%) were reverse_vehicle -- agent was thrashing
3. **Trains never completed deliveries**: profit_this_year + profit_last_year = -3,953 total

### 5.4 Action Breakdown

| Action | Count | % of Total |
|--------|-------|------------|
| reverse_vehicle | 31 | 47.7% |
| start_vehicle | 8 | 12.3% |
| connect_rail | 6 | 9.2% |
| send_to_depot | 6 | 9.2% |
| build_rail_station | 4 | 6.2% |
| add_order | 4 | 6.2% |
| build_rail_depot | 3 | 4.6% |
| buy_vehicle | 2 | 3.1% |
| set_loan | 1 | 1.5% |

---

## 6. Root Cause Analysis

### 6.1 Zero Income Despite Running Trains

The trains have orders and are running, but income = 0 for the entire session. Possible causes:

1. **Stations outside industry catchment**: find_flat_spots returned tiles that pass geometric checks but are too far from the industry center for cargo pickup. The `station_test` and `required_cargo` filters were committed but NOT loaded for this run (GS was loaded before the code changes).

2. **Wrong cargo type**: The stations may accept/produce different cargo than what the industry actually outputs. The agent should check `cargo_acceptance` in find_flat_spots results.

3. **Trains never complete a round trip**: With 31 reverse_vehicle calls disrupting every trip, the trains may never reach their destination stations to load or unload.

### 6.2 reverse_vehicle Thrashing

The agent entered a `start -> reverse -> depot -> start -> reverse` loop consuming 47.7% of all actions. The "LEAVE RUNNING VEHICLES ALONE" rule was committed AFTER this session started, so the agent didn't have it.

### 6.3 Cycle Efficiency

- 84 total cycles, 65 actions -- 19 cycles (22.6%) had zero actions
- Of the 65 actions, only 13 (20%) were infrastructure/route-building
- 45 actions (69%) were vehicle manipulation (start, reverse, depot) -- wasted
- The agent spent the majority of its 20 minutes fidgeting with trains instead of building

---

## 7. Cycle Telemetry

| Metric | Value |
|--------|-------|
| Total cycles | 84 |
| Avg cycle time | 4,774ms |
| Avg observe time | 1.5ms |
| Avg decide time | 4,553ms (95.4% of cycle) |
| Avg execute time | 51.6ms |
| Observation size | ~14,200 bytes (stable) |
| Poll interval | 10.0s |
| Effective cycle period | ~14.8s (10s sleep + 4.8s cycle) |

**Bottleneck**: LLM inference dominates at 95.4% of cycle time. Observation and execution are negligible.

---

## 8. Fixes Applied But Not Yet Tested

These were committed during/after this session and will take effect on the next run:

1. **LEAVE RUNNING VEHICLES ALONE** rule (shared, all agents) -- should eliminate the reverse_vehicle spam
2. **Reactive loan guidance** (shared, all agents) -- take loans only when needed
3. **GSTestMode dry-run** in CmdFindFlatSpots -- `station_test` param validates station placement
4. **required_cargo filter** in CmdFindFlatSpots -- only return tiles producing target cargo
5. **route_status** in observation -- flags orphan stations with counts
6. **find_flat_spots tool schema** updated with station_test, platform_length, rail_type, required_cargo params

---

## 9. Recommendations for Next Run

1. **Re-run the same benchmark** to test all fixes (especially leave-running-vehicles-alone and find_flat_spots validation)
2. **Verify cargo delivery**: The `required_cargo` filter should ensure stations are within industry catchment
3. **Monitor reverse_vehicle count**: Should drop to near-zero with the new rule
4. **Watch for action distribution**: Healthy ratio is ~60% infrastructure, ~30% operations, ~10% financial
5. **Consider adding `age_days` to vehicle observation**: Currently not included -- agent can't check vehicle age without calling get_vehicle_info tool
