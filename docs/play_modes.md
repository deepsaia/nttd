# Scenarios, play modes, and scoring

Three things decide what a run means: the **world** it was played on, the **mode** it was
played in, and the **contestant** that played it. This is what each one is allowed to be,
and what the record does with it.

For how the pieces fit together, see [architecture.md](architecture.md). For writing a
runner, [agent_guide.md](agent_guide.md).

---

## 1. The world

![What a scored run may be played on](images/scoreable_worlds.svg)

A scored run may vary exactly two things: how big the map is, and how hilly. Everything
else about generation is pinned.

**5 sizes × 5 terrain types = 25 maps.**

| | |
|---|---|
| `size_x` = `size_y` | 64, 128, 256, 512, 1024 |
| `terrain_type` | very_flat, flat, hilly, mountainous, alpinist |

### Why the map has to be square

Free axes give 5 × 5 = 25 rectangles that differ only in aspect ratio. A 64×1024 strip is
a different transport problem from a 256×256 square without being an interesting one, and
it would multiply the board by five for no gain. So one `size` list governs both axes and
a scored scenario must set them equal.

Squareness is a relation between two settings rather than a property of one, which a list
of permitted values cannot express, so it has its own check with its own message.

### Why landscape is locked

The four OpenTTD landscapes are not reskins. Cargo chains, town growth requirements, and
available industries all differ, so sub-arctic is really a separate benchmark from
temperate. Ranking them in one table before any of them has a populated board would
compare four problems as though they were one.

`landscape = "temperate"` is locked for now and expected to open up. It is still recorded
as a result column, because a free-play row should say which world it was and because the
column will start carrying information the day it varies.

### Where the variance actually comes from

The 25 maps are **families, not fixed boards**: any seed is admissible. Two runs on
256×256 flat with different seeds face genuinely different towns, industries and terrain.

`task_id` is a digest over the scenario id, version, seed, and normalised settings, so
runs on the same world group by themselves. Two people who independently describe the same
world land on the same `task_id` without coordinating.

### Everything else is pinned

`variety`, `smoothness`, `rivers`, `sea_level`, `map_edges`, `starting_year` (2020),
`town_names`, `number_towns`, `industry_density`, `landscape`.

These are the settings where a difference changes the problem without being visible to
anyone reading a score. Nobody looking at 812 can tell it was earned with denser industry.

`config/benchmark/profile.conf` is the single authority and is meant to be edited by hand.
`nttd scenario profile` prints what is in force.

---

## 2. Scoredness is computed, not declared

**`scored = true` is worth nothing on its own.** Anyone can write it above a world the
profile would never admit, so it is not what grants a run its status. Conformance is
computed from the config, and the flag can only ever narrow the answer:

| In the file | Result |
|---|---|
| nothing | scored if and only if the world conforms |
| `scored = false` | never scored. An opt-out, always honoured |
| `scored = true` | an assertion of conformance: honoured when it holds, **refused** when it does not |

The last row is the interesting one. An author who wrote `scored = true` meant to produce
a benchmark run, so they need to hear that the world is wrong rather than quietly get an
unscored one:

```
$ nttd scenario validate my_variant.conf
Invalid: my_variant.conf

  - map.landscape = 'sub-arctic' is fixed at 'temperate' for a scored run.
    Remove the key to inherit it, or drop scored = true to play it freely.
  - map.size_x = 256 and map.size_y = 512 differ: a scored map must be square.
    Rectangles only vary the aspect ratio ... Set both to the same value, or
    drop scored = true to play it freely.

2 problem(s). Fix them and re-run.
```

Every violation at once rather than the first, so a config can be fixed in one pass.

A scenario that simply does not conform and says nothing is free play, not an error.
Silence is an answer.

So **write your own scenarios**. There is no registry of blessed worlds and no approval
step: conformance is the whole credential. A conforming scenario you wrote yourself is a
benchmark run, and one that is not conforming is a game you played.

### What `scored` changes at runtime

A scored session refuses every game-mutating operator operation for its whole life, for
every caller, and records each attempt. That is the real protection, because it is session
state rather than a credential, and a self-hosting contestant holds every credential
anyway.

A refused attempt does not void the run, since nothing happened, but the result reports
`clean_run = false` and names what was tried. That way an accident is visible without
destroying an otherwise legitimate two-hour session.

Use `scored = false` when you want a conforming world **and** operator powers, which is
the normal case for debugging a scenario.

---

## 3. The two play modes

![Play modes: what each one measures](images/play_modes.svg)

### Real time

The world runs continuously at a fixed 1 wall-minute per economy month. Your loop
observes, decides, and submits whenever it is ready.

This measures play **and speed together**: a faster model takes more decisions in the same
economy horizon, and that is a real advantage it keeps. Bounded by wall-minutes.

**No action ceiling.** The world moves whether or not you act, so every action already
costs game time, and how much a contestant submits is its own business. That includes a
multi-agent system running several loops against one company: coordinating parallel work
is what such a system is for, and it pays for it in tokens.

One thing to know before writing a real-time loop: `state/full` is served from the last
GameScript refresh, so it **lags your own actions** by up to about 7 seconds. Observe, act,
observe again, and the second observation may still show pre-action state. Use
`changed_entities` from the action result as the authoritative immediate answer.

### Stepped

The game is **paused between steps**, so deliberation costs zero game-days. Verified live:
20 seconds of thinking advanced the game by 0 days.

This measures the policy **only**. A slow policy is not punished, which is the entire
point for RL and ES, where inference speed is an implementation detail rather than the
thing under test. Bounded by steps; a wall-clock bound is refused, because wall time in
stepped mode measures the contestant's hardware.

`POST /step` is synchronous: it fixes the target date, unpauses, flushes the batch,
advances, re-pauses, and returns the observation, so a policy never has to guess when its
actions took effect.

**No action ceiling here either.** A step carries as many actions as you care to send.
What bounds a stepped run is how many steps it takes and how many game-days each one
advances, both fixed by the scenario, so a larger batch cannot buy more world than
another contestant gets.

A multi-agent system still submits one batch per company per step, because the barrier
refuses a second concurrent step from the same company. How it divides that batch among
its own agents is its business.

### Which bounds are legal

| Mode | Bound | Why |
|---|---|---|
| real time | `time_limit.wall_minutes` | wall-minutes *are* the economy horizon |
| stepped | `max_heartbeats.count` | steps are the only meaningful unit |

`time_limit` defaults to **enabled at 60 minutes**, so a stepped scenario that simply
omits it would still end on a wall clock. nttd refuses that combination rather than letting
it look reasonable.

### Tiers fix time, not the world

The economy clock is fixed and no OpenTTD 15.3 setting changes it, so wall-minutes are the
economy horizon:

| Tier | Real time | Economy horizon | |
|---|---|---|---|
| T1 | 12 min | 1 game year | a route has time to earn, not only to stand |
| T2 | 24 min | 2 game years | |
| T3 | 60 min | 5 game years | economic performance becomes measurable |
| T4 | 120 min | 10 game years | longer-running businesses |

---

## 4. The contestants

Five kinds, all reaching the game through the same participant routes and all recorded the
same way.

| Contestant | Usual mode | Note |
|---|---|---|
| Human | real time **only** | joins the OpenTTD client on the session's `game_port` |
| Single LLM agent | either | |
| Multi-agent system | either | several loops sharing one company |
| RL policy | stepped | `nttd.rl.env.NttdEnv` |
| ES population | stepped | one session per candidate, same seed |

**Only one of those is a real constraint.** nttd never asks what kind of contestant you
are, so the column is convention, except for the human row: a stepped world stays paused
until a registered stepper calls `POST /step`, and an OpenTTD client has no way to do that.
Everything else is a choice, and an unusual one is legitimate as long as the mode is
recorded, which it is.

### An ES population is many sessions, not many companies

One session per candidate, all on the same seed, so every candidate faces the same world.
Sessions are independent processes on their own ports, so a generation parallelises.

Neither half of the overhead is what limits such a run. Setup and teardown measure about
**13 seconds** per episode against roughly 30 minutes of play for a T2 episode, and four
concurrent starts take about **8.6s** against 33s run serially. What bounds an ES run is
wall-clock play time, which is why parallelism is the lever worth pulling and session
startup is not.

### Multi-agent means several loops, one company

A coordinator plus specialists, all holding the same participant token. nttd sees one
company and writes one result row, so how many agents the system runs, and how they
decide, is its own business. In stepped mode they share one batch per step, so if one
agent spends 5 the rest have 10 between them; in real time there is no ceiling at all.

**Several contestant companies is not the other kind of multi-agent entry. It is
refused.** Two contestants sharing a map compete for the same towns and industries, which
is a different problem from a solo run on the same world, and nothing on a result row
records which it was.

That refusal is also why stepping is simple now. While several companies could share one
clock, each step waited for every registered stepper, because two companies each taking
one step advanced the world 60 days when staggered and 30 when simultaneous. One
contestant makes that unreachable rather than guarded against.

---

## 5. Scoring

**The board ranks `company_value`**, what the company is worth when the run ends, with
`total_cargo` breaking a tie and the entrant name breaking that in turn so the order is stable
rather than dependent on dict iteration. Rank is computed **per size and terrain, never
globally**: a 64x64 flat run and a 1024x1024 mountainous one are not competing, and numbering
them together would invite the comparison anyway.

`performance_rating`, OpenTTD's own quarterly rating from 0 to 1000, is published beside it and
does not decide position. It is nine capped components, cargo delivered over the last four
quarters being by far the largest at 400 of the 1000; the breakdown is in
[gameplay_guide.md](gameplay_guide.md#1-two-numbers-and-only-one-of-them-ranks).

Using the game's own figures rather than an nttd invention matters: both come from the game
rather than from anything nttd computes, neither is tuned to a strategy nttd happens to favour,
and neither can drift as nttd changes.

Two details a reader of a row needs:

- **An unrated company reports -1.** OpenTTD does not rate a company until it has a full
  quarter of history, and that value is carried through as the game gave it rather than
  being flattened to 0, so a run that was never rated is distinguishable from one that was
  rated badly. This matters most at T1, which is largely pre-revenue.
- **`total_cargo` is banked, not read back.** The counter the game exposes covers the
  quarter in progress and resets at every boundary. A 366 day run ends on 1 January, which
  is a boundary, so reading it at the end returns 0 however much the run carried. Each
  quarter is banked as it closes, and that total travels in the savegame so a verifier can
  recompute it.

There are no version columns on either the score or the metrics. Both ranked figures come
from the game, so a change to either is a bug fix rather than a change to what winning
means.

Company value does **not** rise by drawing a loan. It is assets minus the loan plus cash,
floored at 1, so borrowing converts one term into another and nets to zero until the money
buys something that earns. A company value of exactly 1 is a company that owes more than it
owns. See `docs/gameplay_guide.md` for the full derivation and the measured evidence.

One row per scored company in `result.parquet`, written when the session stops.

### Observed versus reported

The distinction the record keeps carefully, because nttd runs no model:

| Observed by nttd | Reported by the contestant |
|---|---|
| the score, from the game | model names and roles |
| every action and its outcome | prompt and completion tokens |
| the world and the seed | cost in USD |
| code provenance, profile version | framework, participant type |

Everything in the right column arrives through `POST /report` and is marked unverified,
because a contestant could put anything there. Marking it is the honest option:
`spend_is_reported` says so in the row, so nobody reads it as though nttd had measured it.

`(model, role)` is the key rather than the model alone, so one model in two roles stays
separate. [agent_guide.md](agent_guide.md#reporting-what-nttd-cannot-see) is where a
contestant is told how to send it, and why per model rather than one figure.

### What makes two rows comparable

Same `task_id`, `profile_version` and `runtime_mode`. All three are recorded, so a reader
can check rather than assume:

- **`task_id`** means the same world, including the seed.
- **`profile_version`** means the same admission rules. It is a digest of the rules
  themselves, not a hand-written number, so it changes exactly when they do.
- **`runtime_mode`** matters because real time scores speed and stepped does not.
  Comparing across them compares two different things.

---

## 6. Putting it together

```bash
uv run nttd server                                                # terminal 1

uv run nttd scenario profile                                      # the rules in force
uv run nttd scenario validate config/benchmark/t2_256_flat_1001_realtime.conf     # check before running

uv run nttd session create --config config/benchmark/t2_256_flat_1001_realtime.conf
uv run nttd session start -s <session> --agent-companies 1
uv run nttd session attach <session>                                # token and routes
uv run nttd runex                                                   # or your runner, by hand
uv run nttd session stop -s <session>
uv run nttd result -s <session>
```

`nttd benchmark --config <the same file>` is those three lifecycle commands in one, and it
waits for the end condition and writes the result rather than leaving you to stop it. Use the
four when you want to change something in between; neither is the blessed one.

Shipped examples, all scored on their own merits rather than because they say so. Four tiers in
both modes, and `config/benchmark/README.md` explains the day counts:

| Tier | Game span | Quarters | Stepped | Real time | World |
|---|---|---|---|---|---|
| T1 | 366 days | 4 | 366 steps of 1 day | 12 min | 256×256 flat 1001 |
| T2 | 731 days | 8 | 731 steps of 1 day | 24 min | 256×256 flat 1001 |
| T3 | 1827 days | 20 | 1827 steps of 1 day | 60 min | 512×512 hilly 2001 |
| T4 | 3653 days | 40 | 3653 steps of 1 day | 120 min | 512×512 hilly 2001 |

A tier is a span of game time, so both modes cover the same span: stepped counts steps, real
time uses the wall clock that produces those days at the fixed economy rate. The counts end
just past a quarter boundary, because the score is the rating of the last COMPLETED quarter.
