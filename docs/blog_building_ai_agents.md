# Building AI Agents That Play Transport Tycoon

*What happens when you give GPT-5.2 the keys to a transport empire?*

---

## Introduction

OpenTTD, the open-source reimplementation of Transport Tycoon Deluxe, is a real-time strategy game where players build transport networks connecting towns and industries. It requires long-horizon planning, resource management, spatial reasoning, and adaptation to a dynamic economy. These are exactly the capabilities we want to test in LLM-powered agents.

**nttd** (Neural Transport Tycoon Driver) is an agent-agnostic API server that wraps OpenTTD as an AI simulation environment. Agents connect via HTTP, observe game state through structured JSON, and submit actions, all without touching OpenTTD internals. Any system that speaks JSON over HTTP can be an agent: LangChain, OpenAI function calling, AutoGen, a plain Python script, or an RL policy.

This article describes how we built the gameloop (the observe-decide-act cycle that lets LLM agents play OpenTTD autonomously) and what happened when we ran three specialized transport agents (rail, air, water) simultaneously on the same company.

---

## Architecture: Agent-Agnostic by Design

```
┌─────────────────────────────────────────────────────┐
│                    Agent (any framework)             │
│         OpenAI / LangChain / Custom / RL            │
└────────────────────┬────────────────────────────────┘
                     │ HTTP/JSON
┌────────────────────▼────────────────────────────────┐
│                  nttd API Server                     │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ Gameloop │  │ Observ-  │  │ Action Validator  │  │
│  │ Manager  │  │ ation    │  │ + Executor        │  │
│  │          │  │ Toolkit  │  │                   │  │
│  └────┬─────┘  └────┬─────┘  └────────┬──────────┘  │
│       │              │                 │             │
│  ┌────▼──────────────▼─────────────────▼──────────┐  │
│  │           AdminClient (async TCP)              │  │
│  │        correlation IDs + chunked messages      │  │
│  └────────────────────┬───────────────────────────┘  │
└───────────────────────┼─────────────────────────────┘
                        │ Admin Port (TCP)
┌───────────────────────▼─────────────────────────────┐
│              OpenTTD Dedicated Server                 │
│  ┌─────────────────────────────────────────────────┐ │
│  │          nttd GameScript (Squirrel)             │ │
│  │   90+ commands: queries, builds, vehicles,      │ │
│  │   orders, pathfinding, smart finders            │ │
│  └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

Key design decisions:

1. **OpenTTD is the source of truth.** nttd never caches or duplicates game state. Every observation is a fresh query.
2. **Agents are external clients.** No adapters, no framework-specific code inside nttd. The server publishes JSON schemas; agents conform to them.
3. **GameScript does the heavy lifting.** 90+ commands implemented in Squirrel, including smart finders that use `GSTestMode` for dry-run validation.
4. **One admin connection per session, multiplexed.** All agent requests go through a single `AdminClient` with correlation IDs, enabling safe concurrent access.

---

## The Observe-Decide-Act Cycle

Each agent runs an autonomous cycle loop:

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│ OBSERVE  │────▶│  DECIDE  │────▶│   ACT    │────▶│  TRACK   │
│          │     │          │     │          │     │          │
│ Compact  │     │ LLM call │     │ Validate │     │ Record   │
│ game     │     │ with 31  │     │ + execute│     │ cycle    │
│ state    │     │ tools    │     │ via GS   │     │ metrics  │
└──────────┘     └──────────┘     └──────────┘     └──────────┘
                      │ ▲
                      │ │  Multi-turn tool calling
                      ▼ │  (observe tools during decide)
                 ┌──────────┐
                 │  TOOLS   │
                 │ get_towns│
                 │ find_*   │
                 │ get_*    │
                 └──────────┘
```

### Observe

The agent receives a compact JSON snapshot of the game state scoped to its company: vehicles, stations, balance, profit, in-game date. This is cheap (~1 GS call) and provides the baseline context.

### Decide (multi-turn)

The LLM receives the observation plus its conversation history. It can call any of 31 observation tools to gather more information before committing to actions. This is where the real reasoning happens:

- **Bus agent**: "Which towns are closest? Where can I build stops?"
- **Rail agent**: "Which industries produce coal? Where's flat land near them?"
- **Air agent**: "What are the two largest towns? Can I build airports there?"
- **Water agent**: "Which towns are on the coast? Where can I build docks?"

The multi-turn loop continues until the LLM responds with a final JSON action list instead of more tool calls.

### Act

Actions are validated against a whitelist, then executed via the GameScript bridge. Each action returns success/failure with error details, which feed back into the agent's conversation history for learning.

### Track

Every cycle records: timing (decide_ms, cycle_ms), actions attempted/succeeded/failed, tool calls made. These are stored in-memory and optionally flushed to SQLite for cross-session analysis.

---

## Transport Specialists

We built four transport-type-specific agent prompts, each encoding domain expertise about its transport mode:

### Bus Agent
**Strategy**: Connect towns with road vehicles.
**Typical first moves**: Find two nearby towns → build bus stops → build road depot → connect with road → buy bus → set orders → start.
**Strength**: Low capital, forgiving terrain requirements.

### Rail Agent
**Strategy**: Connect industries via trains (coal→power station, farm→factory).
**Typical first moves**: Find industry pairs → scout flat land near them (`find_flat_spots`) → build rail depot → build stations → lay track → signals → buy train → orders → start.
**Challenge**: Rail needs contiguous track on flat terrain. Signals required for bidirectional. Most complex build sequence.

### Air Agent
**Strategy**: Build airports in the two largest towns, run passenger aircraft.
**Typical first moves**: `get_towns` → pick top 2 by population → `find_airport_spots` (GSTestMode-validated) → build airports → `get_hangars` → buy aircraft → orders → start.
**Challenge**: Airports need flat rectangular areas. High capital cost. Town authority approval required.

### Water Agent
**Strategy**: Connect coastal towns via ships.
**Typical first moves**: `get_towns` → find coastal towns → `find_dock_spots` (GSTestMode-validated) → build docks → `find_water_depot_spots` → build depot → buy ship → orders → start.
**Challenge**: Not all maps have useful waterways. Ships are slow. Dock placement requires specific coast tile orientations.

---

## Smart Finder Tools: GSTestMode Dry-Run Validation

One of the most impactful additions was the smart finder tools. Early agent runs had high failure rates because agents would pick tiles that looked valid on paper but failed OpenTTD's strict placement requirements (wrong slope, occupied tile, insufficient flat area).

The solution: **dry-run validation using OpenTTD's `GSTestMode()`**. When the GameScript enters test mode, build commands check all preconditions without actually building anything. We use this to:

1. Scan tiles in a radius around a target (town or industry)
2. Attempt a build in test mode for each candidate tile
3. Return only tiles that passed the dry-run

This guarantees that coordinates returned by `find_airport_spots`, `find_dock_spots`, and `find_water_depot_spots` will succeed when the agent builds there. The effect on success rates was dramatic.

```squirrel
// Simplified example from CmdFindAirportSpots
local test = GSTestMode();
foreach (tile in candidates) {
    if (GSAirport.BuildAirport(tile, airport_type, GSStation.STATION_NEW)) {
        results.append({ tile = tile, x = GSMap.GetTileX(tile), y = GSMap.GetTileY(tile) });
    }
}
```

---

## Multi-Agent Test Results

We ran all three transport agents (rail, air, water) simultaneously on the **same company** for 5 minutes using GPT-5.2 via the OpenAI adapter. This tests both the gameloop's ability to manage concurrent agents and the LLM's ability to reason about a shared company state.

### Session Summary

| Metric | Value |
|--------|-------|
| Session ID | `ses_524399c17ed1` |
| Duration | 5 minutes |
| Model | GPT-5.2 (OpenAI adapter) |
| Company | 0 (shared by all 3 agents) |
| Map size | 256x256 |
| Total cycles | 114 |
| Total actions | 226 |
| Actions succeeded | 165 |
| Actions failed | 61 |
| Overall success rate | 73.0% |

### Per-Agent Breakdown

| Agent | Cycles | Actions | Succeeded | Failed | Success Rate | Avg Cycle (ms) | Avg Decide (ms) |
|-------|--------|---------|-----------|--------|-------------|----------------|-----------------|
| Rail | 31 | 57 | 41 | 16 | 71.9% | 7,923 | 7,828 |
| Air | 42 | 99 | 70 | 29 | 70.7% | 4,548 | 4,430 |
| Water | 41 | 70 | 54 | 16 | 77.1% | 4,793 | 4,694 |

### Observations

1. **Air agent was most prolific** (99 actions in 42 cycles), likely because airport construction is a simpler build sequence than rail.

2. **Water agent had the highest success rate** (77.1%), benefiting from `find_dock_spots` and `find_water_depot_spots` dry-run validation.

3. **Rail agent was slowest** (7.9s avg cycle vs ~4.5s for air/water), reflecting the complexity of rail reasoning: finding industry pairs, computing track paths, placing signals.

4. **All agents ran without interference** despite sharing company 0. Actions are serialized through the GS bridge, so there were no race conditions. Each agent maintained its own conversation history and cycle state.

5. **Company financials**: Starting balance of ~100,000. After 5 minutes, balance was 47,383 with infrastructure worth ~55-67K in company value. The agents were actively spending on infrastructure but hadn't yet reached profitability (expected, since transport routes take time to generate revenue).

6. **Zero last_error on all agents**: no crashes, no unhandled exceptions, no cycle failures. The gameloop was stable throughout.

### Cycle Timing Distribution

Decide time dominates cycle time (~99%), which is expected since execution is a fast GS round-trip. The LLM reasoning (especially multi-turn tool calling) is the bottleneck.

- Rail: 7.8s decide / 7.9s total (slow due to complex spatial reasoning)
- Air: 4.4s decide / 4.5s total (faster, simpler build patterns)
- Water: 4.7s decide / 4.8s total (moderate complexity)

---

## What We Learned

### What worked well

- **Agent-agnostic design**: Swapping between OpenAI and LangChain adapters required zero changes to the gameloop or GS layer.
- **Multi-turn tool calling**: Letting agents query game state during the decide phase dramatically improved action quality compared to single-shot prompting.
- **GSTestMode dry-run validation**: Eliminated an entire class of "valid-looking but invalid" tile placement failures.
- **Transport-specific prompts**: Domain expertise encoded in prompts (e.g., "airports need flat rectangular areas", "docks need coast tiles") prevented agents from wasting cycles on impossible builds.
- **Shared company multi-agent**: Three agents on one company worked without coordination: each focused on its transport mode, and the GS serialization prevented conflicts.

### What needs improvement

- **Rail agent complexity**: Rail builds have the longest action sequences (depot → station → track × N → signal × N → station → vehicle → orders → start). The LLM sometimes loses track mid-sequence.
- **Water agent tile confusion**: Even with smart finders returning correct tiles, the LLM occasionally uses tiles from the wrong tool result (e.g., dock tiles instead of water depot tiles).
- **No inter-agent coordination**: The three agents don't know about each other. They might build redundant infrastructure or compete for the same loan capacity.
- **Profitability tracking**: Agents currently optimize for "build infrastructure" without feedback on whether routes are actually profitable.

---

## What's Next

1. **Inter-agent communication**: A shared message bus so agents can coordinate ("I'm building the airport, you handle the bus feeder route").
2. **Profitability-driven cycles**: Inject revenue/profit data into the observation so agents learn to optimize existing routes, not just build new ones.
3. **Reinforcement learning**: Use the cycle records and action outcomes as training data for RL policies that complement LLM reasoning.
4. **Leaderboard and benchmarking**: Cross-session comparison of agent performance with different models, prompts, and strategies.
5. **Human co-play**: Run agents alongside human players in the same game, with agents handling specific transport modes.

---

*Built with nttd, an agent-agnostic API server for OpenTTD. Agents connect, observe, and act via published JSON schemas. No adapters, no framework lock-in.*
