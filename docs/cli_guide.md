# nttd CLI Guide

The `nttd` CLI is the primary interface for running OpenTTD AI simulations. Everything — server management, session lifecycle, agent registration, and benchmarks — is driven from the command line using HOCON configuration files.

## Prerequisites

- OpenTTD installed (macOS: `/Applications/OpenTTD.app`, or set `NTTD_OPENTTD_BINARY`)
- Python 3.11+ with nttd installed (`uv sync`)
- The `ottd_config/` base configuration directory (ships with nttd)

## Quick Start

```bash
# 1. Start the nttd API server
nttd server

# 2. Create a session from config
nttd session create --config config/scenario.conf

# 3. Start the session (spawns OpenTTD)
nttd session start ses_abc123

# 4. Register an agent
nttd agent register \
  --session ses_abc123 \
  --agent-id my_agent \
  --company-id 0 \
  --framework openai \
  --model gpt-4o \
  --instructions-file prompts/bus.txt

# 5. Start the agent's cycle loop
nttd agent start --session ses_abc123 --agent-id my_agent

# 6. Watch it run, then stop when done
nttd agent list --session ses_abc123
nttd session status ses_abc123
nttd session stop ses_abc123
```

Or run everything at once with `nttd benchmark`:

```bash
nttd benchmark --config config/scenario.conf --speed 3 --output results/
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

| Variable              | Default                                          | Description                |
|-----------------------|--------------------------------------------------|----------------------------|
| `NTTD_DB_PATH`        | `nttd.db`                                        | SQLite database path       |
| `NTTD_ADMIN_PASSWORD` | `nttd`                                           | OpenTTD admin port password|
| `NTTD_OPENTTD_BINARY` | `/Applications/OpenTTD.app/Contents/MacOS/openttd` | Path to OpenTTD binary   |
| `NTTD_BASE_CONFIG`    | `ottd_config`                                    | Base config directory      |
| `NTTD_SESSIONS_DIR`   | `runs`                                           | Session data directory     |
| `NTTD_PORT_RANGE_START` | `4000`                                         | First port for sessions    |

---

### `nttd session`

Manage session lifecycle. Each session owns one OpenTTD server process.

#### `nttd session create`

Create a new session from a HOCON config file. This stores settings and end conditions in the database but does not start OpenTTD yet.

```bash
nttd session create --config config/scenario.conf [--name "my_run"]
```

| Option     | Description                           |
|------------|---------------------------------------|
| `--config` | Path to HOCON scenario config file    |
| `--name`   | Optional session name (default: from config) |
| `--url`    | Override nttd server URL              |

Returns a session ID like `ses_abc123def456` used in all subsequent commands.

#### `nttd session start`

Spawn an OpenTTD server for the session, apply map/company settings, and start the game.

```bash
nttd session start <session_id> [--ai-opponents N]
```

| Option            | Description                                |
|-------------------|--------------------------------------------|
| `--ai-opponents`  | Override number of built-in AI opponents    |

After starting, you can connect to the game as a spectator at `127.0.0.1:<game_port>`.

#### `nttd session stop`

Stop the OpenTTD server and archive the session.

```bash
nttd session stop <session_id>
```

#### `nttd session list`

List all sessions with their status.

```bash
nttd session list
```

#### `nttd session status`

Show detailed information about a session, including live game state if running.

```bash
nttd session status <session_id>
```

---

### `nttd agent`

Register and control AI agents within a running session. Each agent occupies one company (0-14) and runs an autonomous observe-decide-act cycle loop.

#### `nttd agent register`

Register an agent with the session's gameloop. The agent is created but not yet running.

```bash
nttd agent register \
  --session <session_id> \
  --agent-id <name> \
  --company-id <0-14> \
  [--framework openai|langchain|passthrough] \
  [--model gpt-4o] \
  [--instructions-file prompts/my_agent.txt] \
  [--instructions "You are a bus transport specialist..."] \
  [--poll-interval 5.0] \
  [--observation-mode compact|full]
```

| Option                | Default       | Description                                   |
|-----------------------|---------------|-----------------------------------------------|
| `--session`, `-s`     | (required)    | Session ID                                    |
| `--agent-id`, `-a`    | (required)    | Unique identifier for this agent              |
| `--company-id`, `-c`  | (required)    | OpenTTD company slot (0-14)                   |
| `--framework`, `-f`   | `openai`      | LLM framework adapter                        |
| `--model`, `-m`       | `gpt-4o`      | Model name passed to the adapter              |
| `--instructions-file` | —             | Path to instructions (text or `file.py:func`) |
| `--instructions`      | —             | Inline system prompt                          |
| `--poll-interval`     | `5.0`         | Seconds between cycles                        |
| `--observation-mode`  | `compact`     | `compact` (own company) or `full` (everything)|

**Frameworks:**

- **`openai`** — Calls the OpenAI API via the `openai` Python SDK. Requires `OPENAI_API_KEY` env var.
- **`langchain`** — Calls an LLM via LangChain's `ChatOpenAI`. Requires `langchain-openai` installed and `OPENAI_API_KEY`.
- **`passthrough`** — No LLM. Returns empty actions each cycle. Useful for testing the gameloop without API costs.

**Instructions file formats:**

```bash
# Plain text file
--instructions-file prompts/bus_builder.txt

# Python function that returns the prompt string
--instructions-file examples/agent_instructions.py:get_bus_agent_prompt
```

#### `nttd agent start`

Start the agent's cycle loop. The gameloop will begin calling the LLM and executing actions.

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
| `--output`, `-o`  | —          | Directory for JSON results export      |
| `--url`           | auto       | nttd server URL                        |

The benchmark command requires agents to be defined in the HOCON config (see below). Press `Ctrl+C` to stop early.

---

### `nttd logs`

Read or tail JSONL event logs from the `runs/` directory.

```bash
nttd logs [--run <path>] [--follow] [--last 40] [--log-dir runs]
```

| Option      | Default | Description                          |
|-------------|---------|--------------------------------------|
| `--run`     | latest  | Path to a specific JSONL log file    |
| `--follow`  | off     | Tail mode (like `tail -f`)           |
| `--last`    | `40`    | Number of recent lines to show       |
| `--log-dir` | `runs`  | Directory containing log files       |

### `nttd tensorboard`

Launch TensorBoard pointing at the runs directory.

```bash
nttd tensorboard [--log-dir runs] [--port 6006]
```

---

## HOCON Configuration

All session configuration lives in a single HOCON file (typically `config/scenario.conf`). The file controls map generation, company setup, end conditions, runtime settings, and agent definitions.

### Full Example

```hocon
scenario {

  name        = "bus_benchmark"
  description = "Two AI agents competing on bus routes"

  map {
    size_x         = 256
    size_y         = 256
    landscape      = "temperate"   # temperate | arctic | tropic | toyland
    terrain_type   = 1             # 0=flat, 1=hilly, 2=mountainous
    starting_year  = 1950
    number_towns   = 2             # 0=very_low .. 4=very_high
    industry_density = 4           # 0=none .. 5=very_high
  }

  companies {
    num_ai_companies = 0           # built-in OpenTTD AIs (not nttd agents)
    max_loan         = 300000
  }

  runtime {
    mode       = "async_realtime"  # async_realtime | heartbeat
    game_speed = 3                 # 1=normal, 3=fast, 128=turbo
  }

  end_conditions {
    logic = "any"                  # any | all

    time_limit {
      enabled      = true
      wall_minutes = 30            # real-world minutes
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
      agent_id          = "bus_builder"
      company_id        = 0
      framework         = "openai"
      model             = "gpt-4o"
      instructions_file = "examples/agent_instructions.py:get_bus_agent_prompt"
      observation_mode  = "compact"
      poll_interval     = 5.0
    },
    {
      agent_id          = "rail_planner"
      company_id        = 1
      framework         = "langchain"
      model             = "gpt-4o-mini"
      instructions      = "You are a rail transport specialist..."
      observation_mode  = "compact"
      poll_interval     = 8.0
    }
  ]
}
```

### Agent Config Fields

| Field                  | Default        | Description                              |
|------------------------|----------------|------------------------------------------|
| `agent_id`             | (required)     | Unique identifier within the session     |
| `company_id`           | (required)     | OpenTTD company slot (0-14)              |
| `framework`            | `"openai"`     | `openai`, `langchain`, or `passthrough`  |
| `model`                | `"gpt-4o"`     | Model name for the LLM adapter           |
| `instructions`         | `""`           | Inline system prompt                     |
| `instructions_file`    | `""`           | Path to prompt file or `file.py:func`    |
| `observation_mode`     | `"compact"`    | `compact` (own company) or `full`        |
| `poll_interval`        | `5.0`          | Seconds between agent cycles             |
| `observation_tools`    | `true`         | Enable observation tool-calling          |
| `max_actions_per_cycle`| `10`           | Safety limit on actions per cycle        |
| `api_key_env`          | `"OPENAI_API_KEY"` | Environment variable for LLM API key |

---

## Typical Workflows

### Manual step-by-step (development / debugging)

```bash
# Terminal 1: start server
nttd server --reload

# Terminal 2: create and run
nttd session create --config config/scenario.conf
nttd session start ses_abc123
nttd agent register -s ses_abc123 -a bus -c 0 -f passthrough
nttd agent start -s ses_abc123 -a bus
nttd agent list -s ses_abc123

# Join as spectator in OpenTTD → 127.0.0.1:4000

# When done:
nttd agent stop -s ses_abc123 -a bus
nttd session stop ses_abc123
```

### Automated benchmark

```bash
# Terminal 1: start server
nttd server

# Terminal 2: run benchmark (blocks until end condition)
OPENAI_API_KEY=sk-... nttd benchmark \
  --config config/scenario.conf \
  --speed 3 \
  --output results/
```

### Spectating a benchmark

While a session is running, open OpenTTD and connect to `127.0.0.1:<game_port>` as a spectator (company 255). You'll see agent companies building infrastructure, buying vehicles, and setting up routes in real time.

Find the game port with:

```bash
nttd session status <session_id>
```

---

## REST API Reference

The CLI commands are thin wrappers around the nttd REST API. You can also call the API directly.

### Session Management

| Method | Endpoint                                   | CLI Equivalent          |
|--------|--------------------------------------------|-------------------------|
| POST   | `/admin/sessions/new`                      | `nttd session create`   |
| POST   | `/admin/sessions/{id}/start`               | `nttd session start`    |
| POST   | `/admin/sessions/{id}/stop`                | `nttd session stop`     |
| GET    | `/admin/sessions`                          | `nttd session list`     |
| GET    | `/admin/sessions/{id}`                     | `nttd session status`   |

### Gameloop / Agent Management

| Method | Endpoint                                                    | CLI Equivalent          |
|--------|-------------------------------------------------------------|-------------------------|
| POST   | `/sessions/{id}/gameloop/agents/register`                   | `nttd agent register`   |
| POST   | `/sessions/{id}/gameloop/agents/{agent_id}/start`           | `nttd agent start`      |
| POST   | `/sessions/{id}/gameloop/agents/{agent_id}/stop`            | `nttd agent stop`       |
| GET    | `/sessions/{id}/gameloop/agents`                            | `nttd agent list`       |
| GET    | `/sessions/{id}/gameloop/agents/{agent_id}/status`          | —                       |
| GET    | `/sessions/{id}/gameloop/agents/{agent_id}/cycles?limit=50` | —                       |
| GET    | `/sessions/{id}/gameloop/status`                            | —                       |

### Observation & Control (for external agents)

| Method | Endpoint                                    | Description                      |
|--------|---------------------------------------------|----------------------------------|
| GET    | `/sessions/{id}/status`                     | Game state (date, speed, paused) |
| GET    | `/sessions/{id}/snapshot`                   | Full world state snapshot        |
| POST   | `/sessions/{id}/speed?speed=N`              | Set game speed                   |
| POST   | `/sessions/{id}/mode?mode=async_realtime`   | Set runtime mode                 |
| POST   | `/sessions/{id}/actions/interpret`          | Submit actions for execution     |

---

## Troubleshooting

**`Cannot reach nttd server at http://localhost:8000`**
Start the server first: `nttd server`

**`Session not found or not running`**
Check `nttd session list`. The session must be in `active` status for agent operations.

**`Gameloop not initialized for this session`**
The session needs to be started (`nttd session start`) before registering agents.

**`Company N already has agent X`**
Each company can have only one agent. Use a different `--company-id`.

**`Environment variable OPENAI_API_KEY not set`**
Set your API key: `export OPENAI_API_KEY=sk-...` (required for `openai` and `langchain` frameworks, not for `passthrough`).

**OpenTTD process exits immediately**
Check that `NTTD_OPENTTD_BINARY` points to a valid OpenTTD binary and that `ottd_config/` exists with a valid configuration.
