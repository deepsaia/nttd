# nttd CLI Guide

The `nttd` CLI is the primary interface for running OpenTTD AI simulations. Everything -- server management, session lifecycle, agent registration, and benchmarks -- is driven from the command line using HOCON configuration files.

---

## Installing OpenTTD

nttd requires OpenTTD 15.2 or later installed on your system.

### macOS

```bash
# Homebrew
brew install openttd

# Or download the .dmg from https://www.openttd.org/downloads/openttd-releases/latest
# After installing, the binary is at:
#   /Applications/OpenTTD.app/Contents/MacOS/openttd
```

### Linux

```bash
# Debian / Ubuntu
sudo apt-get install openttd

# Fedora
sudo dnf install openttd

# Arch
sudo pacman -S openttd

# Or download from https://www.openttd.org/downloads/openttd-releases/latest
```

### Windows

1. Download the installer from https://www.openttd.org/downloads/openttd-releases/latest
2. Run the installer and note the install path (default: `C:\Program Files\OpenTTD`)
3. Set the environment variable:
   ```powershell
   $env:NTTD_OPENTTD_BINARY = "C:\Program Files\OpenTTD\openttd.exe"
   ```

OpenTTD downloads base graphics (OpenGFX) automatically on first launch. If running headless on a server, launch OpenTTD once manually to trigger this download.

---

## Prerequisites

- OpenTTD installed (see above)
- Python 3.13+ with nttd installed:
  ```bash
  uv sync              # core dependencies
  uv sync --extra agents  # adds LangChain + OpenAI adapters for AI agents
  ```
- The `ottd_config/` base configuration directory (ships with this repo)
- An LLM API key if running AI agents:
  ```bash
  export OPENAI_API_KEY=sk-...
  # or for Anthropic models:
  export ANTHROPIC_API_KEY=sk-ant-...
  ```

---

## Quick Start

```bash
# 1. Start the nttd API server
nttd server

# 2. Create a session from config
nttd session create --config config/scenario.conf
# Returns: ses_abc123def456

# 3. Start the session (spawns OpenTTD, auto-starts orchestrator)
nttd session start ses_abc123def456 --agent-companies 1

# 4. Register an agent
nttd agent register \
  --session ses_abc123def456 \
  --agent-id road_builder \
  --company-id 0 \
  --framework langchain \
  --model gpt-4o \
  --instructions-file examples/agent_instructions.py:get_road_agent_prompt

# 5. Start the agent's cycle loop
nttd agent start --session ses_abc123def456 --agent-id road_builder

# 6. Watch it run, then stop when done
nttd session status ses_abc123def456
nttd session stop ses_abc123def456
```

Or run everything at once with `nttd benchmark`:

```bash
nttd benchmark --config config/scenario.conf --speed 1 --output results/
```

---

## Commands

### `nttd server`

Start the nttd FastAPI server. All other commands communicate with this server via HTTP.

```bash
nttd server [--host HOST] [--port PORT] [--reload] [--log-level LEVEL]
```

| Option        | Default     | Description                    |
|---------------|-------------|--------------------------------|
| `--host`      | `127.0.0.1` | Bind address                  |
| `--port`      | `8000`      | HTTP port                      |
| `--reload`    | off         | Auto-reload on code changes    |
| `--log-level` | `info`      | Logging level                  |

The server must be running before using any `session`, `agent`, or `benchmark` command.

**Environment variables:**

| Variable                 | Default                                            | Description                 |
|--------------------------|----------------------------------------------------|-----------------------------|
| `NTTD_ADMIN_PASSWORD`    | `nttd`                                             | OpenTTD admin port password |
| `NTTD_OPENTTD_BINARY`    | `/Applications/OpenTTD.app/Contents/MacOS/openttd` | Path to OpenTTD binary      |
| `NTTD_BASE_CONFIG`       | `ottd_config`                                      | Base config directory       |
| `NTTD_SESSIONS_DIR`      | `logs/sessions`                                    | Session data directory      |
| `NTTD_PORT_RANGE_START`  | `4000`                                             | First port for sessions     |

---

### `nttd session`

Manage session lifecycle. Each session owns one OpenTTD server process.

#### `nttd session create`

Create a new session from a HOCON config file. Stores settings but does not start OpenTTD yet.

```bash
nttd session create --config config/scenario.conf [--name "my_run"]
```

Returns a session ID like `ses_abc123def456` used in all subsequent commands.

#### `nttd session start`

Spawn an OpenTTD server for the session. Allocates ports, applies map/company settings, starts the game, and auto-starts the orchestrator (snapshot capture, screenshots, saves, end condition monitoring).

```bash
nttd session start <session_id> [--agent-companies N] [--ai-opponents N]
```

| Option              | Description                                          |
|---------------------|------------------------------------------------------|
| `--agent-companies` | Number of idle company slots for nttd agents (0-14)  |
| `--ai-opponents`    | Number of built-in OpenTTD AI opponents              |

Use `--agent-companies` to pre-create company slots that your agents will control. After starting, you can connect to the game as a spectator at `127.0.0.1:<game_port>`.

#### `nttd session stop`

Stop the OpenTTD server and finalize session data (merges Parquet fragments, updates session.conf).

```bash
nttd session stop <session_id>
```

#### `nttd session list`

List all sessions with their status.

```bash
nttd session list
```

#### `nttd session status`

Show detailed information about a session, including game port and live state if running.

```bash
nttd session status <session_id>
```

---

### `nttd agent`

Register and control AI agents within a running session. Each agent targets a company (0-14) and runs an autonomous observe-decide-act cycle loop.

#### `nttd agent register`

Register an agent with the session's gameloop. The agent is created but not yet running.

```bash
nttd agent register \
  --session <session_id> \
  --agent-id <name> \
  --company-id <0-14> \
  [--framework openai|langchain|passthrough] \
  [--model gpt-4o] \
  [--instructions-file prompts/road.txt] \
  [--instructions "You are a road transport specialist..."] \
  [--poll-interval 5.0] \
  [--observation-mode compact|full]
```

| Option                | Default       | Description                                   |
|-----------------------|---------------|-----------------------------------------------|
| `--session`, `-s`     | (required)    | Session ID                                    |
| `--agent-id`, `-a`    | (required)    | Unique identifier for this agent              |
| `--company-id`, `-c`  | (required)    | OpenTTD company slot (0-14)                   |
| `--framework`, `-f`   | `openai`      | LLM framework adapter                         |
| `--model`, `-m`       | `gpt-4o`      | Model name passed to the adapter              |
| `--instructions-file` | (none)        | Path to instructions (text or `file.py:func`) |
| `--instructions`      | (none)        | Inline system prompt                           |
| `--poll-interval`     | `5.0`         | Seconds between cycles                         |
| `--observation-mode`  | `compact`     | `compact` (own company) or `full` (everything) |

**Frameworks:**

- **`openai`**: Calls the OpenAI API via the `openai` Python SDK. Requires `OPENAI_API_KEY`.
- **`langchain`**: Calls an LLM via LangChain. Auto-detects provider from model name. Requires `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`.
- **`passthrough`**: No LLM. Returns empty actions each cycle. Useful for testing without API costs.

**Instructions file formats:**

```bash
# Plain text file
--instructions-file prompts/road_builder.txt

# Python function that returns the prompt string
--instructions-file examples/agent_instructions.py:get_road_agent_prompt
```

#### `nttd agent start`

Start the agent's cycle loop.

```bash
nttd agent start --session <session_id> --agent-id <name>
```

#### `nttd agent stop`

Stop the agent's cycle loop. The agent remains registered but stops running.

```bash
nttd agent stop --session <session_id> --agent-id <name>
```

#### `nttd agent list`

List all agents in a session with their status and cycle counts.

```bash
nttd agent list --session <session_id>
```

---

### `nttd benchmark`

All-in-one command that creates a session, starts OpenTTD, registers agents from config, runs until an end condition is met, and exports results.

```bash
nttd benchmark \
  --config config/scenario.conf \
  [--speed 3] \
  [--ai-opponents 2] \
  [--output results/]
```

| Option            | Default    | Description                           |
|-------------------|------------|---------------------------------------|
| `--config`, `-c`  | (required) | HOCON scenario config with agents     |
| `--speed`         | from config| Override game speed multiplier         |
| `--ai-opponents`  | from config| Override AI opponent count             |
| `--output`, `-o`  | (none)     | Directory for JSON results export      |

The benchmark command requires agents to be defined in the HOCON config (see below). Press `Ctrl+C` to stop early.

---

## HOCON Configuration

All session configuration lives in a single HOCON file (typically `config/scenario.conf`). The file controls map generation, company setup, runtime settings, end conditions, and agent definitions.

### Example

```hocon
scenario {
  name        = "road_benchmark"
  description = "Two AI agents competing on transport routes"

  map {
    size_x         = 256
    size_y         = 256
    landscape      = "temperate"    # temperate | sub-arctic | sub-tropical | toyland
    terrain_type   = "hilly"        # flat | hilly | mountainous | alpinist | custom
    variety        = "none"         # none | very_low | low | medium | high | very_high
    smoothness     = "smooth"       # very_smooth | smooth | rough | very_rough
    rivers         = "medium"       # none | few | medium | many
    sea_level      = "medium"       # very_low | low | medium | high | custom
    map_edges      = "random"       # random | manual | all_water
    starting_year  = 1950
    town_names     = "english"
    number_towns   = "normal"       # very_low | low | normal | high | custom
    industry_density = "normal"     # funding_only | minimal | very_low | low | normal | high | custom
  }

  companies {
    num_ai_companies = 0            # built-in OpenTTD AIs (not nttd agents)
    competitors_interval = 0        # minutes between AI starts (0 = immediate)
    max_loan = 300000
  }

  runtime {
    mode       = "async_realtime"   # async_realtime | heartbeat
    game_speed = 3                  # 1=normal, 3=fast, 128=turbo

    # Game-days between Parquet snapshot captures (1 = every in-game day)
    snapshot_interval_days = 1

    # Periodic minimap screenshot capture (works in headless mode)
    screenshot_interval_seconds = 60   # 0 = disabled
    screenshot_type = "minimap"        # normal | giant | minimap

    # Periodic .sav game save
    save_interval_seconds = 300        # 0 = disabled
  }

  end_conditions {
    logic = "any"                   # any | all

    time_limit {
      enabled      = true
      wall_minutes = 30             # real-world minutes
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

  # Agents are registered and started automatically by `nttd benchmark`
  agents = [
    {
      agent_id          = "road_builder"
      company_id        = 0
      framework         = "langchain"
      model             = "gpt-4o"
      agent_type        = "road"
      instructions_file = "examples/agent_instructions.py:get_road_agent_prompt"
      observation_mode  = "compact"
      poll_interval     = 10.0
    },
    {
      agent_id          = "rail_planner"
      company_id        = 1
      framework         = "langchain"
      model             = "gpt-4o-mini"
      agent_type        = "rail"
      instructions      = "You are a rail transport specialist..."
      observation_mode  = "compact"
      poll_interval     = 15.0
    }
  ]
}
```

### Agent Config Fields

| Field                   | Default            | Description                              |
|-------------------------|--------------------|------------------------------------------|
| `agent_id`              | (required)         | Unique identifier within the session     |
| `company_id`            | (required)         | OpenTTD company slot (0-14)              |
| `framework`             | `"openai"`         | `openai`, `langchain`, or `passthrough`  |
| `model`                 | `"gpt-4o"`         | Model name for the LLM adapter           |
| `instructions`          | `""`               | Inline system prompt                     |
| `instructions_file`     | `""`               | Path to prompt file or `file.py:func`    |
| `observation_mode`      | `"compact"`        | `compact` (own company) or `full`        |
| `poll_interval`         | `5.0`              | Seconds between agent cycles             |
| `observation_tools`     | `true`             | Enable observation tool-calling          |
| `max_actions_per_cycle` | `10`               | Safety limit on actions per cycle        |
| `api_key_env`           | `"OPENAI_API_KEY"` | Environment variable for LLM API key     |
| `agent_type`            | `"road"`           | Transport type: `road`, `rail`, `air`, `water` |

### Supported Models

The LangChain adapter auto-detects the provider from the model name:

| Model prefix | Provider  | Env var              | Examples                              |
|-------------|-----------|----------------------|---------------------------------------|
| `gpt`       | OpenAI    | `OPENAI_API_KEY`     | `gpt-4o`, `gpt-4o-mini`              |
| `claude`    | Anthropic | `ANTHROPIC_API_KEY`  | `claude-sonnet-4-6-20250514`, `claude-haiku-4-5-20251001` |

---

## Internal Settings Keys

When creating a session via the REST API, you can pass a `settings` dict to override values. These keys use **flattened internal names** (prefixed with `_`), not the HOCON config paths.

This is an important distinction: the HOCON config file uses hierarchical paths like `end_conditions.time_limit.wall_minutes = 30`, but the internal system flattens these to `_ec_wall_minutes`. When overriding via the API, always use the internal key.

### Runtime Settings

| Internal Key                    | HOCON Path                               | Type   | Default          | Description                       |
|---------------------------------|------------------------------------------|--------|------------------|-----------------------------------|
| `_runtime_mode`                 | `runtime.mode`                           | string | `async_realtime` | `async_realtime` or `heartbeat`   |
| `_game_speed`                   | `runtime.game_speed`                     | int    | `1`              | Game speed multiplier             |
| `_snapshot_interval_days`       | `runtime.snapshot_interval_days`         | int    | `1`              | Game-days between snapshots       |
| `_screenshot_interval_seconds`  | `runtime.screenshot_interval_seconds`    | int    | `60`             | Seconds between screenshots (0=off) |
| `_screenshot_type`              | `runtime.screenshot_type`                | string | `minimap`        | `normal`, `giant`, or `minimap`   |
| `_save_interval_seconds`        | `runtime.save_interval_seconds`          | int    | `300`            | Seconds between saves (0=off)     |

### End Condition Settings

| Internal Key       | HOCON Path                                    | Type  | Description                         |
|--------------------|-----------------------------------------------|-------|-------------------------------------|
| `_ec_logic`        | `end_conditions.logic`                        | string| `any` or `all`                      |
| `_ec_wall_minutes` | `end_conditions.time_limit.wall_minutes`      | float | Wall-clock minutes before auto-stop |
| `_ec_end_year`     | `end_conditions.game_date_limit.end_year`     | int   | In-game year to stop at             |
| `_ec_revenue`      | `end_conditions.revenue_threshold.total_revenue` | int | Revenue target to stop at           |
| `_ec_cargo`        | `end_conditions.cargo_threshold.total_cargo_delivered` | int | Cargo delivered target to stop at |

End condition keys are only written when the corresponding condition is `enabled = true` in the HOCON config. To enable an end condition via API override, just set the internal key (e.g., `_ec_wall_minutes = "15"`) -- its presence enables the condition.

### Example: Override via REST API

```bash
# Create session with 5-minute wall-clock limit
curl -s -X POST http://localhost:8000/admin/sessions/new \
  -H "Content-Type: application/json" \
  -d '{
    "name": "quick-test",
    "config_path": "config/scenario.conf",
    "settings": {
      "_ec_logic": "any",
      "_ec_wall_minutes": "5"
    }
  }'
```

Note: explicit `settings` values override config-derived values, so you can use a base config file and selectively change end conditions or runtime parameters.

---

## Session Data Output

Each session stores all data under `logs/sessions/<session_id>/`:

```
logs/sessions/<session_id>/
  session.conf            # Session metadata and settings (HOCON)
  agents.conf             # Agent configs and final stats (HOCON)
  snapshots.parquet       # Game state time-series (companies, towns, vehicles)
  tiles.parquet           # Terrain data
  actions.parquet         # All agent actions with parameters
  agent_cycles.parquet    # Per-cycle telemetry (timing, action counts)
  events.parquet          # Lifecycle and game events
  screenshot/             # Periodic minimap screenshots (.png)
  save/                   # Periodic game saves (.sav)
```

Screenshots and saves use timestamped filenames like `d712283-06apr2026-182323pdt.png` where `d712283` is the in-game date. The final save gets a `_final` suffix.

---

## REST API (Direct Usage)

The CLI commands wrap the nttd REST API. You can also drive the system with `curl` or any HTTP client.

### Session Management

| Method | Endpoint                       | CLI Equivalent        |
|--------|--------------------------------|-----------------------|
| POST   | `/admin/sessions/new`          | `nttd session create` |
| POST   | `/admin/sessions/{id}/start`   | `nttd session start`  |
| POST   | `/admin/sessions/{id}/stop`    | `nttd session stop`   |
| GET    | `/admin/sessions`              | `nttd session list`   |
| GET    | `/admin/sessions/{id}`         | `nttd session status` |

### Agent Management

| Method | Endpoint                                                    | CLI Equivalent        |
|--------|-------------------------------------------------------------|-----------------------|
| POST   | `/sessions/{id}/gameloop/agents/register`                   | `nttd agent register` |
| POST   | `/sessions/{id}/gameloop/agents/{agent_id}/start`           | `nttd agent start`    |
| POST   | `/sessions/{id}/gameloop/agents/{agent_id}/stop`            | `nttd agent stop`     |
| GET    | `/sessions/{id}/gameloop/agents`                            | `nttd agent list`     |
| GET    | `/sessions/{id}/gameloop/agents/{agent_id}/status`          | (none)                |
| GET    | `/sessions/{id}/gameloop/agents/{agent_id}/cycles?limit=50` | (none)                |

### Observation and Control (for external agents)

| Method | Endpoint                                  | Description                      |
|--------|-------------------------------------------|----------------------------------|
| GET    | `/sessions/{id}/status`                   | Game state (date, speed, paused) |
| GET    | `/sessions/{id}/snapshot`                 | Full world state snapshot        |
| POST   | `/sessions/{id}/speed?speed=N`            | Set game speed                   |
| POST   | `/sessions/{id}/actions/interpret`        | Submit actions for execution     |

### Example: REST-only Workflow

```bash
# 1. Start the nttd server
uv run uvicorn nttd.api.app:app --host 0.0.0.0 --port 8000 &
sleep 3

# 2. Create a session
SESSION=$(curl -s -X POST http://localhost:8000/admin/sessions/new \
  -H "Content-Type: application/json" \
  -d '{"name": "my-run"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")
echo "Session: $SESSION"

# 3. Start the session (spawns OpenTTD, auto-starts orchestrator)
curl -s -X POST "http://localhost:8000/admin/sessions/$SESSION/start" \
  -H "Content-Type: application/json" \
  -d '{"agent_companies": 1}'
sleep 5

# 4. Verify the world is populated
curl -s "http://localhost:8000/sessions/$SESSION/state/compact?company_id=0" | python3 -m json.tool

# 5. Register and start an agent
curl -s -X POST "http://localhost:8000/sessions/$SESSION/gameloop/agents/register" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "road_builder",
    "company_id": 0,
    "framework": "langchain",
    "model": "gpt-4o",
    "agent_type": "road",
    "poll_interval": 10.0
  }'
curl -s -X POST "http://localhost:8000/sessions/$SESSION/gameloop/agents/road_builder/start"

# 6. Monitor
curl -s "http://localhost:8000/sessions/$SESSION/gameloop/agents/road_builder/status" | python3 -m json.tool

# 7. Stop
curl -s -X POST "http://localhost:8000/sessions/$SESSION/gameloop/agents/road_builder/stop"
curl -s -X POST "http://localhost:8000/admin/sessions/$SESSION/stop"
```

### Standalone Agent Script

You can also run agents as standalone scripts that call the REST API directly:

```bash
# OpenAI model
OPENAI_API_KEY=sk-... uv run python examples/langchain_nttd_agent.py \
  --session-id $SESSION --company-id 0 --model gpt-4o --tools

# Anthropic model
ANTHROPIC_API_KEY=sk-ant-... uv run python examples/langchain_nttd_agent.py \
  --session-id $SESSION --company-id 0 --model claude-sonnet-4-6-20250514 --tools
```

---

## Spectating

While agents run, connect to the game in OpenTTD:

1. Open OpenTTD
2. Multiplayer -> Add server -> `127.0.0.1:<game_port>`
3. Join as spectator (company 255)
4. Watch AI companies build infrastructure in real time

Find the game port with `nttd session status <session_id>`.

---

## Running Tests

```bash
uv run pytest                     # Run all tests
uv run pytest tests/ -v           # Verbose output
uv run pytest tests/test_foo.py   # Single file
uv run ruff check src/ tests/     # Lint
uv run ruff check --fix src/      # Auto-fix lint issues
```

---

## Troubleshooting

**`Cannot reach nttd server at http://localhost:8000`**
Start the server first: `nttd server`

**`Session not found or not running`**
Check `nttd session list`. The session must be in `active` status for agent operations.

**`Gameloop not initialized for this session`**
The session needs to be started (`nttd session start`) before registering agents.

**`Environment variable OPENAI_API_KEY not set`**
Set your API key: `export OPENAI_API_KEY=sk-...` (required for `openai` and `langchain` frameworks, not for `passthrough`).

**OpenTTD process exits immediately**
Check that `NTTD_OPENTTD_BINARY` points to a valid OpenTTD binary and that `ottd_config/` exists with a valid configuration. Run OpenTTD manually once to download base graphics.

**No screenshots or saves appearing**
Screenshots and saves require the orchestrator to be running (auto-started with `session start`). Check that `screenshot_interval_seconds` and `save_interval_seconds` are non-zero in your scenario config.

**Session data missing after stop**
Session data (Parquet files, screenshots, saves, conf files) is preserved in `logs/sessions/<session_id>/`. Only OpenTTD config artifacts are cleaned up on stop.
