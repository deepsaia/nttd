# Playing nttd over MCP

Five tools, which is enough to play a whole game.

```
nttd_observe   read the world
nttd_act       change it, in real time
nttd_step      change it and advance, for stepped play
nttd_query     ask something the snapshot does not carry
nttd_actions   look up what an action takes
```

## Start a server

One server is one seat: a single session, a single participant token, one company. No
tool takes a session argument, so no client can address a game it was not given.

```bash
nttd session attach 20260815-132431ist-quiet-pickle          # prints the participant token
nttd mcp 20260815-132431ist-quiet-pickle --token tok_123     # stdio
```

For a framework that connects to a server already running rather than launching one:

```bash
nttd mcp 20260815-132431ist-quiet-pickle --token tok_123 --transport http --port 8100
```

Both transports exist because both kinds of client are real here. An agent that spawns
its tools as a subprocess wants stdio. A multi-agent system with its own process model
wants an address to connect to.

## Where the actions are

The obvious objection to five tools is that the actions have been hidden inside one of
them. They have not.

`action_type` is an **enum in the tool schema**, so a client receives every name it may
send as part of the tool definition, in the place it already looks. It never has to be
told them in a prompt, and a name that is not in the manifest cannot be sent at all.

Two enums, because the two verbs take different vocabularies:

| Tool | Vocabulary | Count |
|---|---|---|
| `nttd_act` | actions that change the world | 76 |
| `nttd_query` | actions that read it | 44 |

Operator actions are in neither: no session can run one, so offering it would be
advertising a refusal.

Both are built from the action manifest at import, so adding an action to the GameScript
and regenerating is the whole of exposing it over MCP. There is no list to keep here.

## Parameters

The names arrive in the schema; the parameters do not, because they differ per action and
there are 345 of them. `nttd_actions` gives them on demand:

```
nttd_actions()                        one line per action, for choosing
nttd_actions("build_road_stop")       parameters, types, defaults, accepted values
```

Three things there are worth reading rather than guessing.

**Named constants are not guessable.** `order_flags` is a bitmask you add together, and
neighbouring meanings are not neighbouring values: `OF_FULL_LOAD` is 64, `OF_NO_LOAD` is
128, and `OF_UNLOAD` and `OF_SERVICE_IF_NEEDED` are both 4. The accepted values come with
the parameter, read from the OpenTTD build rather than written down.

**Some actions accept a choice.** `add_order` takes a station id or a destination tile.
Anything placed on the map takes `tile` or an `x,y` pair. The `one_of` field says which.

**Some ids are assigned by the running game** and gated by year: rail types, road types,
cargo types, bridge types, engines. Ask with `nttd_query` rather than reusing a number
that worked in another game.

## Acting

`nttd_act` submits in real time. `nttd_step` submits and advances in one call, which is
what stepped play needs: the reply is the world after the moves landed, so nothing has to
guess when they took effect.

Send as many actions as you like. There is no per-call limit. A stepped run is bounded by
how many steps it takes and how many game-days each advances, both fixed by the scenario,
so a larger batch buys no more world than anyone else gets.

`nttd_act(moves, dry_run=True)` checks a batch without submitting it. Worth doing for
something you are unsure of, since a refused action still costs a round trip.

A refusal is ordinary play rather than a fault. Too little money, a tile that will not
take the structure, a town with a poor opinion of you.

## Observation

`nttd_observe` returns the whole state, not a summary. Deciding what matters is the task,
so nttd does not do that part first. Filter it in your own code.

What the snapshot does not carry is the live stuff: whether a tile is buildable, where a
station would fit, which engines exist this year, what a move would cost. That is
`nttd_query`, and `estimate_cost` in particular runs the action in test mode so nothing is
built and no money moves.

One query is not free of consequence despite being a read: `get_cargo_flows` resets the
cargo monitors, so a second call reports only what moved since the first.

## What this replaced

The previous server had 33 tools, 30 of them getters wrapping one REST call each, and no
way to act or step at all. Its own docstring said execution happened somewhere else, so
an agent connected to it could look at the game and do nothing.

That shape grew with the API rather than with the game: one tool per endpoint means every
new route is a new tool, and none of it was the action vocabulary, which is what an agent
actually needs.
