# nttd CLI Guide

Every command, with examples. The CLI drives the server, the session lifecycle, and the
result record. It does **not** run agents — see [agent_guide.md](agent_guide.md) for
that side.

---

## Installing OpenTTD

nttd requires OpenTTD 15.x.

### macOS

Download from [openttd.org](https://www.openttd.org/downloads/openttd-releases/latest)
and drag to `/Applications`. nttd looks for
`/Applications/OpenTTD.app/Contents/MacOS/openttd`.

### Linux

```bash
sudo add-apt-repository ppa:openttd/ppa && sudo apt update && sudo apt install openttd
```

### Windows

Use the installer, then set `NTTD_OPENTTD_BINARY` to the `openttd.exe` path.

### Base graphics, on every platform

Launch OpenTTD once and install **OpenGFX2 Classic** from Online Content. `OpenSFX` and
`OpenMSX` are optional. To check: restart, Online Content, search `Open` — installed
content shows a green dot.

Override the binary path anywhere:

```bash
export NTTD_OPENTTD_BINARY=/path/to/openttd
```

---

## Prerequisites

```bash
uv sync                 # everything, in one go
```

Confirm your environment behaves the way nttd's design assumes:

```bash
uv run python -m scripts.verify_environment
```

Five checks against real servers: seed determinism, the economy clock rate, engine
availability at the profile's start year, and the pause semantics the step barrier
depends on. Takes a few minutes. Run it after upgrading OpenTTD.

---

## Quick start

```bash
uv run nttd server                                               # terminal 1
uv run nttd benchmark --config config/benchmark/t2_example.conf   # terminal 2
```

`benchmark` prints the session id and participant token, then waits. Attach your runner
to those while it waits, and it writes the result when the end condition fires.

---

## Commands

### `nttd server`

Starts the API server (uvicorn).

```bash
uv run nttd server
uv run nttd server --port 8123 --host 0.0.0.0
```

Reads `.env` from the working directory if present. `NTTD_SESSIONS_DIR` controls where
session data is written; it defaults to `logs/sessions`.

---

### `nttd benchmark`

Stands up a task and waits for it to end.

```bash
uv run nttd benchmark --config config/benchmark/t2_example.conf
uv run nttd benchmark --config config/benchmark/t2_example.conf --seed 2002
uv run nttd benchmark --config config/benchmark/t2_example.conf -o results/
```

| Option | |
|---|---|
| `--config`, `-c` | scenario path (required) |
| `--seed` | override the map seed |
| `--ai-opponents` | override the AI opponent count |
| `--output`, `-o` | directory for exported results |
| `--url` | server URL |

Validation is strict: an ill-specified scenario is refused rather than silently run with
substituted defaults, so a typo cannot quietly produce a run on a different world than
the one claimed.

It orchestrates the **world**, not agents. `--seed` is the one thing you may override,
because which world to play is your choice while whether it is scored is not.

---

### `nttd session`

For driving the lifecycle yourself.

```bash
uv run nttd session create --config config/benchmark/t2_example.conf
uv run nttd session start -s ses_... --agent-companies 1
uv run nttd session attach ses_...
uv run nttd session list
uv run nttd session status -s ses_...
uv run nttd session stop -s ses_...
```

**`create`** registers the session and resolves the scenario. Pass only the config; the
server loads it. Settings are not accepted from a client, because they carry `_scored`
and the profile-derived keys that decide whether the run is scored and what bounds it.

**`start`** generates the world and spawns OpenTTD. `--agent-companies 1` creates the
company your runner will play; without it there is nothing to play.

**`attach`** prints the participant token and the routes — real-time and stepped. The
token exists only in the `start` output and in `participants.json` otherwise, so this is
how you recover it.

**`stop`** ends the session, scores it, and writes `result.parquet`.

---

### `nttd scenario`

```bash
uv run nttd scenario validate config/benchmark/t2_example.conf
uv run nttd scenario validate my_variant.conf
uv run nttd scenario profile
```

**`validate`** runs the same strict validation a benchmark does, without spawning
OpenTTD. Reports every problem at once and exits non-zero, so it works as a pre-run
gate in a script. Worth doing before a T4: otherwise the first check failure costs you a
world generation.

**`profile`** prints the rules in force — locked settings, permitted values per free
dimension, the action ceiling, the profile digest — and names its source, so you can
tell whether your edits to `config/benchmark/profile.conf` are taking effect.

---

### `nttd result`

```bash
uv run nttd result -s ses_...
uv run nttd result -s ses_... --json > entry.json
```

Shows the score, the task identity, code provenance, per-model reported spend, and an
explicit list of verification gaps. `result.parquet` is written when the session stops,
so stop it first.

---

### `nttd analyze`

```bash
uv run nttd analyze -s ses_...
uv run nttd analyze -s ses_... --reports financial,cargo_delivery
uv run nttd analyze -s ses_... --compare ses_other --open
```

Generates reports from the session's Parquet files. See
[session_analyzer.md](session_analyzer.md).

---

## Scenario configuration

HOCON. A scenario is the **task**: the world and the rules, and nothing about who plays
it.

```hocon
scenario {
  name = "benchmark-t2-example"
  id   = "benchmark-t2-example"

  # No `version`, and no `scored`. There is no scenario version at all: any edit
  # worth invalidating a comparison changes the settings, which changes the
  # settings_digest and so the task_id. And scoredness is computed from the world
  # below, so declaring it would grant nothing. Add `scored = false` to opt OUT of a
  # conforming world, which is what you want while authoring.

  map {
    size_x       = 256      # 64 | 128 | 256 | 512 | 1024
    size_y       = 256      # must equal size_x: a scored map is square
    terrain_type = "flat"
    seed         = 1001     # pin it, or the run is not reproducible
  }

  companies {
    num_ai_companies     = 0
    competitors_interval = 0
    max_loan             = 300000
  }

  runtime {
    mode                   = "async_realtime"   # or "stepped"
    snapshot_interval_days = 1
  }

  end_conditions {
    logic = "any"
    time_limit { enabled = true, wall_minutes = 30 }
    bankruptcy { enabled = true }
  }
}
```

Anything omitted from `map` inherits from the profile, so a scenario says only what
makes it different.

### What a scored scenario may set

Locked by `config/benchmark/profile.conf` and refused if you change them:
`variety`, `smoothness`, `rivers`, `sea_level`, `map_edges`, `starting_year`,
`town_names`, `number_towns`, `industry_density`, `landscape`.

Free to vary, because each is recorded as a result column: the map **size** (one list
for both axes, which must be equal) and `terrain_type`. That is 5 × 5 = 25 scoreable
maps, each admitting any seed. Run `nttd scenario profile` for the permitted values.

**Scoredness is computed, not declared.** A conforming world is scored whether or not
the file says so; `scored = true` over a non-conforming world is refused rather than
honoured. See [play_modes.md](play_modes.md).

There is **no** `agents` block and **no** `fairness` block. Which agents play is your
runner's business; how much anyone may do is operator policy and lives in the profile.
A scenario carrying either is refused, with a message saying where it went.

### Stepped scenarios

```hocon
  runtime  { mode = "stepped" }
  heartbeat { interval_days = 15 }        # game-days per step

  end_conditions {
    time_limit     { enabled = false }    # see below
    max_heartbeats { enabled = true, count = 61 }
  }
```

`time_limit` must be explicitly disabled. It defaults to **enabled at 60 minutes**, so a
stepped scenario that simply omits it still ends on a wall clock — which is the one bound
that means nothing when the clock only advances on request. nttd refuses the combination
rather than letting it look reasonable.

### Tiers

The economy clock is fixed at 1 wall-minute per economy month, so wall-minutes *are* the
economy horizon: T1 15 min (~1.25 yr), T2 30 min (~2.5 yr), T3 60 min (~5 yr), T4
120 min (~10 yr).

There is no `game_speed`. OpenTTD 15.3 has no such setting; nttd's `/speed` endpoint
returns 501 and explains why.

---

## Session data

Under `NTTD_SESSIONS_DIR` (default `logs/sessions`), per session:

| File | |
|---|---|
| `result.parquet` | one row per scored company — the leaderboard artifact |
| `actions.parquet` | every action, refusals included, with status and game date |
| `snapshots.parquet` | full game state time-series |
| `events.parquet` | lifecycle and game events |
| `tiles.parquet` | terrain scan |
| `nttd_scenario.conf` | the resolved scenario, for provenance |
| `participants.json` | the tokens, mode 0600 |

---

## Spectating

`nttd session start` prints a `game_port`. Connect an OpenTTD client to
`127.0.0.1:<port>` to watch, or to play as a human entry.

---

## Tests

```bash
uv run pytest -q
uv run pytest tests/test_step_barrier.py -v
uv run ruff check src/ tests/
```

GameScript integration tests need a live session and are skipped otherwise:

```bash
uv run pytest tests/test_gs_integration.py --session-id ses_...
```

---

## Troubleshooting

**"Cannot reach nttd server"** — start it with `nttd server`, or pass `--url`.

**`nttd analyze` says "Session not found"** while `nttd result` works — check
`NTTD_SESSIONS_DIR` is set for both. Both honour it.

**A scored scenario is refused** — run `nttd scenario validate` on it. Every violation
is reported at once, naming the setting and what it is fixed at.

**Actions time out while the game is paused** — expected for pathfinding.
`connect_road` and `connect_rail` yield through `Sleep(1)`, which counts game ticks, so
a long search cannot complete while paused. Stepped mode handles this by flushing with
the game running.

**No participant token** — the session was started without `--agent-companies`, so no
contestant company exists.
