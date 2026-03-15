# nttd Simulation & Benchmarking Guide

## Overview

nttd wraps OpenTTD as a headless AI simulation environment. This guide covers the complete workflow — from starting a server to running multi-agent benchmarks and observing results.

---

## Quick start (5 minutes)

```bash
# 1 — Install
git clone <repo> && cd nttd
uv sync --extra dev

# 2 — Start OpenTTD in dedicated server mode
./scripts/start_openttd_server.sh       # or see "Starting OpenTTD" below

# 3 — Start nttd
nttd server --tensorboard               # or: uv run uvicorn nttd.api.app:app --reload

# 4 — Load a scenario and start heartbeat simulation
nttd scenario                           # preview active scenario
nttd sim                                # stream live metrics

# 5 — Run an agent (in a new terminal)
OPENAI_API_KEY=sk-... uv run python agents/langchain_agent.py --company-id 0

# 6 — Watch results
nttd results
nttd tensorboard                        # open http://localhost:6006
```

---

## Architecture: How the simulation works

```
OpenTTD dedicated server  ←──admin port (TCP 3977)──→  nttd API server
                          ←──GameScript (GS) msgs──→

nttd orchestrator (heartbeat loop):

  pause game
  │
  ├─ GS refresh  ─────────────────────────────→  WorldState updated
  │                                               (towns, stations, vehicles, companies)
  ├─ snapshot()  ─────────────────────────────→  StateSnapshot (full or compact)
  │
  ├─ push to broker ──────────────────────────→  AgentSnapshotBroker per agent
  │                                               (maxsize=1 queue, rolling history)
  │                   WebSocket /ws/{agent_id} →  Agent receives snapshot
  │
  ├─ action window (default 5s)
  │                   POST /session/heartbeat/action  ←  Agent submits GameAction list
  │
  ├─ execute actions  ─────────────────────────→  GS command → OpenTTD
  │                                               ActionTracker records result
  ├─ check end conditions
  │
  unpause game
  wait N game-days
  repeat
```

### Data flow in detail

| Step | What happens |
|------|-------------|
| **GS refresh** | Orchestrator calls `get_towns`, `get_industries`, `get_stations`, `get_vehicles` via GameScript. Responses are JSON. Each response is merged into `WorldState`. |
| **Snapshot** | `WorldState.snapshot()` copies current companies/towns/stations/vehicles into a `StateSnapshot`. |
| **Broker push** | `broadcast_snapshot(snapshot)` pushes the snapshot into each agent's `AgentSnapshotBroker` (max 1 pending — old unread snapshots are dropped, never queued lag). |
| **Agent receives** | Agent's WebSocket task calls `broker.wait_for_snapshot()` and unblocks. `NttdClient` enqueues into its local `deque`. |
| **Agent decides** | `AgentBase.run()` calls `decide(AgentContext)`. Sync implementations run in an executor; async ones are awaited directly. |
| **Action submitted** | Agent calls `client.submit_heartbeat_action(action, params)` → `POST /session/heartbeat/action`. The request carries `agent_id` for scope enforcement. |
| **Scope check** | If `agent_id` is present and `company_scope` is non-empty, the server rejects (403) actions targeting companies outside that scope. |
| **Execution** | After the action window closes, the orchestrator calls `send_gamescript(action, params)` for each queued action. The GS command runs inside OpenTTD via `GSCompanyMode`. |
| **Tracking** | Each action gets an `ActionEnvelope` (auto-generated `hb_XXXXXXXX` ID). `ActionTracker` records status: `PENDING → SUCCESS | FAILED`. |
| **End conditions** | After observer notification, `EndConditionChecker.check(snapshot)` evaluates all configured conditions. If triggered, the loop breaks and `on_end` callbacks fire. |

---

## Game state

### Full snapshot (`GET /state/full`)

Complete `StateSnapshot` — all companies, towns, industries, stations, vehicles. Typically 15–50 KB JSON. Use for detailed analysis or saving.

### Compact snapshot (`GET /state/compact?company_id=N`)

LLM-friendly summary (~1–3 KB). Includes:

- `game_date`, `paused`, `mode`, `map_width/height`
- `company`: balance, loan, income, value, `profit_trend` (last 3 heartbeats)
- `vehicles`: total, in_depot, avg_profit_this_year, by_type counts
- `top_stations`: top 3 by cargo waiting
- `top_towns`: top 3 by population
- `recent_actions`: last 5 submitted actions with status

Use this in LLM prompts — it fits comfortably inside a system message.

---

## Scenario configuration

Scenarios are defined in `config/scenario.conf` (HOCON format). Load at runtime:

```bash
nttd scenario --config config/scenario.conf
# or via API:
curl -X POST "http://localhost:8000/session/scenario?config_path=config/scenario.conf"
```

### End conditions

Any combination can be enabled. Set `logic = "any"` (first met stops) or `logic = "all"` (all must be met simultaneously).

```hocon
end_conditions {
  logic = "any"

  time_limit {
    enabled      = true
    wall_minutes = 60
  }
  game_date_limit {
    enabled  = false
    end_year = 2000
  }
  revenue_threshold {
    enabled       = false
    total_revenue = 1000000
  }
  cargo_threshold {
    enabled               = false
    total_cargo_delivered = 50000
  }
  max_heartbeats {
    enabled = false
    count   = 1000
  }
}
```

---

## Running agents

### Protocol

Any agent that implements one function can participate:

```python
from agents.base import AgentBase, AgentContext, GameAction

class MyAgent(AgentBase):
    def decide(self, context: AgentContext) -> list[GameAction]:
        # context.compact  — compact snapshot dict
        # context.history  — last 5 full snapshots
        # context.company_id, .game_date, .heartbeat_count
        return [GameAction(action="buy_vehicle", params={"company_id": 0, ...})]

import asyncio
asyncio.run(MyAgent(company_id=0, agent_id="my_agent").run())
```

`decide()` can also be `async`. Blocking (sync) calls run in a thread executor to avoid stalling the event loop.

### Included examples

| File | Framework | Strategy |
|------|-----------|---------|
| `agents/langchain_agent.py` | LangChain | One ReAct LLM call per heartbeat beat |
| `agents/langgraph_agent.py` | LangGraph | Planner (every N beats) + Executor (every beat) |

```bash
# LangChain agent
OPENAI_API_KEY=sk-... uv run python agents/langchain_agent.py \
  --company-id 0 --agent-id lc_0 --model gpt-4o-mini

# LangGraph agent
OPENAI_API_KEY=sk-... uv run python agents/langgraph_agent.py \
  --company-id 1 --agent-id lg_1 --planner-interval 5
```

### Agent scope enforcement

When you register an agent with `company_scope: [1, 2]`, the server enforces this:

- Any `POST /session/heartbeat/action` with `company_id` outside the scope returns `403`.
- Multiple agents can run simultaneously, each scoped to their own company.

---

## Headless benchmark

### Setup

```bash
# 1 — Create N AI companies
curl -X POST "http://localhost:8000/benchmark/setup?num_companies=2"

# 2 — Optionally reset (new game) with a specific scenario
curl -X POST "http://localhost:8000/benchmark/reset"
curl -X POST "http://localhost:8000/session/scenario"

# 3 — Start heartbeat mode
curl -X POST "http://localhost:8000/session/mode?mode=heartbeat"

# 4 — Run agents in separate terminals
OPENAI_API_KEY=sk-... uv run python agents/langchain_agent.py --company-id 0
OPENAI_API_KEY=sk-... uv run python agents/langgraph_agent.py --company-id 1

# 5 — Monitor
nttd sim          # live terminal metrics
nttd results      # company performance table
nttd tensorboard  # charts over time
```

### benchmark/setup internals

`POST /benchmark/setup?num_companies=N` does:
1. `rcon "setting max_no_competitors N"` — allows AI companies
2. `rcon "start_ai"` × N (500ms apart) — creates companies
3. `GS get_companies` — returns created company IDs

### Results

```bash
nttd results                                     # print table
nttd results --export benchmark_20250315.json    # also save JSON
curl http://localhost:8000/benchmark/results     # raw JSON
```

Per-company output:
- `balance`, `loan`, `income`, `company_value`
- `vehicles`, `stations`
- `actions_submitted`, `success_rate`

---

## Observability

### Terminal logs

```bash
nttd logs                  # last 40 events from newest log file
nttd logs --follow         # tail in real time
nttd logs --last 100       # more lines
nttd logs --run runs/nttd_20250315_120000.jsonl  # specific file
```

Log events: `observation`, `action_submitted`, `action_result`, `gs_command`, `reconnect`, `error`.

### TensorBoard

```bash
nttd server --tensorboard         # enable TB logging on startup
# or set env var:
NTTD_TENSORBOARD=1 nttd server

# in another terminal:
nttd tensorboard                  # opens http://localhost:6006
```

Tracked scalars:
- `game/date`, `game/vehicles`, `game/stations`, `game/companies`
- `company_N/balance`, `company_N/loan`, `company_N/income`, `company_N/value`, `company_N/vehicles`, `company_N/stations`
- `actions/success_rate`

### Metrics API

```bash
curl http://localhost:8000/state/metrics    # latest per-company snapshot (JSON)
```

---

## CLI reference

```
nttd server     [--host] [--port] [--reload] [--tensorboard] [--log-level]
nttd sim        [--scenario PATH] [--mode heartbeat|async_realtime] [--steps N] [--url]
nttd status     [--url]
nttd results    [--url] [--export PATH]
nttd logs       [--run PATH] [--follow] [--log-dir] [--last N]
nttd tensorboard [--log-dir] [--port]
nttd scenario   [--config PATH] [--url]
```

Set `NTTD_BASE_URL=http://myserver:8000` to point CLI commands at a remote nttd instance.

---

## Starting OpenTTD

OpenTTD must be running as a dedicated server before nttd can connect.

```bash
# macOS (Homebrew)
brew install openttd
openttd -D -c ottd_config/openttd.cfg

# Linux
apt install openttd
openttd -D -c ottd_config/openttd.cfg

# Docker
docker run --rm -p 3979:3979/tcp -p 3977:3977/tcp \
  -v "$(pwd)/ottd_config:/config" \
  openttd/openttd:latest
```

Key config (`ottd_config/openttd.cfg`):
- `admin_password = nttd` — matches `NTTD_ADMIN_PASSWORD` env var
- `pause_on_join = false` — spectators don't pause the benchmark
- `max_no_competitors = 0` — set > 0 at runtime via `/benchmark/setup`

```bash
# Override admin password
NTTD_ADMIN_PASSWORD=mysecret nttd server
```

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NTTD_ADMIN_HOST` | `127.0.0.1` | OpenTTD admin host |
| `NTTD_ADMIN_PORT` | `3977` | OpenTTD admin port |
| `NTTD_ADMIN_PASSWORD` | `nttd` | Admin password |
| `NTTD_TENSORBOARD` | `` | Set to `1` to enable TensorBoard |
| `NTTD_BASE_URL` | `http://localhost:8000` | CLI default server URL |
