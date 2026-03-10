# `nttd` Architecture Report

## Purpose

`nttd` is a proposed control-plane, state-plane, and agent-facing API system for using **OpenTTD** as an AI-agent simulation environment. The goal is to support:

- Human-visible gameplay with full OpenTTD visuals
- LLM-powered single-agent or multi-agent systems
- Plug-and-play compatibility with multiple agent frameworks
- Three execution modes: heartbeat, async real-time, and assisted/co-pilot
- Gym-compatible and PettingZoo-compatible environments
- Fault-tolerant, replayable, benchmark-friendly operation
- Strong observability and structured logging

The core design principle is:

> **OpenTTD remains the simulation kernel and source of truth. `nttd` becomes the agent-facing operating system around it.**

---

## Bottom line

Yes — this can be built, but the right way to build `nttd` is **not** as a thin Python wrapper around the OpenTTD process. It should be a **control plane + state plane + agent-agnostic API server** that sits between OpenTTD and any agent system. Agents are external clients that connect via published schemas — `nttd` contains no agent-framework-specific code.

That gives you:

- fault tolerance
- plug-and-play agents (any system that speaks JSON over HTTP/WebSocket)
- better observability
- a clean path to both LLM-agent control and Gym/PettingZoo training
- complete decoupling from any agent framework

OpenTTD already gives you two important extension surfaces:

1. the **admin network** for remote control and subscriptions
2. the **AI/GameScript APIs** inside the game for in-world queries and actions

The admin network supports persistent external apps, remote console commands, and company/client information; importantly, admin clients stay connected across new games and save/load operations. The GameScript API can also act “as” a company using `GSCompanyMode`, so actions can be executed on behalf of a company rather than as a god-mode external process.

### Key source links

- OpenTTD admin network docs: <https://github.com/OpenTTD/OpenTTD/blob/master/docs/admin_network.md>
- OpenTTD admin network HTML docs: <https://andythenorth.github.io/OpenTTD/docs/admin_network.html>
- OpenTTD GameScript API: <https://docs.openttd.org/gs-api/>
- `GSController`: <https://docs.openttd.org/gs-api/classGSController>
- `GSCompanyMode`: <https://docs.openttd.org/gs-api/classGSCompanyMode>
- OpenTTD dedicated server guide: <https://wiki.openttd.org/en/Manual/Dedicated%20server>
- Server admin port overview: <https://wiki.openttd.org/en/Development/Server%20admin%20port>
- `pyOpenTTDAdmin`: <https://github.com/liki-mc/pyOpenTTDAdmin>
- `pyOpenTTDAdmin` on PyPI: <https://pypi.org/project/pyOpenTTDAdmin/>
- OpenTTDLab: <https://github.com/michalc/OpenTTDLab>
- OpenTTDLab on PyPI: <https://pypi.org/project/OpenTTDLab/>
- OpenTTDLab paper: <https://joss.theoj.org/papers/10.21105/joss.08014.pdf>
- TensorBoardX: <https://github.com/lanpa/tensorboardX>
- Plotly Dash docs: <https://dash.plotly.com/>

---

## The most important architectural decision

Do **not** let agents talk directly to OpenTTD primitives.

Instead, define a stable **`nttd` contract**:

- a normalized **observation schema** (published JSON, agents subscribe to it)
- a normalized **action schema** (published JSON, agents submit against it)
- an **agent connection API** (connect, subscribe, observe, act — no adapters)
- a **runtime loop** that can run in heartbeat, async real-time, or assisted mode

That way, any system — LangGraph, AutoGen, CrewAI, Neuro-SAN, Haystack, MCP-based agents, RL policies, or a plain Python script — can be an agent. `nttd` does not care what the agent is. It only validates the JSON contract.

A good reference pattern is a three-layer split:

- stateless tool layer
- persistent bridge server
- in-game script logic that actually performs commands and returns structured results

A recent third-party OpenTTD MCP server uses a similar split: MCP tool server → bridge server → OpenTTD admin port → GameScript, with JSON messages, chunking, and reconnect logic. This is useful as architectural validation, though not something I would treat as the final production dependency.

Reference:

- OpenTTD MCP project: <https://github.com/iNewLegend/openttd-mcp/blob/main/README.md>

---

# Recommended architecture for `nttd`

## 1) OpenTTD deployment model

Use OpenTTD in **multiplayer server mode** as the authoritative simulation, even for a single human plus AI.

OpenTTD supports dedicated server mode with `-D`, and the admin interface is only available when an admin password is configured. That gives you a stable, networked process boundary and avoids trying to automate a local desktop UI.

Reference:

- Dedicated server docs: <https://wiki.openttd.org/en/Manual/Dedicated%20server>
- Server admin port overview: <https://wiki.openttd.org/en/Development/Server%20admin%20port>
- Admin network docs: <https://github.com/OpenTTD/OpenTTD/blob/master/docs/admin_network.md>

### Variant A — best for production and evaluation

- OpenTTD runs as a **dedicated server**
- A human watches/joins through a normal OpenTTD client
- `nttd` connects through the admin port
- AI actions are executed through GameScript + admin port / rcon

This is the cleanest and most fault-tolerant layout.

### Variant B — good for local prototyping

- OpenTTD runs locally in hosted multiplayer mode
- Human is also the host
- `nttd` still uses admin port + GameScript

This is simpler for local experimentation, but less clean operationally.

### Recommendation

Build for **Variant A first**.

---

## 2) `nttd` internal components

### A. Game Bridge `[Feasible]`

This is the persistent service that holds the OpenTTD admin-port connection.

Responsibilities:

- authenticate to admin port
- subscribe to updates
- expose an internal event stream
- issue rcon commands
- manage reconnects
- buffer outbound commands and correlate replies

References:

- Admin network docs: <https://github.com/OpenTTD/OpenTTD/blob/master/docs/admin_network.md>
- `pyOpenTTDAdmin`: <https://github.com/liki-mc/pyOpenTTDAdmin>

### B. In-Game Execution Script `[Hard]`

This is a **GameScript** loaded into OpenTTD.

Responsibilities:

- run inside the game’s Squirrel VM
- query state not conveniently available over admin port
- execute company-scoped commands
- serialize results/errors back to the bridge
- optionally store minimal persistent state in savegames

> **Feasibility caveat:** Communication between the bridge and GameScript is indirect — via the admin port’s GameScript message channel. This is not a request/response RPC. Messages are fire-and-forget with size limits. Building a reliable query/response layer requires careful protocol design: correlation IDs, chunking for large payloads, and timeouts. The OpenTTD MCP project validated this is doable but non-trivial. Additionally, `GSCompanyMode` switches sequentially within a single GS instance — you cannot parallelize actions for multiple companies within one game tick.

References:

- GameScript API: <https://docs.openttd.org/gs-api/>
- `GSController`: <https://docs.openttd.org/gs-api/classGSController>
- `GSCompanyMode`: <https://docs.openttd.org/gs-api/classGSCompanyMode>

### C. State Service `[Hard]`

This normalizes raw game data into a consistent observation model:

- map topology
- towns, industries, cargo
- companies and finances
- vehicles, stations, routes
- current game date / tick
- recent deltas and events
- local tactical windows around relevant assets

This service should produce:

1. a **full canonical state**
2. a **delta stream**
3. **compressed views** for LLMs and RL agents

> **Feasibility caveat:** The admin port provides company info, economy stats, and chat — but does NOT provide tile-level map data, vehicle positions, station details, or industry states directly. Most of Layer 1's canonical full state requires GameScript queries. Serializing large state through the GS message channel is slow. Recommend lazy loading + caching: build the canonical world model once at session start, then update incrementally via targeted GS queries and admin port subscriptions.

### D. Action Service `[Feasible]`

This receives structured actions in JSON and turns them into validated commands.

Responsibilities:

- validate schema
- check permissions/company scope
- estimate cost/risk
- perform dry-run feasibility checks where possible
- split high-level actions into atomic action sequences
- execute with idempotency keys
- return action result + changed entities + errors

### E. Runtime Orchestrator `[Feasible]`

This decides how often observations are published and actions are accepted.

Responsibilities:

- heartbeat mode (for benchmarks, RL, evaluation)
- async real-time mode (for human co-play)
- assisted/co-pilot mode (human-triggered AI)
- per-agent budgets
- command timeouts
- arbitration when multiple agents produce actions
- fallback behavior

### F. Observability Plane `[Feasible]`

This is essential.

It should store:

- every observation snapshot and delta
- every action request
- validation results
- every command sent to OpenTTD
- action latency
- action success/failure
- agent thought summaries or structured rationales
- replay metadata
- benchmark metrics

---

# Known limitations and technical constraints

These are hard constraints imposed by OpenTTD's architecture that affect `nttd` design.

## 1. GameScript message channel is not RPC

Communication between the Python bridge and the in-game GameScript is indirect. Messages flow through the admin port's GameScript message channel, which is fire-and-forget with size limits. There is no built-in request/response correlation — you must build your own protocol layer with correlation IDs, chunking for large payloads, and timeouts. The OpenTTD MCP project demonstrates this is doable but adds significant protocol complexity.

## 2. Admin port has limited data

The admin port provides: server info, client/company lifecycle events, company economy/statistics, chat, console output, and GameScript messages. It does **not** provide: tile-level map data, vehicle positions/orders, station details, industry production, or cargo routing. All of these require GameScript queries.

## 3. Sequential GSCompanyMode

A single GameScript instance can use `GSCompanyMode` to act as different companies, but only **one at a time, sequentially**. You cannot parallelize actions for multiple companies within one game tick. This is fine for heartbeat mode (serialize decisions per company) but limits throughput in real-time multi-company scenarios.

## 4. Expensive derived views

Some proposed derived views are computationally expensive:
- `buildable_area_scan(region)`: requires iterating map tiles via GS — slow for large regions
- `cashflow_forecast(company_id)`: OpenTTD has no native forecast; must model from quarterly data
- Full canonical state: serializing the entire world through the GS message channel is prohibitive for large maps

**Mitigation:** Pre-compute expensive data at session start, cache aggressively, update incrementally.

## 5. Multiplayer pause is global

In OpenTTD multiplayer, pause/unpause affects ALL connected players. There is no per-player pause. This is why heartbeat mode is unsuitable for human co-play and why async real-time mode is necessary.

---

# The control problem: real-time vs heartbeat vs assisted

This is the most important design issue.

LLM agents are often too slow for true real-time play, but pausing the game constantly ruins the human co-play experience. `nttd` should have **three first-class modes**, each optimized for a different use case.

### Mode comparison

| | Heartbeat | Async Real-Time | Assisted/Co-Pilot |
|---|---|---|---|
| **Use case** | Benchmarks, RL training, evaluation | Human + AI co-play | Human requests AI help |
| **Game pauses for AI?** | Yes (hard pause) | Never | Only when human triggers |
| **Deterministic?** | Yes | No (async) | Partially |
| **Human experience** | Spectator or none | Smooth, uninterrupted | Natural co-pilot feel |
| **Best for LLMs?** | Yes | Yes (strategic cadence) | Yes |
| **Best for RL?** | Yes | No | No |

---

## Mode 1 — Heartbeat mode

**Best for: benchmarks, RL training, evaluation, Gym/PettingZoo.**

This should be the default when no human is actively playing, or the human is spectator-only.

Flow:

1. Pause the game
2. Capture stable state snapshot
3. Send observation to agent system
4. Agent returns structured actions
5. Validate and queue actions
6. Apply actions
7. Unpause / advance simulation window
8. Repeat

This is feasible because OpenTTD can be paused/unpaused through remote admin tooling and rcon-style commands; the admin interface supports remote console commands, and external admin bots already use pause/unpause and auto-pause flows.

Reference:

- Admin network docs: <https://github.com/OpenTTD/OpenTTD/blob/master/docs/admin_network.md>

### Why heartbeat mode is good

- deterministic snapshots
- easier debugging
- easier benchmarking
- works with slower LLM systems
- allows multi-agent deliberation
- better for replay and evaluation
- closer to Gym `step()` semantics

### Heartbeat variants

#### Hard pause heartbeat

Pause the game completely during decision-making.

#### Soft heartbeat

Do not fully pause, but only permit AI actions every N game days / N ticks.

#### Burst simulation heartbeat

Pause, plan, execute, unpause for a fixed in-game interval, pause again.

### Why heartbeat mode is wrong for human co-play

In OpenTTD multiplayer, **pause freezes ALL players**. If the AI needs to think for 5-30 seconds every game-month, the human experiences a freeze every ~30-60 seconds of real play. With multiple agent roles deliberating, each heartbeat could take minutes. The human would spend more time frozen than playing, destroying immersion.

### Recommendation

Use heartbeat mode for **benchmarks, RL, and evaluation only**. For human co-play, use Mode 2 or Mode 3 below.

---

## Mode 2 — Async real-time mode

**Best for: human + AI co-play, competitive multiplayer, demos.**

This is the recommended mode when a human is actively playing alongside AI companies.

Flow:

- game runs continuously at a configurable speed — **never pauses for AI**
- AI observes state periodically (every N game-days)
- AI thinks asynchronously while game continues running
- actions are submitted when ready and validated against current state
- game speed is the primary control knob (slower speed = more AI thinking time per game period)
- simple rule-based policies handle urgent tactical needs (vehicle stuck, depot routing)
- LLM handles strategic decisions on a slow cadence (every few game-months)
- human can manually pause if they want to wait for AI

### Why this works for a transport game

OpenTTD is a **strategic** game. You don't need millisecond-precision decisions. An AI that makes one good strategic decision every 3 game-months will outperform one that micromanages every tick. The world state doesn't change fast enough to invalidate most strategic plans.

### Handling stale observations

Because the AI decides on a snapshot that may be a few game-days old:

- the Action Service must **re-validate** actions against current state before execution
- build actions should check terrain/ownership are unchanged
- financial actions should check balance is sufficient
- if validation fails, the action is rejected and the agent is notified with fresh state

### Game speed as first-class control

OpenTTD supports multiple game speeds. This is a critical mechanism:

- **Slower game speed** = more wall-clock time per game-day = AI has more time to think
- **Faster game speed** = rapid simulation for training or fast-forward
- `nttd` should expose game speed as a configurable parameter per session
- in co-play mode, a moderate speed (1x or 0.5x) gives LLMs comfortable thinking time

### Tactical vs strategic split

In async mode, not all decisions should go through the LLM:

- **LLM (slow, strategic)**: route planning, expansion, capital allocation — every few game-months
- **Rule-based (fast, tactical)**: reroute stuck vehicles, send to depot, adjust frequency — continuous

This hybrid approach means the AI is responsive on routine matters even while the LLM is thinking about big decisions.

### Recommendation

Use async real-time as the **default for human co-play**. Limit active LLM agents to 2-3 maximum in this mode.

---

## Mode 3 — Assisted / co-pilot mode

**Best for: human-directed play, co-pilot experience, tutorials.**

This is the most natural mode when the human wants AI as an assistant rather than an autonomous player.

Flow:

- game runs normally under human control
- human explicitly requests AI help (e.g., "build me a profitable route from town X to Y")
- `nttd` pauses the game (human-initiated, so it doesn't feel intrusive)
- AI analyzes state, plans, and presents a proposal
- human reviews and approves/modifies/rejects
- AI executes approved plan
- game unpauses

### Why this is different from heartbeat

In heartbeat mode, pauses are system-initiated and happen on a fixed cadence. In assisted mode, pauses are **human-initiated** and happen only when the human asks for help. This preserves immersion because the human is in control of when the game freezes.

### Recommendation

Assisted mode is ideal for onboarding, tutorials, and scenarios where the human wants to stay in the driver's seat. It requires a communication channel between the human and the AI (chat, UI buttons, or hotkeys).

---

## Latency classes `[Phase 2+]`

Across all modes, do **not** expose raw access equally to all agent types. Use **latency classes**:

- **Strategic agents**: think every X days/months (LLM-powered)
- **Tactical agents**: think every few seconds or event triggers (rule-based or lightweight model)
- **Execution agents/policies**: react continuously (scripted policies)

This creates a hybrid multi-agent system where the LLM is not required to micromanage in real time.

---

# Recommended multi-agent design (reference for agent builders)

Since `nttd` is agent-agnostic, multi-agent orchestration lives **outside `nttd`**, in the agents' own codebase. However, `nttd` should be designed to support multi-agent patterns well. This section provides reference guidance for teams building agents against the `nttd` API.

The recommended pattern is a **role-based control hierarchy** rather than a swarm of generic agents.

> **Practical guidance:** Start with 2 connected agents (Planner + Executor). Each connects to `nttd` independently, subscribes to different observation channels, and submits its own actions. For async real-time human co-play, limit active LLM agents to 2-3 maximum to keep decision latency manageable.

## Reference role hierarchy

### 1. Executive Planner

- long-horizon strategy
- choose growth direction
- rail vs road vs air priorities
- capital allocation
- expansion timing

### 2. Network Planner

- select town/industry pairs
- choose transport mode
- propose corridors and route plans
- estimate ROI

### 3. Build/Execution Agent

- turn plan into actionable build commands
- find feasible build sites
- sequence track/station/depot/signal construction

### 4. Fleet Operations Agent

- buy/refit/sell vehicles
- assign and repair orders
- dispatch to depots
- capacity balancing

### 5. Finance/Risk Agent

- monitor loans, profitability, idle assets
- decide when to borrow, repay, prune routes
- alert on insolvency risk

### 6. Arbitration / Safety Controller

- final gatekeeper
- resolve conflicting actions
- enforce budgets and safety policies
- guarantee schema correctness

This separation maps well to multiple connected agents, each subscribing to different observation channels and submitting actions through the same `nttd` API. `nttd` does not enforce this hierarchy — it is a recommendation for agent builders.

---

# The API contract you should define

## Observation API

You want multiple endpoints, but don’t expose raw game internals first. Expose **three layers**.

### Layer 1 — Canonical full state `[Hard — requires GS message protocol]`

For debugging, replay, and RL data generation.

> **Feasibility caveat:** Most of these domains (map, stations, vehicles, industries) are NOT available through the admin port. They require GameScript queries serialized through the GS message channel, which has size limits and is not RPC-based. Full state extraction for large maps will be slow. **Recommended approach:** build the canonical model once at session start via a batch GS query sequence, then update incrementally using targeted queries and admin port subscriptions. Cache aggressively. Do not attempt full-state extraction every heartbeat.

Domains:

- `game`
- `map` (expensive — cache and update incrementally)
- `companies`
- `towns`
- `industries`
- `stations` (requires GS queries)
- `vehicles` (requires GS queries)
- `engines`
- `cargo`
- `events`
- `visibility`
- `economy`
- `agent_metadata`

### Layer 2 — Task-specific derived views

These are what agents should actually use.

Examples:

- `company_summary(company_id)`
- `route_candidates(company_id)`
- `town_pair_opportunities(company_id)`
- `idle_vehicle_report(company_id)`
- `station_congestion_report(company_id)`
- `cashflow_forecast(company_id)` (derived — OpenTTD has no native forecast; must be modeled from quarterly data)
- `buildable_area_scan(region)` (expensive — pre-compute at session start, update incrementally)
- `industry_supply_chain_snapshot(cargo_type)`

### Layer 3 — Delta/event stream `[Hard — most events require polling]`

Agents should rarely consume the whole world every cycle.

> **Feasibility caveat:** The admin port pushes only a limited set of events (company economy updates, client joins/quits, chat). Most game events listed below (industry production changes, vehicle stuck, station congestion) are NOT pushed by the admin port. These must be detected by polling via GameScript or by diffing snapshots. The event list below is the target; actual availability depends on the GS polling layer built in Phase 1.

Examples:

- company cash changed
- industry production changed
- vehicle lost / stuck / profitable / unprofitable
- station overcrowding threshold crossed
- loan threshold crossed
- route completed
- build failed
- competitor expanded nearby

This makes the system scalable.

---

## Subscription model for agent observation feeds `[Phase 1 — core to agent-agnostic design]`

> **This is a Phase 1 requirement.** The subscription model is how external agents connect to observations. Without it, agents cannot plug in. Phase 1 should support basic subscription registration (by entity type, event type, and cadence) via REST/WebSocket. Phase 2+ adds advanced features like region-based subscriptions, backpressure, and coalescing.

Every AI agent should be able to subscribe to one or more observation streams or derived statistics. This is a strong design choice and should be treated as a first-class capability.

### Why subscriptions matter

They let you support both of these patterns cleanly:

- **Single-agent mode**: one agent subscribes to all observation domains
- **Multi-agent mode**: different agents subscribe to different observation domains and operate concurrently

That enables faster processing because agents only receive the information they need.

### Recommended subscription types

Each agent should be able to subscribe by:

- **entity type**: vehicles, stations, towns, industries, companies
- **derived metric**: station congestion, profitability, loan pressure, idle assets, route opportunities
- **region/window**: map sub-regions or route corridors
- **event type**: build failures, production changes, cash threshold breaches
- **cadence**: every heartbeat, every N heartbeats, event-driven only, or continuous streaming
- **priority**: high-priority streams such as bankruptcy risk or route failure alerts

### Recommended implementation

Use a pub/sub layer inside `nttd`:

- state service publishes normalized events and derived updates
- external agents register subscriptions via the API
- observation router fans out relevant updates over WebSocket/SSE
- optional backpressure and coalescing are applied for slower consumers `[Phase 2+]`

### Example subscriptions

- Finance agent subscribes to `cashflow_forecast`, `loan_pressure`, `company_balance_sheet`
- Fleet agent subscribes to `vehicle_status`, `idle_vehicle_report`, `depot_alerts`
- Network planner subscribes to `town_pair_opportunities`, `cargo_supply_demand`, `map_buildability`
- Executive planner subscribes to `company_summary`, `expansion_candidates`, `competitor_activity`

### Practical design note

This subscription model is inherently framework-agnostic. Any agent that can open a WebSocket or poll a REST endpoint can consume observation channels. No adapters or wrappers are needed inside `nttd`.

---

## Action API

Use **JSON action envelopes**. Keep the action vocabulary small and typed.

Example envelope:

```json
{
  "action_id": "uuid",
  "company_id": 1,
  "mode": "atomic",
  "action_type": "build_rail_corridor",
  "parameters": {
    "from_town_id": 12,
    "to_town_id": 48,
    "station_config": {"platforms": 2, "length": 5},
    "budget_limit": 250000
  },
  "constraints": {
    "deadline_ms": 3000,
    "idempotency_key": "..."
  },
  "metadata": {
    "agent_id": "network_planner_v2",
    "trace_id": "..."
  }
}
```

### Action categories

#### Atomic

Direct game operations:

- build tile
- place station
- buy vehicle
- add order
- start/stop vehicle

#### Compound

Short sequences:

- create bus line
- connect two towns by road
- refit fleet to cargo type

#### Strategic

Intent-level:

- expand passenger network eastward
- improve profitability of company 1
- reduce congestion at station X

Strategic actions should **never** hit the game directly. They must be translated by `nttd` into compound/atomic actions.

---

# How actions should actually reach OpenTTD

Support **two execution paths**.

## Path A — Admin/rcon path

Use for:

- pausing/unpausing
- save/load
- server settings
- player/company admin
- chat
- operational control

Reference:

- Admin network docs: <https://github.com/OpenTTD/OpenTTD/blob/master/docs/admin_network.md>

## Path B — GameScript command path

Use for:

- in-world queries
- build logic
- route planning helpers
- vehicle/company-scoped actions
- structured result returns

This is the more important path for “playing the game.” `GSCompanyMode` is especially valuable because it lets GameScript execute actions under a specific company, so costs and permissions behave like a real player.

Reference:

- `GSCompanyMode`: <https://docs.openttd.org/gs-api/classGSCompanyMode>

### Why this split matters

If you try to do all game-playing through rcon and raw console commands, you will end up with brittle automation. The admin port is excellent for orchestration and server control, but the **in-game GameScript layer** is where a reliable semantic API should live.

That is the core insight.

---

# Fault tolerance design

`nttd` needs several guarantees.

## 1. Persistent bridge, stateless agent connections `[Feasible — Phase 1]`

Agent connections are stateless and disposable — if an agent disconnects and reconnects, it re-subscribes and continues. The **bridge** should hold the authoritative session state and keep the OpenTTD connection alive.

Reference:

- OpenTTD MCP project: <https://github.com/iNewLegend/openttd-mcp/blob/main/README.md>

## 2. Idempotent action execution `[Phase 2+]`

Every action needs:

- `action_id`
- `idempotency_key`
- `precondition_hash`
- `company_id`
- `expected_game_epoch`

If an agent retries, the system should not accidentally double-build a station or buy duplicate vehicles.

> **Phase guidance:** For Phase 1, use `action_id` for logging and deduplication. Full idempotency keys and precondition hashes add complexity that is unnecessary for a research prototype. Log everything and detect duplicates post-hoc.

## 3. Epoch-based consistency `[Feasible — Phase 1]`

Tag each observation with:

- `game_date`
- `tick_epoch`
- `snapshot_id`
- `company_revision`
- `map_revision`

Reject or revalidate actions generated from stale observations.

## 4. Durable event log `[Feasible — Phase 1]`

Every inbound/outbound message should be appended to a durable log:

- raw admin packets if useful
- normalized state deltas
- actions
- validation decisions
- execution results
- exceptions

## 5. Reconnect semantics `[Feasible — Phase 1]`

The bridge should:

- reconnect to admin port
- re-subscribe to updates
- resync state
- detect whether game changed via save/load/newgame
- notify agents of world reset

Reference:

- Admin network docs: <https://github.com/OpenTTD/OpenTTD/blob/master/docs/admin_network.md>

## 6. Command circuit breakers `[Phase 2+]`

If execution starts failing:

- pause the company executor
- keep observation plane alive
- classify failures by transient/permanent
- avoid command storms
- trip a per-company breaker
- allow human override

> **Phase guidance:** For Phase 1, use simple retry-with-backoff and error logging. Full circuit breaker patterns add complexity that is justified only at scale.

## 7. Human safety override `[Feasible — Phase 1]`

The human operator should always be able to:

- pause the game
- freeze the AI
- reject queued actions
- switch AI to observe-only mode
- disconnect or block specific agent connections

---

## Checkpoints and crash recovery considerations

Yes — a **checkpoint** mechanism is reasonable and, in practice, highly recommended.

### Why checkpoints make sense

Even with strong event logging, a full machine or process failure can leave you with:

- a lost in-memory world cache
- incomplete action queues
- partially processed observations
- lost agent-local working memory

Checkpointing helps you recover faster and more deterministically.

### What to checkpoint

At a minimum, each checkpoint should capture:

1. **OpenTTD savegame**
   - authoritative simulation state
2. **`nttd` runtime metadata**
   - snapshot id
   - game date / tick epoch
   - active company mappings
   - runtime mode
   - current subscriptions
3. **Action queue state**
   - pending actions
   - in-flight actions
   - last acknowledged action ids
4. **Observation state**
   - latest canonical world snapshot hash
   - recent deltas if using event replay windows
5. **Agent context state**
   - optional summaries, tool memory, strategic plans, or role state
6. **Observability metadata**
   - trace ids
   - run ids
   - experiment ids

### Checkpoint strategies

#### Strategy A — periodic full checkpoints

- save OpenTTD game every N in-game days / N heartbeats / M minutes
- persist `nttd` metadata transactionally alongside it

Pros:
- simple to reason about
- strong recovery behavior

Cons:
- can be heavier operationally

#### Strategy B — full checkpoint + incremental event replay

- take periodic full savegames
- rely on durable event logs to replay from the last checkpoint forward

Pros:
- faster than checkpointing too frequently
- good for experiments and replay

Cons:
- slightly more complex restart logic

### Recommended checkpoint design

Use **hybrid checkpointing**:

- periodic full OpenTTD savegame
- transactional metadata snapshot in Postgres/object storage
- durable action/event log between checkpoints

### Recovery flow after crash

1. restart OpenTTD server
2. load latest valid savegame checkpoint
3. restore `nttd` metadata snapshot
4. reconcile admin connection and world identity
5. replay post-checkpoint action/event log if needed
6. re-establish subscriptions
7. mark any ambiguous in-flight actions as `needs_reconciliation`
8. resume in safe mode or heartbeat mode first

### Important design consideration

Because OpenTTD is the source of truth, the **savegame** is the core checkpoint artifact. Everything else in `nttd` should be designed to rebuild around that artifact.

### Recommendation

For production and research reproducibility, checkpointing should be a mandatory feature, not an optional extra.

---

# Scalability design

Scalability here means:

- multiple concurrent agent frameworks
- multiple companies
- large maps
- many observations
- replay and experiments

## Use event sourcing, not polling everything

Polling full state repeatedly will overload both the bridge and the agent context budget.

Instead:

- maintain a canonical world model
- update it incrementally from events and periodic reconciliations
- expose delta subscriptions

## Partition state by concern

Keep separate stores for:

- world topology
- economic state
- vehicle state
- route graph
- station throughput
- action journal

## Cache derived analytics

Things like “best town pairs” or “stuck vehicles” should be derived once per epoch and reused.

## Separate hot path and cold path

### Hot path

- current tick
- action validation
- execution queue
- event stream

### Cold path

- replay
- analytics
- training data export
- large-scale summarization
- dashboards

## LLM-specific scalability rule

Never ship raw full-state dumps to an LLM every heartbeat. Instead:

- send compact summaries
- retrieve local details on demand
- give the LLM tool calls into `nttd`
- allow it to ask for more detail only when needed

This is where multiple asynchronous endpoints become useful: not as random endpoints, but as a **toolable information graph**.

---

# Agent connection model

`nttd` is **fully agent-agnostic**. It does not wrap, adapt, or embed any agent framework. Instead, it exposes documented APIs with published schemas. Agents are external clients that connect, subscribe, observe, and act.

> **Core principle: `nttd` does not care what the agent is.** It only cares about the JSON contract. Any system — LangGraph, CrewAI, AutoGen, Neuro-SAN, Haystack, MCP-based agents, RL policies, hand-coded scripts, a human with curl — can be an agent if it speaks the API.

## How an agent connects

1. **Connect** — agent authenticates and registers with `nttd`, declaring its identity and company scope
2. **Subscribe** — agent subscribes to one or more observation streams (state domains, derived views, events, or cadence-based snapshots)
3. **Observe** — `nttd` pushes observation data to the agent on its subscribed channels (via WebSocket/SSE) or the agent polls via REST
4. **Act** — agent publishes a JSON action envelope to the Action API
5. **Validate + Execute** — `nttd` validates the action against the schema and current game state, translates it into in-game commands, executes it, and returns the result

## Multiple concurrent agents

Multiple agents can connect simultaneously, each with their own:

- **subscriptions** — different agents observe different state domains
- **company scope** — an agent may be scoped to one company or have cross-company visibility
- **action permissions** — enforced per-agent based on their registered scope
- **cadence** — some agents observe every heartbeat, others every N game-days, others on-demand

This means the same `nttd` instance can serve:

- a single monolithic LLM agent observing everything
- multiple specialized agents each watching their own domain
- a mix of LLM agents and lightweight rule-based policies
- human-driven tools alongside autonomous agents

## Speed decoupling

Agent response time is the agent's problem, not `nttd`'s. The system decouples observation delivery from action execution:

- **Observations are pushed/available regardless of agent speed** — if an agent is slow, it gets the next observation when it's ready (or the latest available)
- **Actions are queued and executed by `nttd` at game speed** — after an agent submits actions, `nttd` controls when and how fast they are applied
- **Game speed is the system knob** — `nttd` can slow the game to give agents more thinking time, or fast-forward between agent decisions
- **Stale actions are rejected** — if an agent's action references an outdated game state, the Action Service revalidates before execution

## What `nttd` publishes (schema documentation)

The only contract between `nttd` and any agent is:

1. **Observation schemas** — documented JSON schemas for every observation domain, derived view, and event type that an agent can subscribe to
2. **Action schemas** — documented JSON schemas for every action type an agent can submit
3. **Connection protocol** — how to authenticate, subscribe, and receive/send messages

That's it. No adapters. No framework-specific code inside `nttd`. Agents are plug-and-play by design.

## Why this makes framework compatibility trivial

There is no `LangGraphAdapter` or `CrewAIAdapter` to build. Any framework that can make HTTP/WebSocket calls and produce JSON can be an agent. Framework-specific integration (if desired) lives **outside `nttd`**, in the agent's own codebase — a thin client library that wraps `nttd`'s API.

---

# Gym and PettingZoo compatibility

Yes, you can support both, but do it in layers.

## Gym-compatible single-agent view

Expose one company as the learning agent, while competitors are scripted/baseline.

Define:

- `reset()`
- `step(action)`
- `observation_space`
- `action_space`
- `reward`
- `terminated`
- `truncated`

Best fit: **heartbeat mode**.

## PettingZoo-compatible multi-agent view

Each company becomes an agent, or each internal role becomes an agent, depending on the experiment.

You will need:

- agent ordering
- per-agent observations
- shared/global state
- action masking
- synchronization barriers

Again, heartbeat mode is much easier first.

---

# Reward design and gameplay objectives

You mentioned wanting to understand the various objectives that can be achieved in the game. This is closely related to reward design.

OpenTTD is a transport-business simulation rather than a single-objective arcade game, so `nttd` should support **multiple benchmark objectives**.

## Natural gameplay objectives in OpenTTD

### 1. Profit maximization

- maximize operating profit
- maximize annual income
- minimize losses and waste

### 2. Company value growth

- maximize company valuation over time
- maximize long-term asset quality and network value

### 3. Network expansion

- connect more towns
- connect more industries
- cover more map area
- achieve transport modality diversity

### 4. Service quality

- increase station coverage
- reduce cargo wait times
- improve passenger/mail service frequency
- reduce congestion and delivery delays

### 5. Throughput and logistics efficiency

- maximize delivered cargo/passenger throughput
- reduce idle vehicles
- improve vehicle utilization
- optimize route efficiency and load balancing

### 6. Financial discipline

- avoid bankruptcy
- manage debt well
- borrow and repay strategically
- maintain healthy cash reserves

### 7. Competitive advantage

- outperform rival companies
- secure attractive routes earlier
- deny competitors key network positions

### 8. Scenario or custom benchmark goals

Depending on map/scenario settings, benchmarks can target:

- connect specified towns within budget
- create profitable coal-to-power logistics chain
- achieve profitability within fixed in-game time
- recover from economic downturn or adversarial events
- sustain service under infrastructure constraints

## Reward design guidance

Do **not** use a single scalar reward only. Log a **reward vector** and collapse later for training or leaderboard reporting.

### Candidate reward signals

- company value growth
- operating profit
- route profitability
- service coverage
- delivery throughput
- network efficiency
- reduced congestion
- lower idle assets
- survival / solvency
- milestone achievements

### Suggested benchmark families

#### Benchmark family A — Growth

Optimize for:

- company value
- total profitable routes
- network expansion rate

#### Benchmark family B — Efficiency

Optimize for:

- revenue per vehicle
- throughput per route
- congestion reduction
- station and fleet utilization

#### Benchmark family C — Robustness

Optimize for:

- solvency
- resilience after failures
- recovery after bad investments or disruptions

#### Benchmark family D — Strategic competition

Optimize for:

- rank against competitors
- route domination
- first-mover advantage

### Recommendation

Store rewards in a structured object such as:

```json
{
  "profit": 0.73,
  "valuation": 0.64,
  "coverage": 0.58,
  "efficiency": 0.70,
  "solvency": 0.95,
  "competition": 0.41,
  "composite": 0.67
}
```

That keeps the platform useful for both RL and LLM-agent evaluation.

---

# Gameplay settings and config considerations for OpenTTD

Gameplay settings matter a lot because they define the benchmark regime. `nttd` should treat OpenTTD configuration as part of the experiment specification.

## Why gameplay config matters

Changes to map, economy, infrastructure cost, industries, and vehicle settings can radically change:

- agent difficulty
- planning horizon
- route economics
- build feasibility
- benchmark comparability

## Recommended config categories

### 1. Map generation settings

- map size
- terrain roughness
- water level
- town density
- industry density
- seed / reproducibility seed
- climate / landscape type

These directly affect routing complexity and opportunity density.

### 2. Economy settings

- inflation on/off
- industry behavior options
- subsidy availability
- town growth constraints
- loan limits / interest settings where applicable
- breakdown severity / maintenance-related settings

These shape long-term strategy and financial risk.

### 3. Vehicle settings

- max vehicles
- vehicle breakdowns
- realistic acceleration on/off
- infrastructure maintenance settings where relevant
- speed limits / pathfinding-affecting rules
- vehicle aging and replacement environment

These shape operational difficulty.

### 4. Infrastructure and construction settings

- build cost factors
- terraform cost sensitivity
- permissiveness around road/rail construction
- station spread limits
- signal/pathfinding-related settings

These affect build-agent complexity.

### 5. Multiplayer / server settings

- pause permissions
- autosave cadence
- admin port config
- server tick pace / speed management policies
- spectator vs player access model
- save/load and scenario loading policies

These matter directly to `nttd` operations.

### 6. Benchmark mode settings

`nttd` should define benchmark presets such as:

- `starter_easy_growth`
- `dense_towns_passenger`
- `sparse_industry_logistics`
- `mountain_hard_build`
- `competitive_multicompany`
- `recovery_from_crisis`

Each preset should pin:

- OpenTTD version
- NewGRF / scenario dependencies if any
- map seed
- gameplay settings
- heartbeat config
- reward configuration

## Recommendation

Treat gameplay config as a versioned artifact:

- `game_config.yaml`
- `benchmark_config.yaml`
- `reward_config.yaml`

This is critical for reproducibility.

---

# Human gameplay + observability screen

You want both the normal game visuals and a second monitoring screen.

## Screen 1 — OpenTTD client

This is the primary visual game surface. The human sees the real game with its normal UI.

## Screen 2 — `nttd` observability UI

This should show:

- current game date and mode
- pause/heartbeat state
- company KPIs
- top routes by profit/loss
- vehicle health / stuck alerts
- station congestion
- recent events
- pending actions
- action execution timeline
- per-agent decisions
- token/cost/latency stats for LLM agents
- trace view for each decision cycle

This observability plane should feel like LangSmith/OpenTelemetry for a transport simulation.

---

# Observability stack: TensorBoardX and Dash

Using **TensorBoardX** is reasonable, especially for experiment tracking and performance curves.

References:

- TensorBoardX GitHub: <https://github.com/lanpa/tensorboardX>
- TensorBoardX project page: <https://lanpa.github.io/work/tensorboardx/>
- Plotly Dash docs: <https://dash.plotly.com/>

## Recommended observability split

### TensorBoardX for experiment metrics and time series

Use TensorBoardX for:

- per-run scalar metrics
- reward curves
- company value over time
- profit / loss time series
- action latency and success rates
- token usage and model cost over time
- benchmark comparisons across runs

This is especially useful for RL training and large-scale benchmarking.

### Dash for rich operational dashboards

Use Plotly Dash when you need custom observability such as:

- live company drill-downs
- station congestion tables
- vehicle route maps
- action timeline inspection
- subscription stream debugging
- operator controls and alerts
- experiment comparison panels

### Recommendation

Use both, with a clear split:

- **TensorBoardX** for experiment logs, training curves, and benchmark metrics
- **Dash** for live control-room and interactive operational observability

That is likely the most practical approach.

---

# Logging: what “superb logging” actually means

Superb logging should mean **structured, replayable, queryable** logs.

## Mandatory log entities

- `game_session`
- `snapshot`
- `delta_event`
- `agent_request`
- `agent_response`
- `action_candidate`
- `validation_result`
- `execution_attempt`
- `execution_result`
- `error_event`
- `human_override`
- `reward_frame`

## Log levels

- `debug`: packet-level and raw tool payloads
- `info`: actions, decisions, key state changes
- `warning`: stale observations, partial failures
- `error`: failed execution, schema errors, lost connection
- `audit`: all human overrides, company-control changes, save/load/newgame

## Replay support

You should be able to replay a session in three ways:

1. state-only replay
2. action timeline replay
3. decision replay with agent rationales

This becomes invaluable for both evaluation and training.

---

# Suggested API surface for `nttd`

Expose **four APIs**. These are the only interfaces any agent, dashboard, or operator needs.

## 1. Control API

For orchestration and admin (human operators, not agents):

- `/session/start`
- `/session/stop`
- `/session/pause`
- `/session/unpause`
- `/session/mode` — switch between heartbeat / async real-time / assisted
- `/session/speed` — set game speed (first-class control)
- `/session/save`
- `/session/load`
- `/session/status`

## 2. Agent Connection API

For agent lifecycle management:

- `/agents/connect` — authenticate and register an agent, declare identity and company scope
- `/agents/{id}/disconnect` — graceful disconnect
- `/agents/{id}/status` — agent connection health
- `/agents/list` — list all connected agents

## 3. Observation API

For agents and dashboards (subscribe + consume):

- `/state/full`
- `/state/company/{id}`
- `/state/map/window`
- `/state/towns`
- `/state/industries`
- `/state/stations`
- `/state/vehicles`
- `/state/events/stream`
- `/state/opportunities/...`
- `/subscriptions/register` — agent subscribes to observation channels
- `/subscriptions/list`
- `/subscriptions/remove`

Delivery via:

- **WebSocket** — real-time push for subscribed channels (primary)
- **SSE** — alternative push mechanism
- **REST polling** — fallback for simple agents

## 4. Action API

For agent decisions (submit + track):

- `/actions/validate` — dry-run validation against current state
- `/actions/submit` — submit a JSON action envelope
- `/actions/batch_submit` — submit multiple actions atomically
- `/actions/{id}/status` — track execution result
- `/actions/{id}/cancel` — cancel a pending action
- `/actions/recent` — query recent action history

Every action is a JSON envelope conforming to the published action schema. `nttd` validates, translates, and executes. The agent never touches OpenTTD directly.

---

# Recommended technology choices

## Core backend

- **Python + FastAPI**
- async bridge service
- event bus via Redis or NATS `[Phase 2+ — MVP: use in-process async queues]`
- Postgres for durable logs / metadata `[Phase 2+ — MVP: SQLite or structured JSON logs]`
- object storage or Parquet for large replay artifacts `[Phase 2+]`

## OpenTTD integration

- Python admin-port client for the external bridge
- custom OpenTTD GameScript in Squirrel for in-game semantics
- optional rcon/admin helpers for operational control

## Dashboard

- React frontend or Dash for production UI
- Streamlit for early prototype if desired
- websocket timeline + charts
- company and agent drill-downs

## Optional execution isolation

- separate worker processes for heavy planning
- per-agent sandbox/process boundary
- timeout + cancellation

---

# A concrete runtime design I would recommend

## Phase 1 — MVP

Goal: one human + one AI company, all three runtime modes functional.

### What to build

- dedicated OpenTTD server setup with admin port
- Python bridge to admin port (using `pyOpenTTDAdmin` or custom async client)
- GameScript with structured query/response protocol (correlation IDs, JSON serialization)
- FastAPI service exposing Control, Agent Connection, Observation, and Action APIs
- **published JSON schemas** for all observation domains and action types (the agent contract)
- agent connection + subscription registration (basic: by entity type, event type, cadence)
- observation delivery via WebSocket and REST polling
- action validation + translation pipeline (JSON envelope → GameScript commands)
- heartbeat mode (hard pause) for benchmarks
- async real-time mode for human co-play (with game speed control)
- assisted mode skeleton (human triggers AI via chat/command)
- structured logging to SQLite / JSON files
- one simple dashboard (Streamlit or Dash prototype)
- Gym single-agent wrapper (heartbeat mode)
- example agent client (plain Python) demonstrating the connect → subscribe → observe → act flow

### What to defer to Phase 2+

- Redis/NATS event bus
- Postgres
- advanced subscription features (region-based, backpressure, coalescing)
- PettingZoo wrapper
- circuit breakers and idempotency infrastructure
- latency class routing
- compound action decomposition (pathfinding for rail corridors)
- full canonical state extraction for large maps
- distributed experiments

This phase proves the concept: any external agent can connect, subscribe to observations, and submit actions via documented schemas, across all three runtime modes.

## Phase 2 — Production research platform

Add:

- per-company isolation via GSCompanyMode orchestration
- subscription model with pub/sub routing
- PettingZoo multi-agent wrapper
- event-driven delta detection (GS polling + snapshot diffing)
- compound action decomposition (pathfinding, rail corridor builder)
- action validation engine with idempotency
- circuit breakers per company
- Redis/NATS event bus + Postgres for durable logs
- save/load + benchmark packs
- observability traces (OpenTelemetry-style)
- smarter derived observations (cashflow forecast, buildable area scan)

## Phase 3 — Scale and RL

Add:

- tactical rule-based policy workers for async real-time mode
- LLM strategic planner with periodic replans
- latency class routing infrastructure
- distributed experiments across multiple OpenTTD instances
- reward shaping and offline dataset export
- full canonical state extraction for large maps
- training data pipelines (Parquet, object storage)

---

# What I would avoid

## 1. Avoid raw screen scraping

OpenTTD already has proper programmatic surfaces. UI scraping will be brittle and unnecessary.

## 2. Avoid direct LLM-to-console control

Never let LLMs emit raw rcon commands as the main control path. Too fragile and unsafe.

## 3. Avoid monolithic “one agent does everything”

A huge generic planner will be slower, harder to debug, and worse for benchmarking.

## 4. Avoid only full-state REST polling

That will become slow and expensive fast. Use deltas and task-specific views.

## 5. Avoid coupling to any agent framework

`nttd` should never contain framework-specific code. No adapters, no imports of LangGraph/CrewAI/etc. The API schemas are the only contract. Agents are external clients.

---

# The single best design pattern for `nttd`

If I had to summarize the right mental model:

`nttd` should be for OpenTTD what a **game server API + orchestrator + observability layer** is for agent systems.

- OpenTTD is the simulation kernel
- GameScript is the semantic in-engine extension
- admin port is the external control bus
- `nttd` is the normalized API layer with published schemas
- any agent connects as an external client via those schemas
- dashboards and replay tools sit beside it

That gives you:

- plug-and-play agents via published API schemas
- heartbeat, async real-time, and assisted modes
- human-visible gameplay
- strong logging
- reproducibility
- Gym/PettingZoo compatibility
- resilience to slow or flaky LLMs

---

# Final recommendation

Build `nttd` with this core principle:

> **OpenTTD remains the source of truth. `nttd` becomes the agent-facing operating system around it.**

That means:

- **server-mode OpenTTD**
- **persistent Python bridge**
- **custom GameScript**
- **normalized state/action schemas**
- **three runtime modes: heartbeat, async real-time, and assisted**
- **game speed as a first-class control mechanism**
- **agent-agnostic API with published schemas (no adapters)**
- **serious observability and replay**
- **checkpointing for recovery and reproducibility**
- **subscription-based observation routing (Phase 2+)**

That is the architecture most likely to work well in practice.

---

## Source-backed notes used in this report

- The OpenTTD admin network is a dedicated protocol for external apps, supports remote console commands, exposes client/company information, and keeps admin applications connected across new games and save/load events: <https://github.com/OpenTTD/OpenTTD/blob/master/docs/admin_network.md>
- OpenTTD provides GameScript APIs including `GSController` and `GSCompanyMode` for in-game scripting and company-scoped queries/commands: <https://docs.openttd.org/gs-api/>, <https://docs.openttd.org/gs-api/classGSController>, <https://docs.openttd.org/gs-api/classGSCompanyMode>
- OpenTTD dedicated server mode is documented and intended for running network games without a local client on the server process: <https://wiki.openttd.org/en/Manual/Dedicated%20server>
- The server admin port is documented as the external admin interface and points to available libraries and scripts: <https://wiki.openttd.org/en/Development/Server%20admin%20port>
- `pyOpenTTDAdmin` is a Python library for working with the admin port: <https://github.com/liki-mc/pyOpenTTDAdmin>, <https://pypi.org/project/pyOpenTTDAdmin/>
- OpenTTDLab is a Python framework for reproducible OpenTTD experiments and result extraction: <https://github.com/michalc/OpenTTDLab>, <https://pypi.org/project/OpenTTDLab/>, <https://joss.theoj.org/papers/10.21105/joss.08014.pdf>
- TensorBoardX is a lightweight TensorBoard writer often used for experiment metrics: <https://github.com/lanpa/tensorboardX>
- Plotly Dash is suitable for building custom operational dashboards: <https://dash.plotly.com/>
- Unknown horizons Godot port <https://github.com/unknown-horizons/godot-port>
