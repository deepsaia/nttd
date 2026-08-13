# Agent network design, from playing nttd by hand

Working notes for the five neuro-san networks: one per transport mode, plus a combined one.

**Status, stated plainly.** One session was played on seed 581017999 (T1 stepped, 256x256 flat),
and it did not reach a running train. The nine remaining sessions have not been played. What is
below is what the attempt taught, and the findings are the point: every trap here is one an
agent network has to survive, and each was found by hitting it rather than by reading code.

Two nttd bugs were found and one is already fixed. See "Bugs found while playing".

---

## 1. The single most important finding: a stepped run used to lose its own clock

A stepped session ran **unpaused** from the moment OpenTTD spawned until the contestant's first
`step/reset`. The world moved during OpenTTD's boot, the 64,516 tile scan, and any latency in
the agent's own startup.

Measured: the first session opened at game day **737939 = 2020-05-29**. It should have opened at
737790 = 2020-01-01. **149 of 182 days, 82 percent of the run, were gone before the first
action.**

Fixed in PR #93: `Orchestrator.pause_at_start()`, called for stepped mode only. The same session
now opens at 737790 with the full 100,000 in cash.

**Design consequence.** An agent network can deliberate as long as it likes between steps and it
costs nothing in game time. Multi-agent deliberation, several LLM calls per step, a planning
phase that reads the whole map: all free. This is the property that makes a *network* of agents
viable rather than a single fast policy. Do not design around latency; design around step count.

---

## 2. The economics, which decide what every network optimises

- `performance_rating` is OpenTTD's own 0-1000 composite and is the leaderboard rank. It needs a
  **full completed quarter** before it reports anything but -1, so a T1 run of two quarters has
  very few rating observations. Optimising it directly inside a short run is close to blind.
- **Expenses are negative.** `GSCompany.GetQuarterlyExpenses` returns negative money, confirmed
  across 1,626 recorded samples with no positive case. Profit is `q0_income + q0_expenses`.
  Subtracting inverts every margin. This exact mistake was live in nttd's own RL env until PR #92.
- A company starts with **100,000 cash and a 100,000 loan already drawn**, against a 300,000
  ceiling. So there is headroom, and interest is running from day one. Idle cash is a cost.
- The rating is not the only measure: company value and revenue matter too, and value is
  inflated by simply drawing a loan, which is why the rating is the primary score.

**Design consequence.** For a two-quarter run, optimise **cargo delivered and revenue**, and
treat rating as a lagging confirmation. A network that waits for rating feedback gets none.

---

## 3. The API traps, each hit for real

These are the ones that cost time. Every one belongs in a coded_tool so no agent meets it.

| Trap | What happens | What to do |
| --- | --- | --- |
| Action envelope | Parameters at the top level give 422 | `{"action": ..., "params": {...}}`. nttd's error says so precisely, so surface it verbatim to the agent |
| `find_station_spot` is singular | `find_station_spots` returns **403 "not a read-only query"**, not "unknown action" | Read names from the manifest, never guess |
| Thin list queries | `get_industries` carries `accepted` but **not** `produces_cargo`. Pairing industries is impossible from the bulk query | One `get_industry_info` per industry, 42 calls on this map. Cache it |
| `accepted` vs `accepts_cargo` | Alphabetically first, easily misread as the same thing | They differ: `accepted` carries stockpile |
| Terrain tuple order | `[height, slope, flags, owner]`. Reading `t[1]` as flags reads slope | flags are `t[2]` |
| Occupancy is opt-in | Without `occupancy: true`, flags carry only water/coast/buildable. Decoding with rail/road/station bits reads **trees as rail** | Always pass `occupancy: true` when asking where track is |
| Row width | Rows are **254** wide on a 256 map, with no `from_x` | x = index + 1. The void edges are excluded |
| Step response key | `action_results`, not `results` | Reading the wrong key hid a partial build entirely: the step looked silent and successful |

---

## 4. Rail is the hardest mode, and the reason is platform geometry

The route attempted: Iron Ore Mine [17] (161,235) to Steel Mill [6] (178,232), 20 tiles,
a live producer at 88 IORE last month with **transported 0**, into a mill accepting IORE at 112.
A textbook pair. It still did not connect, in three distinct ways:

1. **First attempt.** `connect_rail` built 17 of 19 tiles and reported a partial. `can_build`
   then went **false**, because its own partial track blocked a fresh plan. A failed connect
   makes the corridor worse, not neutral.
2. **Second attempt.** The mill station was built along **y**, so track arriving from the west
   met the platform's **side**. A train cannot enter a platform sideways: `trace_route` from the
   mill reached exactly 3 tiles, the platform itself, isolated. I had taken the nearest spot,
   distance 1, without checking its orientation suited my approach.
3. **Third attempt.** A new station along **x** at (176,231), which the finder offered with
   `valid_directions [0,1]` and IORE acceptance 112. `connect_rail` then reported "every segment
   built, but the line is not continuous: 1 of 5 have no through connection, first at (175,231)"
   — the turn from north-south into east-west needs a curve piece that did not join.

**Design consequence, and this is the core of the rail network.** Station orientation is not a
detail to be delegated to a spot finder that ranks by distance. It must be chosen from the
*approach direction*, which means planning the route before choosing the station. The correct
order is:

    pick cargo pair -> plan the corridor (check_connection) -> derive the approach heading at
    each end -> choose a spot whose valid_directions contains that heading -> build stations ->
    connect -> VERIFY with trace_route -> only then buy a vehicle

`find_station_spot`'s `reachable_directions` answers "is some entry tile usable", not "does the
route I intend to build arrive at a usable end". Those are different questions and I conflated
them.

**Always verify with `trace_route` after connecting.** `connect_rail` returning `partial` is
informative, but a `success` is not proof a train can run: `trace_route` walks the game's own
connectivity and is the authority. `check_connection` answers a different question again, whether
a NEW line could be built, and reports no path once a line stands.

---

## 5. What the five networks need

### Shared, all five

- **Survey agent.** Two-phase: bulk list, then per-entity detail, then cache. Must know that the
  bulk queries are thin.
- **Pair ranker.** Producers with `transported: 0` and non-zero `last_month`, matched to
  acceptors of the same cargo, ranked by distance and acceptance. Unserved producers are the
  whole opportunity; this map had 25 raw producers and 170 viable pairs.
- **Feasibility gate.** `check_connection` before spending. It is read-only, needs no game ticks,
  works while paused, and cost 2.4 seconds to save a failed 6,435 build.
- **Verifier.** `trace_route` after every connect. Treat an unverified route as not built.
- **Budget agent.** Interest runs from day one against a drawn loan. Cash sitting idle is a loss.

### Rail network

Everything in section 4. The orientation-before-siting rule is the design. Add a repair
sub-agent: given a partial line and the `first at (x,y)` coordinate the error carries, decide
between bridging the gap, re-siting a station, or abandoning and removing track. Note that
abandoning is a real option, because a partial line blocks the corridor.

### Road network

Played, and it earned nothing. The prediction that road would be forgiving was HALF right and
the wrong half mattered.

What went right, and it is a real advantage: `check_connection` reported 25 tiles of which only
**6 needed building**, because towns arrive with roads. Two stops plus a depot plus the road cost
about 16,000 of the opening 100,000, and every build returned `success`.

What went wrong: after 60 game days the bus had carried nothing. `q0_income` 0, expenses -522,
vehicle profit -188, both stations `rated: False` with 17 and 7 passengers waiting. The cause,
found with `trace_route` from the stop tile: **`tiles_reachable: 1`**. The stop was connected to
nothing. The bus sat at the depot tile burning running costs.

So the lesson generalises past rail, and it is the single most important one for every network:

**A `success` from a build action is not a route. `connect_road` and `build_road_stop` both
succeeded while leaving a stop the vehicle could not reach.** Verify with `trace_route` and
require `tiles_reachable` greater than 1 before buying a vehicle, in EVERY mode. Rail failed
visibly, with a partial and a discontinuity message; road failed silently, which is worse.

Still unresolved on this route: why the stop is isolated when `find_bus_stop_spots` reported
`adjacent_road_count: 1` at (179,223) and `connect_road` then reported success along that tile.
Candidates are the bay's facing, the depot at (180,222) taking the access tile, or the connect
having routed elsewhere. Worth resolving before the road network is designed, because it decides
whether the tool must place the stop before or after the road.

### Air network

Untested. `find_airport_spots` takes a `town_id` and an `airport_type`. Aircraft need no route
construction at all, which removes the entire class of failure above, at the cost of expensive
vehicles and airports.

### Water network

Untested. Docks plus buoys, no track. `build_canal` and `build_lock` exist. Earlier work noted a
circular water filter bug in the planner, since fixed.

### Combined network

A portfolio allocator over the four, with a shared budget agent. Sequence by capital efficiency:
whichever mode reaches revenue soonest funds the next. On the evidence so far that ordering is
road, then air or water, then rail last, which is the opposite of what a human OpenTTD player
would assume.

---

## 6. Coded tools, memory, middleware, skills

**coded_tools** (deterministic, no LLM, this is where the traps go to die)

- `survey_world` — towns, industries, per-industry detail, cached
- `rank_cargo_pairs` — unserved producers to acceptors, by distance and acceptance
- `plan_route` — `check_connection`, returning tiles, bridges, tunnels and the approach heading
  at each end
- `choose_station_site` — takes the approach heading, returns a spot whose `valid_directions`
  contains it. This is the tool that would have saved the whole rail session
- `build_station`, `connect_and_verify` — connect then `trace_route`, returning a verified bool
  rather than the raw action status
- `read_occupancy` — `get_map_terrain` with `occupancy: true`, correct tuple index, x offset
  handled, returning a grid an agent can reason over
- `buy_and_dispatch` — engine choice, wagon attach, orders, start
- `company_finances` — profit as `q0_income + q0_expenses`, never subtracted

**memory**

- Per-session: the world survey, which pairs are taken, which routes are verified, which
  corridors are spoiled by failed track
- Across sessions: which cargo pairs and which modes paid, keyed by map size and terrain. This is
  the asset that makes the fifth network better than the four

**middleware**

- Manifest-driven action validation before submit, so a wrong parameter name never reaches the
  game
- Envelope wrapping, so no agent can put params at the top level
- Verbatim error surfacing. nttd's refusals are unusually good, "1 of 5 have no through
  connection, first at (175,231)", and summarising them loses the coordinate that fixes the bug
- Idempotency and spend tracking per step

**skills**

- Rail geometry: platform axis, both ends are entries, curves need a joining piece
- Cargo economics: payment decays with delivery time, so short dense routes beat long ones
- Towns are automatically mail and passenger routes; a station near a town earns without any
  industry pairing
- Reading a partial build and deciding repair versus abandon

---

## 7. Sessions still to play

Nine. Seed 581017999 for the eight single-mode runs, 1847172264 for the two combined. Both
declared rather than random, so the runs are reproducible and can reach a `verified` verdict on
the leaderboard: an absent seed still scores, because the profile constrains size, terrain and
towns rather than the seed, but nothing can regenerate the world, so verification would cap at
`replayed`.

Recommended order, reversing the original plan on the evidence: **road first**, because it avoids
both failure modes that stopped rail and should reach revenue fastest, giving a working template
for the rest. Rail last.

---

## Bugs found while playing

1. **Stepped runs lost game days before the first step.** Fixed, PR #93. 149 of 182 days on the
   first attempt.
2. **`get_industries` omits `produces_cargo`,** so industry pairing costs one round trip per
   industry. Not filed yet; worth filing, since every agent that plans cargo hits it.
3. **An unknown action name on the query endpoint returns 403 "not a read-only query"** rather
   than "unknown action", which sends the reader looking for a permission problem. Not filed yet.
