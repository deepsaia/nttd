# Writing a runner

nttd does not run your agent. You write a loop in your own process and reach the game
over HTTP. This is the contract that loop has to satisfy.

For the reasoning behind these boundaries rather than the mechanics, see
[architecture.md](architecture.md).

---

## What you need to start

Three things, all printed by `nttd session attach`:

```bash
uv run nttd session attach 20260815-132431ist-quiet-pickle
```

| | |
|---|---|
| **session id** | which run |
| **participant token** | which company: sent as `X-Participant-Token` |
| **base URL** | where the server is, `http://localhost:8000` by default |

The token is *addressing*, not a secret. It answers "which company is this action for"
in a form you cannot get wrong: the company is derived from the token server-side and
overwrites anything you put in the request body. Two companies means two tokens.

---

## The loop

```python
import requests

BASE  = "http://localhost:8000"
SID   = "20260815-132431ist-quiet-pickle"
TOKEN = "pt_1a70defa19f34e9eb..."

P = f"{BASE}/v1/participant/sessions/{SID}"
H = {"X-Participant-Token": TOKEN}


def run() -> None:
    while True:
        state = requests.get(f"{P}/state/full", timeout=60).json()
        for i, action in enumerate(decide(state)[:15]):
            requests.post(f"{P}/actions/submit", headers=H, timeout=120, json={
                "action_id": f"c{i}",
                "action_type": action["action_type"],
                "parameters": action["parameters"],
                "company_id": 0,          # ignored; the token decides
            })
```

That is the whole required surface. Everything below is detail.

---

## Observing

`GET /state/full` returns the **complete entitled game state**: towns, industries,
subsidies, and all of your own company's entities, each as a point on the map. Not rival
internals.

**It contains no terrain.** Measured on a 256x256 world, a full observation is about
13 KB and holds not one tile of ground. That is not a gap: an agent does not need a
picture of the map, and could not hold one anyway. Where something will actually fit is
answered by the `find_*` family, which dry-runs the real build inside the game, so a tile
one returns is a tile the game has already agreed to.

If you do want ground, `get_map_terrain` reports a band of it and is bounded by
`max_tiles` at every map size, telling you when it cut the band short and where to
resume. Reading a whole map is not a reasonable request: 256x256 is over half a megabyte,
roughly 389,000 tokens.

`GET /state/routes` answers the question most agents actually have: which producer and
consumer pairs are unserved, which town pairs have demand, how far apart they are, and
which transport modes could serve each. Filter it with `agent_type` to one mode.

It is deliberately not filtered for you: deciding what matters is part of the task, so a
scored run receives the complete entitled state and filtering is your code's job.
[architecture.md](architecture.md#observation-is-deliberately-unbounded) sets out what that
buys and what it costs.

`GET /state/compact?company_id=0` gives a smaller payload for development. A scored run
observes fully regardless.

### Finding out what you can do

```bash
uv run nttd actions --observations    # the 44 ways to read the world
uv run nttd actions --playable        # the 76 ways to change it
uv run nttd actions build_road_stop   # one action's parameters and defaults
```

Or read it as files, starting from [the index](actions/index.md), which is the cheap way in.

```
remove_order(vehicle_id, order_index|order_position)
build_train(engine_id, depot_tile|depot_x,depot_y, [cargo_id, num_wagons, wagon_id])
```

Required parameters first, then a choice as `a|b`, then optional ones in brackets. For
the full detail of one, follow through to [observations](actions/observations.md),
[actions](actions/actions.md), or run `nttd actions <name>`.

Nine operator actions exist and are not in any of this: no session can call one, so
documenting how to would only waste your context. They are named in
[the reference](action_reference.md) so you know what nttd holds back.

If you are calling nttd rather than reading it, use the endpoint instead. Same content,
already structured, no parsing:

```bash
curl localhost:8000/v1/public/actions                      # everything you may submit
curl localhost:8000/v1/public/actions?tier=read_only       # just the observations
curl localhost:8000/v1/public/actions/build_road_stop      # one action in full
```

Public tier, so it answers before a session exists. Working out what you can do should
not require starting a game first.

The listing leaves out the nine operator actions, and says so in an `excluded` field
rather than silently. A mistyped name gets the nearest matches back instead of a bare
404, so a typo costs one request rather than a refetch of the manifest.

Generated from the GameScript, so it cannot drift from what the game accepts. The same
description backs `POST /actions/interpret/validate`, which tells you what an action is
missing before you spend a round trip finding out:

```
plant_tree_rectangle missing required params: height, width, x, y
insert_order needs one of: station_id or dest_tile or destination
```

Two things there are worth knowing before you compose an action by hand.

**Some parameters take named constants, and the numbers are not guessable.** `order_flags`
is a bitmask you add together, and neighbouring meanings are not neighbouring values:
`OF_FULL_LOAD` is 64, `OF_NO_LOAD` is 128, and `OF_UNLOAD` and `OF_SERVICE_IF_NEEDED` are
both 4. The accepted values are listed with each parameter, read from the OpenTTD build
rather than written down, so they are right for the version you are playing.

**Some actions accept a choice rather than a fixed set.** `add_order` takes a station id
or a destination tile; anything placing something on the map takes `tile` or an `x,y`
pair. The reference says which, and the validator checks you supplied one of them.

Ids that the running game assigns are a third case: rail types, road types, cargo types,
bridge types and airport types are numbered per game and gated by year. Ask
(`get_rail_types`, `get_cargo_types`, and so on) rather than hard-coding what worked once.

### Read-only queries

`POST /state/gs/query?action=<name>` reaches the GameScript for things a snapshot does
not carry: finding a buildable tile, listing engines, pricing an action. Only the 44
read-only commands are accepted; a mutator is refused with a 403 that says so.

```python
spots = requests.post(f"{P}/state/gs/query?action=find_bus_stop_spots",
                      headers=H, json={"town_id": 22, "max_results": 3},
                      timeout=120).json()["result"]
```

Useful ones: `find_bus_stop_spots`, `find_station_spot`, `find_rail_depot_spot`,
`get_engines`, `get_rail_types`, `get_towns`, `get_industries`, `estimate_cost`.

`estimate_cost` prices an action without performing it, the way a human sees a cost in
the build cursor before clicking. It works while the game is paused, so a stepped policy
can price a whole batch during deliberation for free.

The finders use `GSTestMode()` dry-run validation, so a coordinate they return is one
the corresponding build will accept. Guessing tiles and handling the failures is
allowed, but it wastes a round trip and some of the game time you are spending.

### Building a route, by transport mode

| Mode | Primary action | Finders |
|---|---|---|
| Road | `connect_road` | `find_bus_stop_spots`, `find_depot_spots` |
| Rail | `connect_rail` | `find_station_spot`, `find_rail_depot_spot`, `get_engines` |
| Air | `build_airport` plus orders | `find_airport_spots`, `get_hangars` |
| Water | `build_dock`, `build_path` | `find_dock_spots`, `find_water_depot_spots` |

`connect_road` and `connect_rail` are whole-route actions: they pathfind and then build
the track, including bridges and tunnels. That makes them the two most expensive things
you can submit, and in stepped mode the reason the flush happens with the game running
rather than paused. Their pathfinder yields every 500 iterations, and that yield counts
game ticks, so a long search cannot complete while the world is stopped.

---

## Acting

`POST /actions/submit` takes one action. `POST /actions/submit-batch` takes a list and
returns a result per envelope, in order.

Five outcomes, and they mean different things:

| Status | Means |
|---|---|
| `success` | it happened; `changed_entities` says what |
| `partial` | a compound build laid part of what you asked; the world moved and was paid for, but the result is not usable |
| `failed` | the game refused it: bad tile, not enough money, no valid path |
| `rejected` | not in your vocabulary, or operator-tier |
| `blocked` | reserved; nothing issues it now that there is no action limit |

### Reading a failure

The error used to be one string carrying OpenTTD's error names, nttd's own sentences and
Squirrel exception text interchangeably, so acting on a failure meant matching substrings
that had no promise of staying the same. The machine-readable part is now separate:

```json
{"status": "failed", "error": "ERR_NOT_ENOUGH_CASH",
 "error_code": 257, "error_name": "ERR_NOT_ENOUGH_CASH", "error_category": "general"}
```

**`error_code` is present only when OpenTTD refused.** nttd's own precondition failures,
such as `Need tile or x,y`, carry no code, and that absence is how you tell the two apart:
one means the game said no, the other means the request never reached it. The first is
worth reacting to, the second is worth fixing.

The names come from the OpenTTD build itself rather than a table in nttd, so they are
right for the version you are playing.

### A route that only partly built is a failure

`connect_road`, `connect_rail` and `build_path` lay a whole route in one action, and one
segment that would not build leaves a gap. A gap means no route, so these report `partial`
unless every segment was laid. Do not read a reply as a working line without checking.

They also walk the finished route and ask the game whether it actually joins up, which is
a different question from whether the builds succeeded: a segment can build and still
leave the line unconnected, and `ERR_ALREADY_BUILT` says something is there but not that
it links to its neighbour. Any breaks come back in `gaps`.

They used to report `success` whatever happened, with the failures tucked inside the
result, which made a broken line indistinguishable from a working one to your code, the
action log and the reports.

A partial build still changed the world, so `changed_entities` comes back with it:

```json
{"status": "partial", "path_length": 24, "built": 19, "existing": 2,
 "failed": [{"x": 41, "y": 55, "action": "road", "error": "ERR_LAND_SLOPED_WRONG"}]}
```

`built` is what this call laid and paid for. `existing` is what was already there, which
counts towards the route being connected but cost nothing. They are separate because
adding them together overstates the work of laying a route across ground you already own.

The error names the first failure and how many there were, since the list can be long and
the first reason is usually the reason for all of them. Each entry in `failed` carries its
own `error_code` and `error_category`, because a route that ran out of money is a
different problem from one that hit a slope.

### Retrying is safe

`action_id` is yours to choose and doubles as an idempotency key. Resending an action that
has already finished returns what happened the first time rather than doing it again,
which matters for `connect_road`: it can run for two minutes, long enough for a proxy or
an impatient client to give up, and building the route twice would pay for it twice.

Reusing an id only replays an action that has *settled*. A resend while the first attempt
is still running is not answered from the log, because there is no result yet and
inventing one would be worse than doing the work twice. Two actions you genuinely want
performed twice need two different ids.

A `rejected` for an operator-tier action says so explicitly rather than "unknown
action", because an agent told only "no" retries forever.

### How many actions to take

Your call, in both modes. **There is no ceiling**, and none is coming: how much to attempt
per decision is part of what a benchmark should measure rather than something to equalise.
[play_modes.md](play_modes.md#3-the-two-play-modes) works through why capping it would buy
nothing, mode by mode.

## Stepped mode, for RL and ES

Stepped mode pauses the world between steps, so deliberation costs no game time and a slow
policy is not punished for being slow. That, and how a stepped run is bounded, is in
[play_modes.md](play_modes.md#stepped). Here is what it looks like to call.

```python
requests.post(f"{P}/step/reset", headers=H, timeout=180)     # opening observation

result = requests.post(f"{P}/step", headers=H, timeout=400, json={
    "actions": [{"action": "set_loan", "params": {"amount": 200_000}}],
}).json()

result["snapshot"]        # the world after the step
result["days_advanced"]   # what actually happened, not what was asked for
result["terminated"]      # an end condition fired
```

`/step` returns only after the world has advanced and been re-observed, so you never
have to guess when your actions took effect. A step carries a variable-length batch, up
as large as you like: a step is not one action.

An empty `actions` list is a legitimate move: waiting while vehicles earn is real play.

Or use the Gym wrapper, which is an ordinary client over these routes:

```python
from nttd.rl.env import NttdEnv

env = NttdEnv(session_id=SID, token=TOKEN)
obs, info = env.reset()
obs, reward, terminated, truncated, info = env.step(action)
```

`info["snapshot"]` is the full state. The ten-float observation vector is a convenience
for a baseline policy, not a limit: build your own encoder from the snapshot.

Reward is computed in the env, not by nttd. What to optimise is your choice.

`env.reset()` ignores `seed`: the world's seed belongs to the scenario, and letting an
env reseed mid-run would break reproducibility. To train across worlds, run one session
per seed.

---

## Several agents playing one company

A session holds **one contestant company**, in every mode. `--agent-companies 1` creates
it and issues one token, in `logs/sessions/<id>/participants.json`; `nttd session attach`
prints it. More than one is refused when the session starts.

A multi-agent entry is not several companies. It is several agents deciding together what
**one** company does: a planner, a surveyor, a finance agent, whatever your architecture
has. They agree on a batch of actions, and one runner submits it.

That runner is the only thing nttd sees, and the only thing that needs a token. How many
agents produced the batch, how they argued about it, and how long they took are yours to
arrange. In stepped mode there is no decision deadline, so a long deliberation costs
nothing but wall-clock.

```python
actions = orchestrator.decide(observation)   # however many agents, however long
result = step(session, actions)              # one call
```

### Why not several companies

A session holds **one** contestant company, and more than one is refused. Several agents
driving that one company is the supported shape; two contestants sharing a map is not, and
[play_modes.md](play_modes.md#4-the-contestants) says why.

Extra *non-contestant* companies are still available: `--ai-opponents N` creates idle
slots. They do not compete for cargo or town ratings.

### Stepped mode, concretely

- **Call `/step/reset` before your first `/step`.** It pauses the world, registers you as
  the stepper, and returns the opening observation. A `/step` without it gets a 409:
  served silently it would advance the world, and you would have a running clock you did
  not know you had started.
- **One step at a time.** A second `/step` while the first is still running gets a 409
  rather than being queued. Each step advances the world, so running two alongside each
  other would advance it twice for one step.
- **You are never truncated for thinking.** There is no decision deadline, and no
  liveness timeout: nothing else is waiting on you.

---

## Reporting what nttd cannot see

nttd runs no model, so it cannot observe which model you used, how many tokens you
spent, or what it cost. Tell it, and those land in the result marked as reported:

```python
requests.post(f"{P}/report", headers=H, json={
    "nttd_framework": "neuro-san",
    "participant_type": "mas",
    "models": [
        {"model": "claude-haiku-4.5", "role": "front_man",
         "prompt_tokens": 8_000, "completion_tokens": 600, "total_cost_usd": 0.012},
        {"model": "claude-opus-5", "role": "route_planner",
         "prompt_tokens": 40_000, "completion_tokens": 3_000, "total_cost_usd": 1.85},
    ],
})
```

Per model, because a multi-agent system routinely uses several and a cheap router in
front of one expensive planner is a different system from the same total spent uniformly.

Calls **accumulate**, so report each cycle's usage as your provider returns it rather
than holding totals yourself. It is optional: report nothing and you still get a complete
result row, since the action counts come from nttd's own log.

---

## What you may not do

**An agent may take any action a human can take through the GUI, and nothing more.**

A handful have no human equivalent and live behind the operator routes instead.
[action_reference.md](action_reference.md#the-actions-nobody-can-play) lists them with
what each one does, and it is generated from the game, so it cannot drift the way a copy
here would.

Everything a human *can* do is available, including the ones easy to miss: terraforming
(`raise_tile`, `lower_tile`, `level_tiles`), conditional orders, one-way roads, road
conversion, and `perform_town_action`: bribery and exclusive transport rights included,
because those are buttons in the town window.

`GET /v1/participant/sessions/{id}/actions/available` lists the vocabulary by category.

In a **scored** session, reaching for one is refused and recorded, and
[play_modes.md](play_modes.md#what-scored-changes-at-runtime) says what that costs you.
The short answer is nothing: the run still counts, because nothing happened.

---

## Reading the outcome

```bash
uv run nttd result -s <session>
```

Prints what the run scored and everything a reader would need to check it, including the
verification gaps: the things that would stop someone checking it at all.
[cli_guide.md](cli_guide.md#nttd-result) lists what it shows and its flags.

Two figures come back, both from the game. The board ranks `company_value`, with
`total_cargo` breaking a tie; `performance_rating` is OpenTTD's own composite judgement and is
published beside it without deciding position. Both are worth understanding before optimising
anything: [gameplay_guide.md](gameplay_guide.md#1-two-numbers-and-only-one-of-them-ranks) has
the rating's nine components with their caps and weights, three of which a one-year run cannot
win, and what company value is actually made of.

---

## Reference runners

Working runners live in a separate repository,
[deepsaia/nttd-workbench](https://github.com/deepsaia/nttd-workbench): a scripted policy
that needs no model, and a neuro-san multi-agent system whose coded tools call back into
`gs/query`. One per idea rather than one per SDK, because four copies of one loop drift in
four directions.

They are contestant-side code, and none of them import the `nttd` package. That is worth
knowing before you start: you do not need the engine installed to write an entry, and an
entry written in another language is on equal footing.

Start with `examples/minimal_runner.py`. It is the whole contract in one file and runs
without an API key. `uv run runex` there will pick it, find your open session, and attach
it for you.
