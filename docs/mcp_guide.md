# Playing nttd over MCP

Six tools play a whole game, for one agent or for many.

```
observe        read the world
act            send game commands, in every game mode
query          ask something the state does not carry
list_commands  look up what a command or query takes
focus          choose the part of the map the replies describe
batch_round    the calls of many agents for one round, for an orchestrator
```

A client that prefixes tool names with the server name sees `nttd_observe`, `nttd_act`,
and so on.

## Start a server

One server plays one session and one company.

```bash
nttd mcp 20260815-132431ist-quiet-pickle                              # stdio
nttd mcp 20260815-132431ist-quiet-pickle --transport http --port 8010 # for a framework
```

Both transports exist because both kinds of client are real. An agent that spawns its
tools as a subprocess wants stdio. A multi-agent system with its own process model wants
an address to connect to.

Flags:

| Flag | Meaning |
|---|---|
| `--token` | Participant token. A session that issued no tokens needs none. |
| `--company` | The company to play. Default 0. |
| `--days` | Game days per step in a stepped session. Unset uses the scenario's step size. Agents never see it. |
| `--reward` | Add `reward` to every act reply: the change in the company's money minus loan since the previous act. |
| `--seed` | Seed for the random order of the agents in a round. |
| `--default-tag` | The agent tag used when a call names none. Default `agent`. |

At start the server reads the session's mode. In a stepped session it registers as the
stepper with the game before the first command, so no client has to.

## Where the commands are

The game commands are not tools. `command` in `act` and `query` in `query` are enums in
the tool schema, so a client receives every name it may send as part of the tool
definition, and a name outside the manifest cannot be sent at all.

| Tool | Vocabulary | Count |
|---|---|---|
| `act` | commands that change the world | 78 |
| `query` | queries that read it | 46 |

Operator actions are in neither, and `list_commands` does not know them.

Both enums are built from the action manifest at import, so adding an action to the
GameScript and regenerating is the whole of exposing it over MCP.

## Parameters

The names arrive in the schema; the parameters do not, because they differ per command.
`list_commands` gives them on demand:

```
list_commands()                        one line per command and query
list_commands("build_road_stop")       parameters, types, defaults, accepted values
```

## Acting

`act` takes `moves`, a list of `{"command": <name>, "parameters": {...}}`, and runs them
in order. The reply carries the state after the moves and one result per command, each
with the command's `action_id`, its status and any error.

The server picks the game route from the session's mode. In a stepped session every
`act` is one step, and an empty `moves` list passes the day. In a heartbeat or real-time
session the commands run when they arrive and the game keeps its own clock.

`act(moves, dry_run=True)` checks the names and parameters without sending anything.

## Observation

`observe` returns the whole state. Two fields are reshaped for reading: a company's
`income` is named `revenue_last_quarter`, since it holds the revenue of the last completed
quarter, and a vehicle's `state` is a word rather than a code.

What the state does not carry is `query`: whether a tile is buildable, where a station
fits, which engines exist this year, what a command would cost.

## Focus

`focus` names towns or industries, or gives a tile rectangle, and from then on that
agent's replies from `observe` and `act` list only what is inside the rectangle, with an
index of the places outside. `focus(clear=True)` removes it. The company, the date and
the command results stay complete.

## Several agents

Every tool except `batch_round` takes an optional `agent_tag`. It names the caller for
the focus, for the `action_id` of each command (`<tag>:<n>`), and for the `agent_id`
column of the session's action log. A single agent leaves it empty and gets the default
tag.

Several agents calling `act` one after another each make their own step in a stepped
session. An orchestrator that wants its agents to act in the same moment sends their
calls through `batch_round`:

```
batch_round(entries=[
  {"agent_tag": "a", "tool": "act", "args": {"moves": [...]}},
  {"agent_tag": "b", "tool": "focus", "args": {"towns": ["Weston"]}},
  {"agent_tag": "c", "tool": "observe", "args": {}},
])
```

The server runs the reads first, then sends every agent's moves together with the agents
in a random order, advances the game once, and answers `{"results": {agent_tag: result}}`.
Each agent gets its own command results and the shared state after the round, cut to its
own focus. An error in one entry is reported in that agent's result and leaves the
others intact. With `--reward`, every agent that acted gets the whole change in money
minus loan; dividing it is the orchestrator's decision.
