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
| T1 | 15 min | ~1.25 game years | build-skill tier, largely pre-revenue |
| T2 | 30 min | ~2.5 game years | |
| T3 | 60 min | ~5 game years | economic performance becomes measurable |
| T4 | 120 min | ~10 game years | longer-running businesses |

---

## 4. The contestants

Five kinds, all reaching the game through the same participant routes and all recorded the
same way.

| Contestant | Usual mode | Note |
|---|---|---|
| Human | real time **only** | joins the OpenTTD client on the session's `game_port` |
| Single LLM agent | either | |
| Multi-agent system | either | several loops sharing one company, or several companies |
| RL policy | stepped | `nttd.rl.env.NttdEnv` |
| ES population | stepped | one session per candidate, same seed |

**Only one of those is a real constraint.** nttd never asks what kind of contestant you
are, so the column is convention, except for the human row: a stepped world stays paused
until a registered stepper calls `POST /step`, and an OpenTTD client has no way to do that.
Everything else is a choice, and an unusual one is legitimate as long as the mode is
recorded, which it is.

### Multi-agent means two different things

Worth separating, because they are scored differently:

- **Several loops, one company.** A coordinator plus specialists, all holding the same
  participant token. nttd sees one company and writes one result row, so how many
  agents the system runs is its own business. In stepped mode they share one batch per
  step, so if one agent spends 5 the rest have 10 between them; in real time there is no
  ceiling at all.
- **Several companies, one each.** `--agent-companies N` gives one token per company. Each
  gets its own ceiling and its own result row, and they compete for cargo and town
  ratings.

For the second, stepped play gathers each company's step into a shared **window**: the
world advances once per window, so K steps is K intervals whether one company plays or
four. Without that, two companies each taking one step advanced the world 60 days when
staggered and 30 when simultaneous.

---

## 5. Scoring

`primary_score` is OpenTTD's own quarterly **performance rating**, 0–1000: a composite of
eight components, of which annual cargo delivered is the largest at 40%. `tiebreak_cargo`
breaks ties. `company_value` is recorded for display and does **not** affect rank, because
it rises simply by drawing a loan.

Using the game's own rating rather than an nttd invention matters: it is the number the
game itself considers success, it is not tuned to any strategy nttd happens to favour, and
it cannot drift as nttd changes.

Two details a reader of a row needs:

- **`rating_available`**. OpenTTD reports -1 until a company has a full quarter of
  history. An unavailable rating is recorded as 0 rather than -1, so a company that never
  earned one ranks below a company that did instead of above everything. The flag says
  which case a 0 is. This matters most at T1, which is largely pre-revenue.
- **`score_version`**. Bumped whenever the derivation changes, so a board can tell which
  entries are comparable instead of silently mixing definitions.

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

Per-model rather than one figure, because a multi-agent system routinely uses several, and
a cheap router in front of one expensive planner is a different system from the same total
spent uniformly. `(model, role)` is the key, so one model in two roles stays separate.

Reporting nothing still produces a complete result row: action counts come from nttd's own
log.

### What makes two rows comparable

Same `task_id`, `profile_version`, `score_version`, and `runtime_mode`. All four are
recorded, so a reader can check rather than assume:

- **`task_id`** means the same world, including the seed.
- **`profile_version`** means the same admission rules. It is a digest of the rules
  themselves, not a hand-written number, so it changes exactly when they do.
- **`score_version`** means the same scoring. Two rows under different versions are not
  the same measurement even on the same world.
- **`runtime_mode`** matters because real time scores speed and stepped does not.
  Comparing across them compares two different things.

`clean_run = false` means an operator power was reached for and refused. The run still
counts; the flag says a reader should look at what was attempted.

---

## 6. Putting it together

```bash
uv run nttd server                                                # terminal 1

uv run nttd scenario profile                                      # the rules in force
uv run nttd scenario validate config/benchmark/t2_example.conf     # check before running

uv run nttd session create --config config/benchmark/t2_example.conf
uv run nttd session start -s ses_... --agent-companies 1
uv run nttd session attach ses_...                                # token and routes
# ... your runner plays ...
uv run nttd session stop -s ses_...
uv run nttd result -s ses_...
```

Shipped examples, all scored on their own merits rather than because they say so:

| File | World | Mode |
|---|---|---|
| `t2_example.conf` | 256×256 flat | real time, 30 min |
| `t3_example.conf` | 512×512 hilly | real time, 60 min |
| `t2_stepped_example.conf` | 256×256 flat | stepped, bounded in steps |
