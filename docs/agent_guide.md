# Agent Configuration Guide

How to configure and run LLM agents and multi-agent systems (MAS) in nttd.

For CLI reference see `docs/cli_guide.md`. For simulation details see `docs/simulation_guide.md`.

---

## Agent Paradigms

nttd supports two agent paradigms:

**Single LLM agents** -- each agent is one LLM that observes game state, reasons with tools, and emits actions. Multiple agents can share a company. Framework: `langchain` or `openai`.

**Multi-agent systems (MAS)** -- a coordinated network of LLM agents running on an external server. nttd sends observations and receives action lists via HTTP. Framework: `mas` with a `mas_transport` block.

```
Single Agent:                    MAS:
  nttd --> LLM --> actions         nttd --> MAS server --> agent network
    ^       |                        ^         |              |
    +--tools--+                      +---HTTP callbacks-------+
                                               |
                                     <-- action list ---------+
```

---

## Scenario Configuration

Agents run inside scenarios defined in HOCON `.conf` files under `config/`.

### Quick Start

```bash
# Run a scenario with all agents
nttd benchmark run config/scenario_20min_2agent.conf

# Or register agents manually
nttd server start
nttd session create --name my-session
nttd agent register -s my-session -a road_agent -c 0 --observation-mode agent
nttd agent start -s my-session -a road_agent
```

### HOCON Structure

```hocon
scenario {
  name        = "my-scenario"
  description = "Description for logs"

  map { ... }
  companies { ... }
  runtime { ... }
  end_conditions { ... }
  agents = [ ... ]
}
```

---

## Map Configuration

```hocon
map {
  size_x          = 256          # Map width (64, 128, 256, 512, 1024, 2048)
  size_y          = 256          # Map height
  landscape       = "temperate"  # temperate | sub-arctic | sub-tropical | toyland
  terrain_type    = "hilly"      # flat | hilly | mountainous
  variety         = "none"       # none | very_low | low | medium | high | very_high
  smoothness      = "smooth"     # very_smooth | smooth | rough | very_rough
  rivers          = "medium"     # none | few | medium | many
  sea_level       = "medium"     # very_low | low | medium | high
  map_edges       = "random"     # all_water | all_land | random
  starting_year   = 1960
  town_names      = "english"
  number_towns    = "high"       # very_low | low | normal | high | custom
  custom_town_number = 0         # Only used when number_towns = "custom"
  industry_density = "normal"    # none | minimal | very_low | low | normal | high
}
```

## Company Configuration

```hocon
companies {
  num_ai_companies    = 0        # Built-in OpenTTD AIs (not nttd agents)
  competitors_interval = 0       # Minutes between AI company spawns
  max_loan            = 300000   # Maximum loan amount
}
```

## Runtime Configuration

```hocon
runtime {
  mode = "async_realtime"            # async_realtime | heartbeat
  game_speed = 1                     # 1=normal, 3=fast, 128=turbo
  snapshot_interval_days = 1         # World state capture frequency
  screenshot_interval_seconds = 0    # 0=disabled
  screenshot_type = "minimap"        # normal | giant | minimap
  save_interval_seconds = 0          # 0=disabled
}
```

## End Conditions

```hocon
end_conditions {
  logic = "any"                      # "any" = first condition wins, "all" = all must be met

  time_limit {
    enabled = true
    wall_minutes = 20                # Real-world minutes
  }

  game_date_limit {
    enabled = false
    end_year = 2000                  # In-game year
  }

  revenue_threshold {
    enabled = false
    total_revenue = 1000000          # Cumulative revenue target
  }

  cargo_threshold {
    enabled = false
    total_cargo_delivered = 50000    # Cumulative cargo units
  }

  max_heartbeats {
    enabled = false
    count = 1000                     # Heartbeat mode only
  }
}
```

---

## Agent Configuration

Each entry in the `agents` array defines one agent connection.

### Common Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `agent_id` | string | required | Unique agent identifier |
| `company_id` | int | required | Company to control (0-14) |
| `nttd_framework` | string | `"openai"` | `openai`, `langchain`, `mas`, or `passthrough` |
| `model` | string | `"gpt-4o"` | LLM model name (for single agents) |
| `agent_type` | string | `"road"` | Transport filter: `road`, `rail`, `air`, `water`, `general` |
| `instructions` | string | `""` | Inline system prompt |
| `instructions_file` | string | `""` | Path to instructions file or `module:function` |
| `observation_mode` | string | `"compact"` | Observation preset (see Observation Modes below) |
| `include_finance` | bool | `false` | Include detailed financial data |
| `poll_interval` | float | `5.0` | Seconds between observe-decide-execute cycles |
| `observation_tools` | bool | `true` | Enable mid-turn observation tool calls |
| `max_actions_per_cycle` | int | `10` | Maximum actions per cycle |
| `max_history_cycles` | int | `10` | Cycles of action history included in observation |
| `api_key_env` | string | `"OPENAI_API_KEY"` | Environment variable for LLM API key |

### MAS-Specific Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mas_transport.protocol` | string | `"custom"` | `http` for external MAS, `custom` for in-process |
| `mas_transport.mas_framework` | string | `"generic"` | `neuro_san` or `generic` |
| `mas_transport.endpoint` | string | `""` | MAS server URL |
| `mas_transport.timeout` | float | `60.0` | Request timeout in seconds |
| `mas_transport.retry_count` | int | `2` | Number of retries on failure |
| `mas_transport.retry_backoff` | float | `1.0` | Seconds between retries |

---

## Single-Agent Examples

### Road agent (simplest config)

```hocon
agents = [
  {
    agent_id          = "road_agent"
    company_id        = 0
    nttd_framework    = "langchain"
    model             = "gpt-5.2"
    agent_type        = "road"
    instructions_file = "examples/agent_instructions.py:get_road_agent_prompt"
    observation_mode  = "agent"
    poll_interval     = 10.0
    max_actions_per_cycle = 5
  }
]
```

### Two agents sharing a company

Both agents see the same company state and coordinate implicitly through
the shared game world. Each has its own cycle loop and transport specialization.

```hocon
agents = [
  {
    agent_id          = "road_agent"
    company_id        = 0
    nttd_framework    = "langchain"
    model             = "gpt-5.2"
    agent_type        = "road"
    instructions_file = "examples/agent_instructions.py:get_road_agent_prompt"
    observation_mode  = "agent"
    poll_interval     = 10.0
    max_actions_per_cycle = 5
  },
  {
    agent_id          = "rail_agent"
    company_id        = 0
    nttd_framework    = "langchain"
    model             = "gpt-5.2"
    agent_type        = "rail"
    instructions_file = "examples/agent_instructions.py:get_rail_agent_prompt"
    observation_mode  = "agent"
    poll_interval     = 10.0
    max_actions_per_cycle = 5
  }
]
```

Reference configs: `config/scenario_20min_1road.conf`, `config/scenario_20min_2agent.conf`, `config/scenario_30min_2agent.conf`.

---

## Multi-Agent System (MAS) Example

A MAS agent delegates reasoning to an external agent network. nttd posts
observations and receives action lists via HTTP.

```hocon
agents = [
  {
    agent_id          = "rail_mas"
    company_id        = 0
    nttd_framework    = "mas"
    agent_type        = "rail"
    observation_mode  = "mas_rail"
    include_finance   = true
    poll_interval     = 10.0
    max_actions_per_cycle = 50
    mas_transport {
      protocol      = "http"
      mas_framework = "neuro_san"
      endpoint      = "http://localhost:8080/api/v1/rail_mas/streaming_chat"
      timeout       = 300.0
      retry_count   = 1
      retry_backoff = 2.0
    }
  }
]
```

The MAS server must be running before starting the agent. For Neuro-SAN
setup details, see `examples/neuro_san_mas/README.md`.

Reference config: `config/scenario_20min_rail_mas.conf`.

---

## Observation Modes

The `observation_mode` field selects which game data sections the agent receives
each cycle. Larger observations give agents more context but cost more tokens.

| Mode | Sections | Size | Use Case |
|------|----------|------|----------|
| `minimal` | company | ~0.5 KB | Testing, smoke checks |
| `compact` | company, vehicles_summary, stations_count, top_towns, routes, route_planning | ~5 KB | Fast cycles, token-constrained agents |
| `agent` | company, vehicles_detail, stations_detail, top_towns, industries, routes, route_planning | ~15-30 KB | Single LLM agents that need full context |
| `mas_rail` | agent + subsidies | ~15-35 KB | Rail MAS with subsidy-aware route prioritization |
| `standard` | company, vehicles, stations, towns, industries | ~20-40 KB | Full entity lists, no route planning |
| `full` | all sections | ~40-80 KB | Complete world state, debugging |

**Section details:**

- `company` -- balance, loan, income, value, game date
- `vehicles_summary` -- total count, in-depot count (aggregate only)
- `vehicles_detail` -- per-vehicle: id, position, speed, orders, profit, depot status
- `stations_count` -- total station count (aggregate only)
- `stations_detail` -- per-station: id, name, position, cargo waiting/acceptance
- `towns` / `top_towns` -- town names, populations, coordinates
- `industries` -- all industries with production/accepted cargo labels
- `routes` -- derived routes with station pairs, vehicle counts, path tiles
- `route_planning` -- unserved cargo routes, town routes, existing route summaries
- `subsidies` -- active subsidies with cargo, source, destination

Custom observation modes can be registered via the API at runtime.

---

## Running a Benchmark

```bash
# Full benchmark from config file
nttd benchmark run config/scenario_20min_2agent.conf

# Analyze results after completion
nttd analyze -s <session_id>
nttd analyze -s <session_id> --save markdown,png
```

The benchmark command handles the full lifecycle: creates a session, starts
OpenTTD, registers agents, starts their cycle loops, monitors until end
conditions are met, and exports results.

---

## Troubleshooting

**Agent not producing actions**
- Check `nttd agent list -s <session_id>` for agent status
- Verify the LLM API key is set (check `api_key_env`)
- Look at agent logs in `logs/sessions/<session_id>/agents/<agent_id>.txt`

**MAS server not reachable**
- Verify the neuro-san server is running on the configured port
- Check `mas_transport.endpoint` URL is correct
- Increase `mas_transport.timeout` for complex agent networks

**Actions failing**
- Run `nttd analyze -s <session_id>` to see action success rates
- Check `previous_actions` in the observation for error messages
- Common: building on occupied tiles, insufficient funds, pathfinder failures

**Observation too large**
- Switch to a smaller observation mode (`compact` instead of `agent`)
- Reduce `max_history_cycles` to limit action history

**Agents competing for resources**
- Multiple agents on the same company share funds and infrastructure
- Use `agent_type` to filter tools by transport mode
- Lower `max_actions_per_cycle` to prevent one agent from monopolizing actions
