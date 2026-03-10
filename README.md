# nttd

Agent-agnostic API server for OpenTTD AI simulation. Agents connect via REST/WebSocket, subscribe to game observations, and submit actions — no framework lock-in.

---

## Quick Start

### Prerequisites

- Python 3.13+, [uv](https://docs.astral.sh/uv/)
- [OpenTTD](https://www.openttd.org/) installed (macOS: `/Applications/OpenTTD.app`)

### Install

```bash
uv sync
```

### Run

Terminal 1 — Start OpenTTD dedicated server:
```bash
./scripts/start_openttd_server.sh
```

Terminal 2 — Start nttd API server:
```bash
uv run uvicorn nttd.api.app:app --reload
```

Terminal 3 (optional) — Join as human player:
Open OpenTTD normally -> Multiplayer -> Add server `127.0.0.1:3979` -> Join

### Try the Example Agent

```bash
# REST mode (connect, observe, act, disconnect)
uv run python examples/agent_client.py

# WebSocket mode (real-time snapshot streaming)
uv run python examples/agent_client.py --ws
```

### Run Tests

```bash
uv run pytest
```

### Test the Bridge Manually

```bash
uv run python scripts/test_bridge.py
```

---

## Configuration

OpenTTD server config lives in `ottd_config/openttd.cfg`. Key settings:
- Admin port: `3977` (password: `nttd`)
- Game port: `3979`
- `allow_insecure_admin_login = true` (required for pyopenttdadmin)

nttd API server config via environment variables:
- `NTTD_ADMIN_HOST` — OpenTTD host (default: `127.0.0.1`)
- `NTTD_ADMIN_PORT` — Admin port (default: `3977`)
- `NTTD_ADMIN_PASSWORD` — Admin password (default: `nttd`)

---

## API Overview

### Control (`/session`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/session/status` | Current game state (date, mode, paused, speed) |
| POST | `/session/pause` | Pause the game |
| POST | `/session/unpause` | Unpause the game |
| POST | `/session/speed?speed=N` | Set game speed |
| POST | `/session/mode?mode=MODE` | Switch runtime mode (heartbeat, async_realtime, assisted) |
| POST | `/session/stop` | Stop the orchestrator |
| POST | `/session/heartbeat/interval?days=N` | Set heartbeat interval |
| POST | `/session/rcon?command=CMD` | Send rcon command to OpenTTD |

### Agent Connection (`/agents`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/agents/connect` | Register agent with company scope |
| POST | `/agents/{id}/disconnect` | Disconnect agent |
| GET | `/agents/{id}/status` | Agent status and subscriptions |
| GET | `/agents/list` | List all connected agents |
| POST | `/agents/{id}/subscriptions` | Subscribe to observation channel |
| DELETE | `/agents/{id}/subscriptions/{channel}` | Unsubscribe |
| GET | `/agents/{id}/subscriptions` | List agent's subscriptions |

### Observation (`/state`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/state/full` | Full state snapshot |
| GET | `/state/company/{id}` | Single company |
| GET | `/state/towns` | All towns |
| GET | `/state/industries` | All industries |
| GET | `/state/stations` | All stations |
| GET | `/state/vehicles` | All vehicles |

### Actions (`/actions`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/actions/submit` | Submit an action |
| POST | `/actions/validate` | Validate without executing |
| GET | `/actions/{id}/status` | Check action result |
| GET | `/actions/recent` | Recent actions |

### WebSocket (`/ws`)

| Endpoint | Description |
|----------|-------------|
| `ws://host/ws/{agent_id}` | Real-time snapshot stream for connected agent |

Agents must first connect via `POST /agents/connect`, then open a WebSocket at `/ws/{agent_id}`. The server pushes `{"type": "snapshot", "data": {...}}` messages based on subscription cadence. Send `{"type": "ping"}` to receive `{"type": "pong"}`.

### Health

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Server + OpenTTD connection status |

---

## Runtime Modes

| Mode | Use Case | How It Works |
|------|----------|--------------|
| **heartbeat** | Benchmarks, RL, Gym | Pause -> snapshot -> notify agents -> unpause -> wait N days -> repeat |
| **async_realtime** | Human co-play | Game runs continuously, periodic snapshots pushed to agents |
| **assisted** | Co-pilot | Human triggers AI; game pauses while AI thinks (skeleton) |

---

## Architecture

```
Agent (any framework)
  |  REST / WebSocket
  v
[nttd API Server]  (FastAPI)
  |  Control, Observation, Action, Agent routes
  v
[State Layer]      (WorldState, AgentRegistry, ActionTracker)
  |
  v
[Bridge]           (async TCP admin port client)
  |
  v
[OpenTTD Server]   (dedicated, admin port 3977)
```

---

## What's Built

| Component | Status | Files |
|-----------|--------|-------|
| Schemas | Done | `src/nttd/schemas/` (game, company, town, industry, station, vehicle, agent, action, snapshot) |
| State layer | Done | `src/nttd/state/world.py`, `agent_registry.py` |
| Action tracker | Done | `src/nttd/actions/tracker.py` |
| API (5 groups) | Done | `src/nttd/api/` (control, agent, observation, action, ws routes) |
| Bridge | Done | `src/nttd/bridge/admin_client.py`, `bridge.py` |
| Runtime modes | Done | `src/nttd/runtime/orchestrator.py` (heartbeat + async_realtime) |
| WebSocket delivery | Done | `src/nttd/api/ws_routes.py` |
| Example agent | Done | `examples/agent_client.py` (REST + WebSocket modes) |
| Server config | Done | `ottd_config/openttd.cfg` |
| Tests | 10 passing | `tests/test_api.py` |

---

## Docs

- [Architecture Report](docs/nttd_architecture_report.md) — full design document with feasibility annotations
- [Implementation Plan](plan.md) — phased task breakdown
