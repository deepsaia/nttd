# Writing a runner

nttd does not run your agent. You write a loop in your own process and reach the game
over HTTP. This is the contract that loop has to satisfy.

For the reasoning behind these boundaries rather than the mechanics, see
[architecture.md](architecture.md).

---

## What you need to start

Three things, all printed by `nttd session attach`:

```bash
uv run nttd session attach ses_20260805_120000_abcd1234
```

| | |
|---|---|
| **session id** | which run |
| **participant token** | which company — sent as `X-Participant-Token` |
| **base URL** | where the server is, `http://localhost:8000` by default |

The token is *addressing*, not a secret. It answers "which company is this action for"
in a form you cannot get wrong: the company is derived from the token server-side and
overwrites anything you put in the request body. Two companies means two tokens.

---

## The loop

```python
import requests

BASE  = "http://localhost:8000"
SID   = "ses_20260805_120000_abcd1234"
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
subsidies, the map, and all of your own company's entities. Not rival internals.

It is deliberately not filtered for you. Deciding what matters is part of the task, so
nttd hands over everything and leaves filtering to your code — that is where it belongs
in a multi-agent design, and it stops information differences confounding scores. The
practical consequence is that a naive agent pays more tokens per step. That is the
intended incentive.

`GET /state/compact?company_id=0` gives a smaller payload for development. A scored run
observes fully regardless.

### Read-only queries

`POST /state/gs/query?action=<name>` reaches the GameScript for things a snapshot does
not carry — finding a buildable tile, listing engines, pricing an action. Only the 44
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

Four outcomes, and they mean different things:

| Status | Means |
|---|---|
| `success` | it happened; `changed_entities` says what |
| `failed` | the game refused it — bad tile, not enough money, no valid path |
| `rejected` | not in your vocabulary, or operator-tier |
| `blocked` | reserved; nothing issues it now that there is no action limit |

A `rejected` for an operator-tier action says so explicitly rather than "unknown
action", because an agent told only "no" retries forever.

### How many actions to take

Your call, in both modes. There is no ceiling.

That is deliberate: how much to attempt per decision is part of what a benchmark should
measure, not something to equalise. A multi-agent system coordinating parallel work, an
RL policy batching a whole route, and an agent taking one action at a time are making
different bets, and each pays for its own in tokens and compute.

Nothing is bought by capping it. In real time the world moves whether or not you act, so
every action already costs game time. In stepped mode the run is bounded by how many
steps it takes and how many game-days each one advances, both fixed by the scenario, so
a larger batch cannot buy you more world than anyone else gets.

Loops sharing a company share nothing but the company: nttd sees one contestant and
writes one result row, and how many agents you run inside it is your business.

## Stepped mode, for RL and ES

Real-time is a wall-clock race. Stepped mode is not: the game is paused between steps,
so deliberation costs no game time.

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
as large as you like — a step is not one action.

An empty `actions` list is a legitimate move: waiting while vehicles earn is real play.

Or use the Gym wrapper, which is an ordinary client over these routes:

```python
from nttd.rl.env import NttdEnv

env = NttdEnv(session_id=SID, token=TOKEN)
obs, info = env.reset()
obs, reward, terminated, truncated, info = env.step(action)
```

`info["snapshot"]` is the full state. The ten-float observation vector is a convenience
for a baseline policy, not a limit — build your own encoder from the snapshot.

Reward is computed in the env, not by nttd. What to optimise is your choice.

`env.reset()` ignores `seed`: the world's seed belongs to the scenario, and letting an
env reseed mid-run would break reproducibility. To train across worlds, run one session
per seed.

---

## Playing several companies in one session

Start the session with `--agent-companies N`. You get one token per company, in
`logs/sessions/<id>/participants.json`, and `nttd session attach` prints them.

### Real-time

Nothing special. Each company acts on its own cadence with its own token. The ceiling and
the score are per company, and observation is full state for everyone, so nobody has an
information edge. Using one company's token to target another is refused:

```
Token is scoped to company 0 but the request targets company 1
```

Be aware that every company's actions go through one GameScript, so a rival issuing long
`connect_rail` calls will slow your submissions. That is the game's shared resource, not
something nttd schedules around.

### Stepped

The clock is shared, so steps are gathered into **windows**. Every registered stepper has
to arrive before the world advances, and then everyone gets the same observation and the
same step number. This is what keeps a two-company run comparable to a one-company run:
K steps is K intervals either way, rather than 2K.

What that means for your runner:

- **Call `/step/reset` before your first `/step`.** It registers you as a stepper. A
  `/step` without it gets a 409 telling you so, because the barrier has to know who it is
  waiting for.
- **Your `/step` blocks until every other stepper has arrived.** That is not a bug to work
  around with a shorter timeout; use a generous one.
- **You are never truncated for thinking.** There is no decision deadline. There is a
  10-minute liveness timeout, after which a silent company is dropped from the barrier for
  the rest of the run and the remaining companies carry on without it.
- **One step per company per window.** A second concurrent `/step` from the same company
  gets a 409: two batches in one window would make a step mean two different things.
- `result["steppers"]` lists whose actions were in the window, so you can tell whether a
  rival was still playing.

For self-play or population training from a single process:

```python
import json
from nttd.rl.multi_env import NttdParallelEnv

tokens = {int(k): v for k, v in json.load(open(f"logs/sessions/{SID}/participants.json")).items()}
env = NttdParallelEnv(session_id=SID, tokens=tokens)

observations, infos = env.reset()
observations, rewards, terminations, truncations, infos = env.step({
    "company_0": [{"action": "set_loan", "params": {"amount": 200_000}}],
    "company_1": [],
})
```

The PettingZoo `ParallelEnv` shape. It issues the N step calls concurrently because each
one blocks until the window closes, so serial calls would deadlock on the first. An agent
you leave out of the dict still steps with an empty batch, for the same reason.

If you are running N independent policies in N processes instead, use N `NttdEnv`
instances and nothing else: the server's barrier already synchronises them.

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
front of one expensive planner is a different system from the same total spent
uniformly. `role` is part of the key, so one model in two roles stays separate.

Calls **accumulate**, so report each cycle's usage as your provider returns it rather
than holding totals yourself. Optional: a contestant that reports nothing still gets a
complete result row, because action counts come from nttd's own log.

---

## What you may not do

An agent may take any action a human can take through the GUI, and nothing more.

Nine actions are operator-only because a human has no equivalent:
`change_bank_balance`, `set_max_loan`, `create_subsidy` (a human can only *claim* an
offered subsidy), `found_town`, `expand_town`, `set_town_growth`, `change_town_rating`,
`set_cargo_goal`, `set_game_setting`.

Everything a human *can* do is available, including the ones easy to miss: terraforming
(`raise_tile`, `lower_tile`, `level_tiles`), conditional orders, one-way roads, road
conversion, and `perform_town_action` — bribery and exclusive transport rights included,
because those are buttons in the town window.

`GET /v1/participant/sessions/{id}/actions/available` lists the vocabulary by category.

In a **scored** session, reaching for an operator power is refused and recorded. It does
not void your run — nothing happened — but the result reports `clean_run = false` and
names what was attempted.

---

## Reading the outcome

```bash
uv run nttd result -s ses_...
```

Shows the score, the task identity, code provenance, per-model spend, and an explicit
list of verification gaps — the things that would stop someone checking your run.

The score is OpenTTD's own `performance_rating`: a 0–1000 composite of cargo delivered,
profitable vehicles, station coverage, vehicle profit, quarterly revenue, cargo
diversity, cash, and loan status. Cargo delivered breaks ties.

---

## Reference runners

Working runners live in a separate repository,
[deepsaia/nttd-examples](https://github.com/deepsaia/nttd-examples): a minimal HTTP
runner, a scripted policy, LangChain and LangGraph agents, and a neuro-san multi-agent
system whose coded tools call back into `gs/query`.

They are contestant-side code, and none of them import the `nttd` package. That is worth
knowing before you start: you do not need the engine installed to write an entry, and an
entry written in another language is on equal footing.

Start with `examples/minimal_runner.py`. It is the whole contract in one file and runs
without an API key.
