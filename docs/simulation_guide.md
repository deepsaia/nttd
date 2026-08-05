# nttd Simulation & Benchmarking Guide

For CLI reference, see `docs/cli_guide.md`. For analysis, see `docs/session_analyzer.md`.

---

## How the Simulation Works

```
OpenTTD dedicated server  <-- admin port (TCP) -->  nttd API server
                          <-- GameScript msgs  -->

Orchestrator loop (async_realtime):
  GS refresh (every ~10s) --> snapshot to Parquet
  Agent cycle loops (independent, per-agent):
    observe -> decide (LLM + tools) -> execute (GS) -> track
  Check end conditions
```

| Step | What Happens |
|------|-------------|
| **GS refresh** | Queries towns, industries, stations, vehicles via GameScript. |
| **Snapshot** | World state recorded to Parquet. |
| **Agent observe** | Compact state (~1-3 KB) for the agent's company. |
| **Agent decide** | LLM call with system prompt + observation tools + history. |
| **Execute** | Actions sent to GS with correlation IDs. |
| **End conditions** | Wall-clock time, game date, revenue, or cargo thresholds. |

---

## Runtime Mode

The current production mode is **async_realtime**: the game runs continuously, agents observe and act on their own poll interval, and the game never pauses for AI.

Game speed is the primary control knob -- slower speed gives agents more thinking time per game period.

---

## Agent Cycle

Each agent runs an independent async loop:

1. **Observe** compact state for its company
2. **Decide** via LLM (can call observation tools mid-turn)
3. **Execute** parsed actions via GameScript
4. **Track** cycle telemetry to Parquet

### Route Building

| Transport | Primary Action | Finder Tools |
|-----------|---------------|-------------|
| Road | `connect_road` (A* pathfind + auto-build) | `find_bus_stop_spots`, `find_depot_spots` |
| Rail | `connect_rail` (A* pathfind + auto-build) | `find_flat_spots`, `get_engines` |
| Air | `build_airport` + orders | `find_airport_spots`, `get_hangars` |
| Water | `build_dock` + `build_path` | `find_dock_spots`, `find_water_depot_spots` |

`connect_road`/`connect_rail` handle full route construction: A* pathfinding, road/rail placement, bridges/tunnels. The GS pathfinder yields every 500 iterations to avoid blocking.

Smart finder tools (`find_*_spots`) use `GSTestMode()` dry-run validation -- returned coordinates are guaranteed to succeed.

---

## Session Data

Stored in `logs/sessions/<session_id>/`:

| File | Content |
|------|---------|
| `session.parquet` | Metadata, settings, timestamps |
| `agents.parquet` | Per-agent config |
| `snapshots.parquet` | Game state time-series |
| `actions.parquet` | Agent actions with results |
| `result.parquet` | One row per scored company |
| `events.parquet` | Lifecycle events |
| `tiles.parquet` | Terrain data |
| `screenshot/` | Minimap screenshots (when enabled, default off) |
| `save/` | Game saves (when enabled, default off) |

---

## Analysis

```bash
nttd analyze -s <session_id>                     # all reports to terminal
nttd analyze -s <session_id> --save markdown,png  # save files
nttd analyze -s <session_id> --compare <other_id> # compare sessions
```

Reports include period headers (date range, total game days) and handle year-boundary resets with this_year/last_year/total columns.
