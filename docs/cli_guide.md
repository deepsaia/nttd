# nttd CLI Guide

Every command, with examples. The CLI drives the server, the session lifecycle, and the
result record. It does **not** run agents: see [agent_guide.md](agent_guide.md) for
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
`OpenMSX` are optional. To check: restart, Online Content, search `Open`, installed
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
| `--ai-opponents` | override the extra company slot count (these are idle, not opponents) |
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

More than one contestant company makes the run **unscored**, and `start` says so. A
scored result is one company on one world; several sharing a map is a different problem.
Self-play still works, it simply cannot be ranked.

**`attach`** prints the participant token and the routes: real-time and stepped. The
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

**`profile`** prints the rules in force: locked settings, permitted values per free
dimension, the profile digest, and names its source, so you can
tell whether your edits to `config/benchmark/profile.conf` are taking effect.

---

### `nttd actions`

```bash
uv run nttd actions                       # everything, split by what it does
uv run nttd actions build_road_stop       # one action's parameters
uv run nttd actions --observations        # only what reads the world
uv run nttd actions --playable            # only what changes it
uv run nttd actions --operator            # only the scenario-setup powers
uv run nttd actions --category rail       # one category
uv run nttd actions --playable --json     # what a contestant may submit, as JSON
```

What nttd can do, and what each action takes. **Generated from the GameScript**, not
hand-written, so it cannot describe an action the game does not implement or miss one it
does. 129 actions, 345 parameters, all described.

The listing splits on what running something does, because that is the first thing worth
knowing: 44 observations that read the world and cost nothing, 76 actions that change it,
and 9 operator powers refused during scored play.

Each entry gives every parameter with its type, whether it is required, its default, and
what it means. Where a parameter takes a named constant the accepted values are listed
with it, and where an action accepts a choice of parameters that is stated too:

```
Supply one of: station_id or dest_tile or destination.
condition accepts (GSOrder): OC_AGE = 3, OC_LOAD_PERCENTAGE = 0, ...
```

The same content is served at `GET /v1/public/actions`, which is what a running agent
should use: already structured, and it answers without a session. `?tier=` and
`?category=` filter it, and `/v1/public/actions/<name>` returns one.

It is also in [the action reference](action_reference.md): an
[index](actions/index.md) giving every action's call shape on one line, and two detail
pages behind it so a reader pulls in only what it needs. The nine operator actions are
named there but not documented: no session can call one, so their parameters would be
about 1100 tokens spent telling a reader about things they cannot use. `--operator`
prints them here, which is where an operator setting up a scenario looks.

Regenerate after changing the GameScript:

```bash
uv run python scripts/generate_action_manifest.py
```

The enum values are read from OpenTTD itself rather than written down. Re-dump them after
changing the OpenTTD build:

```bash
uv run python scripts/dump_gs_enums.py
```

Four things are checked, because regenerating only proves the output matches the input it
was made from:

- **Nothing the handler reads is missing**, and **nothing published is absent from the
  handler**. Both directions, extracted independently of the generator, so a bug in the
  generator's own parsing cannot hide behind it.
- **Hand-written prose that matches nothing is an error**, not a silent no-op. A
  description for a deleted action, a glossary entry nobody uses, or an enum binding
  whose class moved would otherwise rot quietly: the parameter just loses its values.
- **Examples in the source are validated.** Both were wrong when this landed:
  `build_road_stop` was shown taking `length`, and `add_order` an `order_index` that
  belongs to `insert_order`. An agent copies the format it is shown.
- **The reference pages are regenerated and compared**, since a stale page reads exactly
  like a current one.

That drift is why this exists: a hand-written table of 14 actions declared
`plant_tree_rectangle` takes `x1, y1, x2, y2` while the GameScript reads
`x, y, width, height` and refuses anything else, so a contestant following nttd's own
validator was rejected by the game.

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

### `nttd submit`

```bash
uv run nttd submit -s ses_...
uv run nttd submit -s ses_... --no-archive
```

Packages the session into `logs/sessions/<id>/submission/` plus a `.tar.gz`, prints every
artifact with its sha256, and states what the bundle cannot prove about itself.

| File | Read by a check | Why it is there |
|---|---|---|
| `manifest.json` | yes | identity and integrity: ids, map digest, a sha256 per artifact |
| `result.parquet` | yes | the score and all provenance |
| `final.sav` | yes | the score is recomputed from this |
| `actions.parquet` | yes | action-log consistency and the capability check |
| `nttd_scenario.conf` | yes | rebuilding the world for `--regenerate` |
| `tiles.parquet` | no | shows *where* two worlds differ, not just that they do |
| `events.parquet` | no | human reading; kilobytes |
| `final_snapshot.parquet` | no | the end state, readable without OpenTTD |

**The full snapshot series is not bundled.** No check reads it, and it dominates a long
run: 2,000 snapshots measured 7.9 MB, so a T4 at one-day intervals is around 14 MB against
roughly 250 KB for everything verification uses. A bundle should be the evidence, not the
archive. Keep your own `snapshots.parquet` and link to it; the bundle carries the last row
as `final_snapshot.parquet`.

**Nothing here is magic.** The layout above is the whole format, so you can assemble a
bundle by hand, and `nttd verify` only reads files. The commands are a convenience.

nttd is self-hosted, so a submission cannot mean "we watched it happen". It means the
artifacts are internally consistent and the score is recomputable.

**`manifest.json` is a projection of `result.parquet`**, never a second source, so the two
cannot disagree. A field the run did not record does not appear: there is no `tier`, for
instance, because nothing records one; the resolved scenario ships instead and states the
actual bound.

The manifest also carries a **map digest** hashed from the terrain rather than from
`tiles.parquet`, since that file holds a session id and a timestamp. Measured across nine
independent sessions, seed 1001 gives the same digest every time, and other seeds differ,
which is what lets a verifier regenerate the world and compare.

There is no signature. With nobody operating nttd there is no key authority, so a
signature would prove authorship rather than honesty: a contestant signing their own
claim. The per-artifact digests are the load-bearing part, and they are tamper-evident
after the fact.

---

### `nttd verify`

```bash
uv run nttd verify -s ses_...                 # seconds
uv run nttd verify -s ses_... --regenerate    # ~15s, and the only route to 'verified'
uv run nttd verify <bundle-path> --json
```

**A self-check, not an authoritative verdict.** It runs on your machine, from code you
could have changed, so it predicts what a leaderboard will conclude rather than granting
anything. The verdict that counts is computed by the board's ingest, on infrastructure you
do not control and with its own copy of nttd and the GameScript.

So expect a submitted run to start out unjudged whatever this printed, and to gain a real
verdict when the board next runs its checks. That is not a lack of trust in your self-check;
it is that a verdict computed where the contestant controls the code cannot mean anything to
anyone else. nttd ships the checker; it does not host a board, and it stores no verdict.

Sharing the code is the point rather than a compromise: you should be able to predict the
outcome instead of being surprised by it. And nothing is written into the bundle -- a
bundle carrying its own verdict would assert something anyone could write.

| Verdict | Means |
|---|---|
| `verified` | the score was recomputed from the save **and** the world matches its declared seed |
| `replayed` | the score was recomputed from the save; the world was not reconciled |
| `unverified` | the artifacts do not support checking, so the score is self-reported |

The default path checks the artifact digests, inspects the save with `openttd -q`, reloads
it to recompute every company's score, and replays the action log for consistency. That
takes about 2 seconds and earns `replayed`, which is the intended bar.

`--regenerate` additionally rebuilds the world from its seed and compares terrain, which
is what earns `verified`. Measured at about 15 seconds for a 256x256 map: 64,516 tiles
regenerated and hashed.

What it catches, all measured against a real bundle:

| Tampering | Outcome |
|---|---|
| edit a score in `result.parquet` | `unverified` -- the digest no longer matches |
| edit the score *and* fix the digest | `unverified` -- the savegame does not support the score |
| swap the declared seed and fix the digest | `replayed` -- the regenerated world is a different world |

Exits non-zero only on `unverified`, so it works as a gate in a script without treating
`replayed` as a failure.

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
stepped scenario that simply omits it still ends on a wall clock, which is the one bound
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
| `result.parquet` | one row per scored company: the leaderboard artifact |
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

**"Cannot reach nttd server"**: start it with `nttd server`, or pass `--url`.

**`nttd analyze` says "Session not found"** while `nttd result` works: check
`NTTD_SESSIONS_DIR` is set for both. Both honour it.

**A scored scenario is refused**: run `nttd scenario validate` on it. Every violation
is reported at once, naming the setting and what it is fixed at.

**Actions time out while the game is paused**: expected for pathfinding.
`connect_road` and `connect_rail` yield through `Sleep(1)`, which counts game ticks, so
a long search cannot complete while paused. Stepped mode handles this by flushing with
the game running.

**No participant token**: the session was started without `--agent-companies`, so no
contestant company exists.
