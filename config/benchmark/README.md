# Benchmark tiers

Eight example scenarios: four tiers, each in both runtime modes.

| tier | game span | quarters | stepped                | real time            | world              |
|------|-----------|----------|------------------------|----------------------|--------------------|
| T1   | 366 days  | 4        | 366 steps of 1 day     | 12 wall-minutes      | 256x256 flat 1001  |
| T2   | 731 days  | 8        | 731 steps of 1 day     | 24 wall-minutes      | 256x256 flat 1001  |
| T3   | 1827 days | 20       | 1827 steps of 1 day    | 60 wall-minutes      | 512x512 hilly 2001 |
| T4   | 3653 days | 40       | 3653 steps of 1 day    | 120 wall-minutes     | 512x512 hilly 2001 |

```
uv run nttd benchmark --config config/benchmark/t1_256_flat_1001_stepped.conf
```

## A tier is a span of game time, not a wall clock

Tiers are TIME tiers, not worlds: T1 and T2 are the same 256x256 flat seed 1001 map and differ
only in how much of the game is played. T3 and T4 share a larger, hillier world because a
longer run needs somewhere to grow into.

The span is what the tier means, so both modes cover the same game time. Stepped counts steps;
real time is bounded by the wall clock that produces the same span, since OpenTTD's economy
clock is fixed at about 1.97 seconds per game day and there is no speed multiplier.

## Why these exact day counts

The score is the rating of the last COMPLETED quarter, so a run must end just PAST a quarter
boundary. Ending just short publishes a score describing the company as it stood a quarter
earlier, and the last quarter of building is the one that changed most.

From the profile's 2020-01-01 start:

```
T1   366 days -> 2021-01-01    4 completed quarters
T2   731 days -> 2022-01-01    8
T3  1827 days -> 2025-01-01   20
T4  3653 days -> 2030-01-01   40
```

T2 is 366 rather than 365 because 2020 is a leap year: day 365 is 2020-12-31, which is still
inside Q4. The same leap day is why T3 is 731 and T4 is 1827.

## Steps are one game day

A step advances one day. Deliberation and construction cost no game time, because a step
flushes its actions while the game is paused, so a batch of any size advances exactly one day.
Measured: a batch taking 154.7 seconds of wall time advanced the same as an empty one.

That is what makes a one-day step usable. It was not always: when a flush ran with the world
moving, a slow batch could outrun its own interval.

## Why a stepped run is not bounded by wall time

In stepped mode the clock only advances when the contestant asks, so wall time would measure
how fast their hardware is rather than how much of the game was played, and a slow policy
would be cut off mid-run. nttd refuses that combination rather than letting it look
reasonable.

Real time is the opposite: the world moves whether or not the contestant acts, so it measures
decisions per minute as much as decision quality. Both are legitimate questions; they are not
the same question, and a T1 stepped result is not comparable with a T1 real-time one.

## What each tier measures

T1 and T2 are largely PRE-REVENUE. A transport company spends its first year building and its
later years earning, so two to four quarters mostly measures whether a contestant can get a
working route standing at all. Read a low score there as "did it build something that works",
not as "is this a good business".

Economic performance becomes measurable from T3, and T4 is where compounding shows: 20
quarters is long enough for a bad early network to cap a run that never went bankrupt.

## What you may vary, and what you may not

A scenario chooses its world size and terrain from these; everything else in `profile.conf` is
locked so two runs on a seed are the same problem.

```
size          64, 128, 256, 512, 1024
terrain_type  very_flat, flat, hilly, mountainous, alpinist
seed          any integer, and it is recorded with the result
```

Locked, and inherited rather than set: variety none, smoothness smooth, rivers medium,
sea_level medium, map_edges random, starting_year 2020, town_names english, number_towns
normal, industry_density normal, landscape temperate. Setting one in a scenario is refused
rather than silently honoured.

## Scoreability

A scenario is scored when its world conforms to `profile.conf`, which locks terrain generation
and the 2020 start so two runs on a seed are the same problem. It is computed from the config
rather than asserted by it: `scored = false` opts out, for playing a conforming world with
operator powers available. See `resolve_scored` in `config/scenario_config.py`.
