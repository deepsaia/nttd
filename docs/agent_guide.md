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
| `blocked` | the scenario's action ceiling |

A `rejected` for an operator-tier action says so explicitly rather than "unknown
action", because an agent told only "no" retries forever.

### The ceiling

At most **15 actions per submission**, per company. Enough for a route — loan, two
stations, a connection, a vehicle, orders — with room to spare. A batch over the ceiling
is refused *whole* rather than part-executed, so a route planned as one batch never ends
up half-built.

Loops sharing a company share the ceiling. Scoring is per company, so three loops must
not get three times the actions of one.

There is no rate limit. How often you act is up to you.

---

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
to the same ceiling — a step is not one action.

An empty `actions` list is a legitimate move: waiting while vehicles earn is real play.

Or use the Gym wrapper, which is an ordinary client over these routes:

```python
from nttd.rl.env import NttdEnv     # needs: uv sync --extra rl

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

`examples/` and `agents/` hold working runners: a plain HTTP client, LangChain and
LangGraph agents, and a neuro-san multi-agent system whose coded tools call back into
`gs/query`. They are contestant-side code and will move to a separate `nttd-examples`
repository.
