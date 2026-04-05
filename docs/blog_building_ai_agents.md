# Building and Benchmarking AI Agents That can Manage Large and Complex Business Empires

*An open benchmarking platform for multi-agent system evaluation in complex real-time environments*

---

## 1. Introduction

Large language models are increasingly deployed as autonomous agents that observe environments, reason about state, and take actions. Evaluating these capabilities requires benchmarks that go beyond static question answering: environments with continuous state evolution, multi-step planning requirements, resource constraints, and real consequences for suboptimal decisions.

**OpenTTD** (the open-source reimplementation of Transport Tycoon Deluxe) is a real-time strategy game where players build transport networks connecting towns and industries. It demands long-horizon planning, resource management, spatial reasoning, and adaptation to a dynamic economy. These properties make it a compelling evaluation environment for LLM-powered agents.

**nttd** is an agent-agnostic API server that wraps OpenTTD as an AI simulation environment. Agents connect via HTTP, observe game state through structured JSON, and submit actions, all without touching OpenTTD internals. Any system that speaks JSON over HTTP can be an agent: LangChain, OpenAI function calling, AutoGen, a plain Python script, or a reinforcement learning policy.

This report describes the architecture, the observe-decide-act gameloop, transport-specific agent design, and presents results from four test sessions: three single-agent sessions (one per transport type) and one multi-agent cooperative session where three specialized agents (rail, air, water) operated simultaneously on a shared company.

---

## 2. Project Goals

nttd is designed as an open benchmarking and experimentation platform with several research and practical objectives:

### 2.1 Multi-Agent Systems Research

Test how multiple specialized agents cooperate (or compete) while managing a shared business empire. Agents share resources (capital, loan capacity, company reputation) and must implicitly coordinate through the shared game state. This enables research into emergent coordination, resource contention, and specialization strategies without requiring explicit inter-agent communication protocols.

### 2.2 LLM Benchmarking with Controlled Variables

Provide a reproducible environment for comparing different LLMs on identical tasks. By fixing the map seed, starting conditions, game speed, transport type, and system prompt, researchers can isolate model capability as the independent variable. The structured cycle metrics (decide time, action success rate, actions per cycle) provide quantitative comparison axes that go beyond pass/fail benchmarks.

### 2.3 Open-Source and Small Model Evaluation

The agent-agnostic HTTP/JSON interface means any model that can generate structured output can be tested, including open-source models (Llama, Mistral, Qwen), small/quantized models, and locally hosted models. This lowers the barrier for researchers who want to evaluate models without vendor lock-in.

### 2.4 Prompt Engineering and Strategy Optimization

The system prompt is a first-class configuration parameter. Researchers can modify transport-specific prompts, adjust the multi-turn tool-calling guide, change observation formats, and test different strategy encodings to find optimal configurations for each model and transport type.

### 2.5 Hybrid AI Architectures

By exposing both a real-time observation API and a structured action interface, nttd supports hybrid architectures where LLM reasoning is combined with classical algorithms. For example, an RL policy for pathfinding paired with an LLM for strategic planning, or a rule-based system for low-level actions with an LLM for high-level goals.

### 2.6 Reproducible Evaluation Infrastructure

All cycle data (timing, actions, success rates) is recorded to SQLite with session-level isolation. Sessions can be replayed, compared, and analyzed programmatically. The leaderboard system computes cross-session rankings for competitive evaluation.

### 2.7 Human-AI Co-Play

Run agents alongside human players in the same game. Agents handle specific transport modes while humans manage others, enabling research into human-AI teaming, trust calibration, and complementary capability assessment.

---

## 3. Architecture

### 3.1 System Overview

```
+-----------------------------------------------------+
|               Agent (any framework)                 |
|         OpenAI / LangChain / Custom / RL            |
+--------------------+--------------------------------+
                     | HTTP/JSON
+--------------------v--------------------------------+
|                  nttd API Server                    |
|  +----------+  +----------+  +-------------------+  |
|  | Gameloop |  | Observ-  |  | Action Validator  |  |
|  | Manager  |  | ation    |  | + Executor        |  |
|  |          |  | Toolkit  |  |                   |  |
|  +----+-----+  +----+-----+  +--------+----------+  |
|       |             |                 |             |
|  +----v-------------v-----------------v----------+  |
|  |           AdminClient (async TCP)             |  |
|  |        correlation IDs + chunked messages     |  |
|  +--------------------+--------------------------+  |
+-----------------------|-----------------------------+
                        | Admin Port (TCP)
+-----------------------v-----------------------------+
|              OpenTTD Dedicated Server               |
|  +------------------------------------------------+ |
|  |          nttd GameScript (Squirrel)            | |
|  |   90+ commands: queries, builds, vehicles,     | |
|  |   orders, pathfinding, smart finders           | |
|  +------------------------------------------------+ |
+-----------------------------------------------------+
```

### 3.2 Key Design Decisions

1. **OpenTTD is the source of truth.** nttd never caches or duplicates game state. Every observation is a fresh query to the GameScript.
2. **Agents are external clients.** No adapters, no framework-specific code inside nttd. The server publishes JSON schemas; agents conform to them.
3. **GameScript does the heavy lifting.** 90+ commands implemented in Squirrel, including smart finders that use `GSTestMode` for dry-run validation.
4. **One admin connection per session, multiplexed.** All agent requests go through a single `AdminClient` with correlation IDs, enabling safe concurrent access from multiple agents.
5. **Session isolation.** Each session spawns its own OpenTTD server process with dedicated ports, configuration, and database records. Multiple sessions can run simultaneously.

---

## 4. The Observe-Decide-Act Cycle

Each agent runs an autonomous cycle loop with four phases:

```
+----------+     +----------+     +----------+     +----------+
| OBSERVE  |---->|  DECIDE  |---->|   ACT    |---->|  TRACK   |
|          |     | Agent:   |     |          |     |          |
| Compact  |     | LLM call |     | Validate |     | Record   |
| game     |     | with     |     | + execute|     | cycle    |
| state    |     | tools    |     | via GS   |     | metrics  |
+----------+     +----------+     +----------+     +----------+
                      | ^
                      | |  Multi-turn tool calling
                      v |  (observe tools during decide)
                 +----------+
                 |  TOOLS   |
                 | get_towns|
                 | find_*   |
                 | get_*    |
                 +----------+
```

### 4.1 Observe

The agent receives a compact JSON snapshot of the game state scoped to its company: vehicle count, station count, balance, profit, loan, and in-game date. This is a single GS round-trip (~1ms) and provides the baseline context for each decision cycle.

### 4.2 Decide (Multi-Turn Tool Calling)

The Agent receives the observation plus its full conversation history. It can call any of 31 observation tools to gather more information before committing to actions. This multi-turn loop continues until the Agent responds with a final JSON action list instead of more tool calls.

Example tool-calling sequences observed during testing:

- **Rail agent**: `get_industries` (find coal mines and power stations) -> `get_tile_info` (scout terrain near industry) -> `find_flat_spots` (validate buildable locations) -> `get_engines(vehicle_type=0)` (list available trains) -> `get_rail_types` -> submit build actions
- **Air agent**: `get_towns` (find largest towns by population) -> `find_airport_spots` (GSTestMode-validated flat areas) -> `get_engines(vehicle_type=3)` (list aircraft) -> submit build actions
- **Water agent**: `get_towns` -> `find_dock_spots` (GSTestMode-validated coast tiles) -> `find_water_depot_spots` -> `get_engines(vehicle_type=2)` (list ships) -> submit build actions

### 4.3 Act

Actions are validated against a whitelist of permitted action types, then executed sequentially via the GameScript bridge. Each action returns a success/failure result with error details, which feed back into the agent's conversation history. This error feedback enables the agent to adapt its strategy in subsequent cycles.

### 4.4 Track

Every cycle records structured metrics: timing breakdown (observe_ms, decide_ms, execute_ms, total_ms), action counts (proposed, executed, succeeded, failed), and observation size. These are stored in-memory during the session and flushed to SQLite for persistent cross-session analysis.

---

## 5. Transport Specialist Agents

We designed four transport-type-specific agent prompts, each encoding domain expertise about its transport mode. The system prompt serves as a strategy guide: it tells the Agent which tools to use, what action sequences to follow, and what pitfalls to avoid.

### 5.1 Road Transport Agent

**Strategy**: Connect nearby towns with road vehicles for passenger transport.

**Typical action sequence**: Find two nearby towns -> build bus stops in each -> build road depot -> connect towns with road -> buy bus -> set orders (town A stop, town B stop) -> start vehicle.

**Characteristics**: Lowest capital requirement among all transport types. Road construction is forgiving (follows terrain automatically). Smallest vehicles, so revenue per vehicle is low but fleet scaling is easy.

### 5.2 Rail Agent

**Strategy**: Connect industries via trains (coal to power station, farm to factory, etc.).

**Typical action sequence**: Find industry pairs -> scout flat land near industries (`find_flat_spots`) -> build rail depot -> build source station -> lay track segments -> build destination station -> place signals at intervals -> buy train with appropriate wagons -> set orders -> start.

**Characteristics**: Most complex build sequence of all transport types. Rail requires contiguous track on compatible terrain. Signals are required for bidirectional traffic. The Agent must manage a 10+ action sequence where each step depends on the previous one. Highest revenue potential per vehicle.

### 5.3 Air Agent

**Strategy**: Build airports in the two largest towns, run passenger aircraft between them.

**Typical action sequence**: `get_towns` -> pick top 2 by population -> `find_airport_spots` (GSTestMode-validated) -> build airports -> buy aircraft (airport tile serves as depot) -> set orders -> start.

**Characteristics**: Simplest build sequence (2 airports + 1 vehicle). Highest capital cost per infrastructure unit. Town authority approval required. Airports need flat rectangular areas of specific dimensions (varies by airport type).

### 5.4 Water Agent

**Strategy**: Connect coastal towns or industries via ships.

**Typical action sequence**: `get_towns` -> find coastal towns -> `find_dock_spots` (GSTestMode-validated) -> build docks -> `find_water_depot_spots` -> build water depot -> buy ship -> set orders -> start. Optionally build buoys for long-distance routes.

**Characteristics**: Moderate complexity. Dock placement requires specific coast tile orientations. Ships are the slowest vehicle type but have low operating costs. Water depot must be on a water tile, not a coast tile. Not all maps have useful waterways.

---

## 6. Smart Finder Tools: GSTestMode Dry-Run Validation

One of the most impactful design decisions was the implementation of smart finder tools using OpenTTD's `GSTestMode()`. Early agent runs showed high failure rates because agents would select tiles that appeared valid based on coordinate proximity but failed OpenTTD's strict placement requirements (wrong slope, occupied tile, insufficient flat area, incorrect coast orientation).

### 6.1 Mechanism

When the GameScript enters test mode, build commands check all preconditions (terrain, ownership, clearance) without actually building anything or spending money. The smart finder tools use this to:

1. Define a search radius around a target location (town center or industry tile)
2. Iterate over candidate tiles within that radius
3. Attempt a build command in test mode for each candidate
4. Return only tiles where the dry-run succeeded

This guarantees that coordinates returned by `find_airport_spots`, `find_dock_spots`, `find_water_depot_spots`, `find_bus_stop_spots`, and `find_flat_spots` will succeed when the agent builds there (assuming no other agent builds on the same tile between the query and the action).

### 6.2 Implementation

```squirrel
// Simplified example from CmdFindAirportSpots
local test = GSTestMode();
foreach (tile in candidates) {
    if (GSAirport.BuildAirport(tile, airport_type, GSStation.STATION_NEW)) {
        results.append({ tile = tile, x = GSMap.GetTileX(tile), y = GSMap.GetTileY(tile) });
    }
}
```

### 6.3 Impact on Success Rates

The effect on action success rates was substantial. Before smart finders, agents frequently wasted cycles attempting builds at invalid locations. After introducing dry-run validation, the primary causes of action failure shifted from "invalid tile" errors to higher-level issues like insufficient funds or incorrect action parameters, indicating that the spatial reasoning bottleneck was largely resolved.

---

## 7. Experimental Setup

### 7.1 Test Configuration

We conducted four test sessions to evaluate each transport-type agent individually and then all three operating cooperatively on a shared company. All sessions used GPT-5.2 as the underlying model, a 256x256 map, and the compact observation mode.

| Parameter | Single-Agent Sessions | Multi-Agent Session |
|-----------|----------------------|---------------------|
| Session IDs | ses_423b (rail), ses_be86 (air), ses_4a48 (water) | ses_524399c17ed1 |
| Duration | ~5 minutes each | 5 minutes |
| Model | GPT-5.2 | GPT-5.2 |
| Adapter | LangChain (rail, air), OpenAI (water) | OpenAI |
| Company | Exclusive | Shared by all 3 |
| Map size | 256 x 256 tiles | 256 x 256 tiles |
| Observation mode | Compact | Compact |
| Starting capital | ~100,000 | ~100,000 |

### 7.2 Single-Agent Sessions

Each single-agent session ran one transport-type agent in isolation, giving it exclusive access to the company's resources. These sessions establish baseline performance for each agent type without resource contention or shared-state complexity.

### 7.3 Multi-Agent Session

The multi-agent session registered all three agents (rail, air, water) to company 0 and started them within 1 second of each other. Each agent maintained its own conversation history, cycle state, and Agent session. Actions were serialized through the GameScript bridge using correlation IDs, preventing race conditions.

---

## 8. Results

### 8.1 Performance Summary

The following table presents all core metrics across the four test sessions. Single-agent sessions ran each transport type in isolation; the multi-agent session ran all three on a shared company simultaneously.

| Metric | Rail Solo | Rail Multi | Air Solo | Air Multi | Water Solo | Water Multi |
|--------|-----------|------------|----------|-----------|------------|-------------|
| Cycles | 17 | 31 | 28 | 42 | 14 | 41 |
| Total actions | 14 | 57 | 32 | 99 | 10 | 70 |
| Actions succeeded | 12 | 41 | 11 | 70 | 8 | 54 |
| Actions failed | 2 | 16 | 21 | 29 | 2 | 16 |
| **Success rate** | **85.7%** | **71.9%** | **34.4%** | **70.7%** | **80.0%** | **77.1%** |
| Avg decide time (ms) | 5,100 | 7,828 | 4,931 | 4,430 | 3,424 | 4,694 |
| Decide time range (ms) | 1,458 - 11,155 | 2,600 - 20,971 | 1,707 - 9,650 | 2,086 - 20,319 | 1,342 - 9,092 | 2,090 - 24,053 |
| Avg execute time (ms) | 36.0 | 94.8 | 29.4 | 118.8 | 29.8 | 98.7 |
| Actions per cycle | 0.8 | 1.8 | 1.1 | 2.4 | 0.7 | 1.7 |
| Zero-action cycles | 52.9% | 22.6% | 42.9% | 19.0% | 71.4% | 24.4% |

**Multi-agent session aggregate**: 114 total cycles, 226 actions attempted, 165 succeeded, 61 failed (73.0% overall success rate). 198 in-game days elapsed. Zero crashes, zero unhandled exceptions across all agents.

### 8.2 Single-Agent Behavioral Profiles

**Rail agent** showed the highest solo success rate (85.7%) despite operating in the most complex transport domain. Over half its cycles (52.9%) were observation-only, suggesting a cautious "gather then act" strategy. The average decide time of 5.1 seconds reflects the complexity of rail reasoning: industry pair selection, terrain scouting, multi-segment track planning.

**Air agent** attempted the most actions per cycle (1.1) but achieved the lowest solo success rate (34.4%). Its primary failure mode was attempting airport construction at self-selected tile coordinates instead of using validated results from `find_airport_spots`. This "overriding the tool" behavior represents a prompt adherence issue rather than a platform limitation.

**Water agent** was the fastest decision-maker (3.4s avg) and the most observation-heavy (71.4% zero-action cycles). Its conservative approach yielded 80.0% accuracy. The water agent benefited strongly from `find_dock_spots` and `find_water_depot_spots`, which validated coast tile orientations via GSTestMode.

### 8.3 Solo-to-Multi Behavioral Shifts

**All agents were more active in the multi-agent session.** Actions per cycle increased 2-2.5x across the board, and zero-action cycles dropped from 43-71% (solo) to 19-24% (multi). The presence of other agents (visible through shared company state changes) may create implicit pressure to act rather than only observe.

**Air agent improved dramatically** (34.4% to 70.7%). This is partly due to the adapter switch (LangChain to OpenAI) and prompt refinements between sessions. It also produced 3x more actions, shifting from hesitant to productive behavior.

**Rail agent traded accuracy for throughput.** Success rate decreased from 85.7% to 71.9%, while total actions increased 4x. The rail agent was less cautious in the multi-agent session. Its decide time also increased from 5.1s to 7.8s (+53%), likely reflecting the additional complexity of reasoning about shared company state.

**Water agent maintained stable performance.** Success rate held at 77-80% while scaling from 10 to 70 total actions, making it the most robust to the multi-agent environment.

### 8.4 Success Rate Over Time

To understand whether agents improved or degraded as sessions progressed, we analyzed success rates across early, mid, and late phases.

**Single-Agent Sessions:**

| Phase | Rail | Air | Water |
|-------|------|-----|-------|
| Early (cycles 1-5) | 80.0% (4/5) | 33.3% (3/9) | 60.0% (3/5) |
| Mid (cycles 6-10) | 83.3% (5/6) | 42.9% (6/14) | N/A (0 actions) |
| Late (cycles 11+) | 100.0% (3/3) | 22.2% (2/9) | 100.0% (5/5) |

**Multi-Agent Session:**

| Phase | Rail | Air | Water |
|-------|------|-----|-------|
| Early (cycles 1-10) | 84.6% (11/13) | 100.0% (15/15) | 64.3% (9/14) |
| Mid (cycles 11-20) | 71.4% (15/21) | 59.4% (19/32) | 100.0% (17/17) |
| Late (cycles 21+) | 65.2% (15/23) | 69.2% (36/52) | 71.8% (28/39) |

Rail and water agents improved over time in solo sessions (both reaching 100% in late phases), suggesting they learned from early failures via conversation history. The air agent degraded (33.3% to 22.2%), indicating it did not adapt to repeated airport placement failures.

In the multi-agent session, rail showed declining success as it attempted increasingly complex operations (signal placement, track routing around obstacles). Air had a perfect early phase during initial airport construction, then dropped as it tried to expand. Water showed a non-monotonic pattern with a perfect mid-phase, suggesting it successfully identified viable coastal sites through early exploration.

### 8.5 Timing Analysis

Decide time (the Agent reasoning phase, including multi-turn tool calling) dominates cycle time at 97-99% of total duration. Execution (the GS round-trip) is negligible.

| Component | Rail | Air | Water |
|-----------|------|-----|-------|
| Decide time share | 98.8% | 97.4% | 97.9% |
| Execute time share | 1.2% | 2.6% | 2.1% |

The rail agent's multi-agent decide time (7,828ms) is 1.77x slower than air (4,430ms), reflecting rail's greater reasoning complexity. All agents exhibited high-variance decide times with occasional spikes to 20-24 seconds during extended multi-turn tool-calling sequences.

Decide time increased for rail (+53%) and water (+37%) in multi-agent mode, as observations now include infrastructure built by other agents. Air decreased slightly (4.9s to 4.4s), possibly due to the adapter switch.

### 8.6 Multi-Agent Action Distribution

| Actions per cycle | Rail | Air | Water |
|-------------------|------|-----|-------|
| 0 (observation only) | 7 | 8 | 10 |
| 1-3 actions | 17 | 28 | 23 |
| 4-6 actions | 6 | 4 | 8 |
| 7+ actions | 1 | 2 | 0 |

The air agent produced the highest-action cycles (up to 10), typically when building an airport and immediately purchasing and configuring an aircraft in a single decision. Rail's complex build sequences were spread across multiple cycles rather than batched.

### 8.7 Multi-Agent Session Economics

| Financial Metric | Value |
|------------------|-------|
| Starting balance | ~100,000 |
| End balance | 47,383 |
| Capital spent | ~52,617 |
| Company value | ~55,000 - 67,000 |

The agents invested heavily in infrastructure but had not yet reached profitability within the 5-minute window. Transport routes in OpenTTD require time for vehicles to complete journeys and generate revenue. A longer session (15-30 minutes) would be needed to assess revenue capability.

---

## 9. Discussion

### 9.1 What Worked Well

**Agent-agnostic design.** Swapping between the OpenAI and LangChain adapters required zero changes to the gameloop or GS layer. The adapter interface cleanly separates LLM-specific concerns from the core simulation loop.

**Multi-turn tool calling.** Letting agents query game state during the decide phase improved action quality compared to single-shot prompting. Agents that used 2-3 tool calls before acting showed higher success rates than cycles where the agent acted immediately from the compact observation alone.

**GSTestMode dry-run validation.** The smart finder tools eliminated an entire class of "valid-looking but invalid" tile placement failures. By guaranteeing that returned coordinates will succeed, we shifted failure modes from spatial errors to higher-level strategic issues.

**Transport-specific prompts.** Domain expertise encoded in prompts (e.g., "airports need flat rectangular areas", "docks need coast tiles with specific orientations") prevented agents from wasting cycles on impossible builds.

**Shared company multi-agent.** Three agents operating on one company worked without explicit coordination. Each focused on its transport mode, and the GS-level action serialization prevented conflicts. Implicit coordination emerged through the shared financial state: when one agent spent heavily, others observed the reduced balance in subsequent observations.

### 9.2 Known Limitations and Open Issues

**Rail agent complexity (GitHub issue #1).** Rail builds have the longest action sequences (depot, station, track segments, signals, station, vehicle, orders, start). The Agent sometimes loses track of its position in the sequence, and the 65.2% late-phase success rate in the multi-agent session suggests degradation as build complexity increases.

**Air agent tile override behavior (GitHub issue related).** In the single-agent session, the air agent ignored validated `find_airport_spots` coordinates in favor of self-selected tiles, resulting in a 34.4% success rate. This "overriding the tool" behavior improved in the multi-agent session (70.7%) after prompt refinements, but remains a risk.

**Water agent tile confusion (GitHub issue #2).** Even with smart finders returning validated tiles, the Agent occasionally uses tiles from the wrong tool result (e.g., dock coordinates when water depot coordinates were needed). This is a context management issue in the Agent.

**No inter-agent coordination (GitHub issue #4).** The three agents do not know about each other. They can build redundant infrastructure or compete for the same loan capacity. A shared message bus would enable explicit cooperation.

**Agents lack profitability feedback (GitHub issue #5).** Current agents optimize for "build infrastructure" without receiving feedback on whether routes are profitable. Injecting revenue data into the observation would shift behavior toward optimization rather than expansion.

**Analysis paralysis.** Some cycles result in zero actions: the agent uses observation tools repeatedly without committing to a build. This occurred in 19-24% of multi-agent cycles and 43-71% of single-agent cycles. The reduction in multi-agent mode is an interesting finding that warrants further investigation.

**DB recording gaps (GitHub issue #6).** The current recording layer captures cycle-level metrics (timing, action counts) but does not record individual action details (which action types, parameters, error messages). This limits post-session analysis to aggregate statistics. The per-action recording pipeline needs to be connected.

---

## 10. Future Directions

### 10.1 Inter-Agent Communication

Implement a shared message bus so agents can coordinate explicitly ("I am building the airport in town A; you handle the dock in the coastal town to the south"). This would enable research into the value of explicit vs. implicit coordination in multi-agent systems.

### 10.2 Profitability-Driven Cycles

Inject revenue and profit-per-route data into the compact observation so agents can optimize existing routes, not just build new ones. This shifts the evaluation from "can the agent build infrastructure?" to "can the agent run a profitable business?"

### 10.3 Reinforcement Learning Integration

Use the cycle records and action outcomes as training data for RL policies that complement Agent reasoning. A hybrid approach could use RL for low-level pathfinding and tile selection while the Agent handles high-level strategy.

### 10.4 Competitive Multi-Company Evaluation

Run agents from different models on separate companies in the same game. This creates a competitive benchmark where agents must respond to opponents' actions, compete for shared resources (industries, town growth), and adapt strategies in real time.

### 10.5 Longitudinal Sessions

Extend test sessions from 5 minutes to 30-60 minutes (or longer) to evaluate whether agents can sustain performance, adapt to changing game conditions (new industries appearing, towns growing), and achieve profitability.

### 10.6 Leaderboard and Public Benchmarking

Publish standardized benchmark configurations (map seed, game settings, agent type, duration) with a public leaderboard. This enables the community to submit results from any model and compare performance on equal footing.

### 10.7 Human-AI Co-Play Studies

Run agents alongside human players in the same game, with agents handling specific transport modes. This enables research into human-AI teaming and whether human oversight improves or hinders agent performance.

---

## 11. Reproducibility

All experiments described in this report can be reproduced using the nttd codebase. The key configuration for the multi-agent test:

```bash
# Start nttd API server
uv run uvicorn nttd.api.app:app --host 0.0.0.0 --port 8000

# Create and start a session
SESSION=$(curl -s -X POST http://localhost:8000/admin/sessions/new \
  -H "Content-Type: application/json" \
  -d '{"name": "multi-agent-test"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")

curl -s -X POST "http://localhost:8000/admin/sessions/$SESSION/start" \
  -H "Content-Type: application/json" \
  -d '{"agent_companies": 1}'

# Set mode and unpause
curl -s -X POST "http://localhost:8000/sessions/$SESSION/mode?mode=async_realtime"
curl -s -X POST "http://localhost:8000/sessions/$SESSION/unpause"

# Register and start three agents
for AGENT in rail air water; do
  curl -s -X POST "http://localhost:8000/sessions/$SESSION/gameloop/agents/register" \
    -H "Content-Type: application/json" \
    -d "{\"agent_id\": \"${AGENT}-agent\", \"company_id\": 0, \"agent_type\": \"$AGENT\",
         \"adapter\": \"openai\", \"model\": \"gpt-5.2\"}"
  curl -s -X POST "http://localhost:8000/sessions/$SESSION/gameloop/agents/${AGENT}-agent/start"
done

# After 5 minutes, stop all agents
for AGENT in rail air water; do
  curl -s -X POST "http://localhost:8000/sessions/$SESSION/gameloop/agents/${AGENT}-agent/stop"
done
```

Cycle data is automatically recorded to `nttd.db` and can be queried:

```sql
-- Per-agent summary for a session
SELECT agent_id, total_cycles, total_actions, successful_actions, failed_actions,
       ROUND(avg_cycle_ms, 1), ROUND(avg_decide_ms, 1)
FROM agent_connections
WHERE session_id = 'SESSION_ID';

-- Cycle-level detail for a specific agent
SELECT cycle_number, decide_ms, actions_succeeded, actions_failed
FROM agent_cycles
WHERE connection_id = 'SESSION_ID:0:AGENT_ID'
ORDER BY cycle_number;
```

---

## 12. Conclusion

nttd demonstrates that OpenTTD can serve as a rich, multi-dimensional evaluation environment for LLM-powered agents. The observe-decide-act gameloop with multi-turn tool calling enables agents to reason about complex spatial and economic state before committing to actions. Transport-specific prompts and GSTestMode dry-run validation address the two primary failure modes: strategic errors and spatial placement errors, respectively.

The most notable finding is the behavioral shift between solo and multi-agent conditions: all agents became 2-3x more active when operating on a shared company, with zero-action ("analysis paralysis") cycles dropping from 43-71% to 19-24%. Whether this is caused by implicit competitive pressure through shared state observation, or by the adapter/prompt changes between sessions, is a question for controlled follow-up experiments.

The platform's agent-agnostic design, structured metrics recording, and session isolation make it suitable for reproducible cross-model benchmarking. As Agent capabilities evolve, nttd provides a consistent, challenging environment where improvements in reasoning, planning, and spatial understanding translate directly into measurable performance gains.

---

*Built with nttd, an agent-agnostic API server for OpenTTD. Source code, documentation, and benchmark configurations available at github.com/deepsaia/nttd.*
