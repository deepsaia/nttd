# Agent network design, from playing nttd by hand

Working notes for the five neuro-san networks: one per transport mode, plus a combined one.

**Status.** Three sessions played to completion or near it, on three different worlds. Road now
earns reliably; rail builds, verifies and loads but stalls; air and water are untested. Seven
sessions remain. Every finding below was hit rather than read.

    road, rule-based baseline   seed 19566827   score 58   value 28,326   41 actions
    road, hand-played           seed 19566827   score 52   value 60,377  115 actions
    rail, hand-played           seed 1780227570 line verified, train loaded, then stalled

Four nttd bugs were found and three are fixed. See "Bugs found while playing".

## 0. The result that changed the strategy

Hand-playing road MORE THAN DOUBLED company value, 28,326 to 60,377, and the score went DOWN,
58 to 52. That is worth stating plainly because it inverts the obvious plan.

Why, from the rating's own weights: 40 percent is ANNUAL CARGO DELIVERED, and buses on 20 to 37
tile routes deliver slowly however many you buy. Drawing the full loan forfeits the 5 percent
"no loan" component outright. Thirty vehicles dilute the 10 percent "profitable vehicles" share
while the newest are still paying themselves off.

**So the objective for every network is cargo UNITS DELIVERED, not fleet size and not company
value.** That favours short dense routes, high capacity per vehicle, and cargo that regenerates
fast. It is why rail on a 12 tile oil run is a better shape than road on a 37 tile passenger run,
even though road is far easier to build.

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
| `order_flags: 64` | `OF_FULL_LOAD` means full load of **every** cargo the consist can carry. A train that can hold two cargo types at a station producing one waits forever | Use `96` (`OF_FULL_LOAD_ANY`) or `0`. Only use 64 when the consist carries exactly one cargo |
| `build_train` refits the engine | A refit skips any vehicle that cannot take the cargo, so a mismatched `cargo_id` silently leaves a **mixed consist** | `build_train` now returns `capacity_by_cargo` and `carries_one_cargo`. Assert `carries_one_cargo` before ordering with a full-load flag |

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
informative, but a `success` is not proof a train can run. `check_connection` answers a different
question again, whether a NEW line could be built, and reports no path once a line stands.

**But `trace_route` is necessary, not sufficient, for rail.** I wrote in an earlier pass that it
"is the authority". A live session disproved that. Station to station, `trace_route` returned
`line_exists: true` over 16 reachable tiles, and the train still left its platform, ran three
tiles, and stopped dead: `state: 0` (running), `current_speed: 0`, unmoved across twelve stepped
days, profit sliding from -176 to -222 on running costs alone. Tracing from the tile the train
actually stood on returned `line_exists: false, tiles_reachable: 1`.

So the two walkers disagree, and OpenTTD's train pathfinder is the one that decides whether the
company earns. The operational rule that follows:

    verify with trace_route BEFORE buying, then verify the train MOVED after starting it.
    A vehicle whose position is unchanged across several steps is a failed route, not a slow one.

That second check is cheap, it is a read, and no amount of build-time verification replaces it.
Every network needs it as a standing watch, not a one-off assertion.

---

## 4b. The rail session, played move by move

Seed 677471231, T1 stepped, 256x256 flat. Three routes built and running by day ~180. Every
number here was measured in that session.

**Choose the route on revenue, not distance.** The five candidate pairs, priced with
`get_cargo_income` at their own distance against the source's `last_month` production:

| pair | dist | production | income/unit | revenue/month |
| --- | --- | --- | --- | --- |
| Forest -> Sawmill | 40 | 128 | 24 | **3,072** |
| Farm -> Factory (GRAI) | 27 | 80 | 15 | 1,200 |
| Farm -> Factory (LVST) | 27 | 72 | 13 | 936 |
| Forest -> Sawmill | 24 | 64 | 14 | 896 |
| Farm -> Factory (GRAI) | 24 | 56 | 13 | 728 |

The shortest pair was worth a quarter of the longest. Income per unit rises with distance, so
the road builder's rule that short beats long is a ROAD rule and inverts for rail. Picking the
nearest pair, which is what the mode builder used to do, throws away most of the map's value.

**Every steel mill showed production 0.** Processing industries produce nothing until something
feeds them, so a pair ranker that reads only "produces this cargo" will confidently choose a
route with no cargo on it. Filter on `last_month > 0`.

**Only one locomotive exists at rail type 0 in 2020,** the 'Dash' diesel, and it carries 80
passengers of its own. So the mixed consist that deadlocked the earlier session is not an
unlucky choice, it is the DEFAULT: any wood or grain train built with this engine has a
passenger hold unless the whole consist is refitted. Passing `cargo_id` to `build_train` refits
the engine too, and `carries_one_cargo: true` in the reply proves it at build time. Capacity
came out 140: 20 in the refitted engine plus 4 wagons at 30.

**A rail depot needs a junction piece, and the finder will not give you one.** Three depots,
same recipe each time:

    find flat ground (slope 0) beside the line -> build_rail_depot facing it
      -> build_rail_track on the NEIGHBOUR with the curve that touches the depot's edge
      -> the build reply's own `connected` flag tells you whether it worked

`connect_rail` cannot do this job: it lays rail on both endpoints, so aimed at a depot tile it
returns ERR_AREA_NOT_CLEAR against the depot it is trying to reach. The direction bits matter,
and the mapping is worth writing down once: **x+ is SW, x- is NE, y+ is SE, y- is NW**. A depot
on the far side of a tile in the x+ direction needs that tile to carry `RAILTRACK_NW_SW` (16)
or `RAILTRACK_SW_SE` (8). Building one of the pair usually reports the other ALREADY_BUILT,
which is fine.

**`find_rail_depot_spot` searches a radius and does not care which line it finds.** Asked for a
depot near the grain station at (145,116) with radius 8, it returned ground beside the WOOD
line at (144,125). The depot built, reported `connected: true`, the train built and started, and
then sat still forever: it was on the wrong network and had no path to its own stations. It cost
21,000 and could not even be sold, because selling requires the vehicle to be in a depot and it
could not reach one. `send_to_depot` answered ERR_UNKNOWN. **Verify the depot reaches the
route's own two stations before buying anything to put in it.**

**Full load is a throughput decision, and it goes both ways.** Measured on the same day:

- Wood route, production 128/month against capacity 140. Partial loads carried 44 per trip and
  delivered 88 in 50 days, with 66 units piling up at the station. Switching order 0 to
  `OF_FULL_LOAD_ANY` (96) made every trip carry a full 140. Train profit went 1,987 -> 11,725.
- Grain route, production 56/month against the same capacity 140. The same flag starved it: the
  train sat at the farm absorbing grain as it appeared, waiting for a full load it would need
  two and a half months to reach, and showed profit **-231**. Dropping to flags 0 turned it to
  **+1,132** within 25 days.

So the rule is not "use full load". It is: **full load pays when the source fills the train
within one round trip, and starves the route when it cannot.** Compare `last_month` production
against consist capacity and the cycle time before choosing.

**Single track caps a route at one train.** Unsignalled track has no protection, so scaling rail
is more ROUTES, not more vehicles on a route. That inverts the road lesson again, where cloning
a proven bus onto a proven route is the cheapest possible growth.

**Water breaks corridors, and `connect_rail` will not use a bridge you built for it.** The first
grain pair failed on ERR_TUNNEL_CANNOT_BUILD_ON_WATER at (186,194). `build_bridge` spanned the
three water tiles successfully, and the next `connect_rail` re-planned from scratch, ignored the
bridge, and hit water two tiles away at (188,195). Connecting each leg to a bridge end instead
failed the other way, because a bridge ramp is not clear ground. Abandoning that pair for an
inland one cost less than fighting it, and that is the general lesson: a corridor that needs
water works is worth a lot less than its revenue table suggests.

**Drawing the loan destroys reported company value.** Value is assets minus debt, so taking
300,000 to fund routes took value to **1** while the rating climbed. Both are scored, and the
rating charges 5 percent for carrying a loan. The plan that follows is to borrow early, spend
it on cargo capacity, and repay what cash allows before the run ends.

---

## 4c. The second rail session: ranking routes properly, and four ways a depot fails

Seed 1716811708. The route ranker from session 4b was wrong, and fixing it changed everything.

**Revenue per month is the wrong ranking.** Priced naively, this map's best pairs were 189, 272
and 225 tiles long at 135 to 176 per unit, showing 18,000 to 20,000 a month. All fantasy: at a
measured **3.3 tiles per game day**, a 189 tile route is a 114 day round trip, so it completes
three trips a year and delivers 420 units. Ranking by what can actually be carried:

    cycle_days   = 2 * distance / 3.3 + 6      (6 days of loading and unloading, measured)
    trips_a_year = 366 / cycle_days
    deliverable  = min(production_a_month * 12, consist_capacity * trips_a_year)

That reordered the board completely. The top pair became a 31 tile wood run at 1,824 units a
year, and the best long candidate fell to 420. **Distance raises income per unit and lowers
throughput, and throughput wins**, because cargo delivered is 40 percent of the rating and the
leaderboard tiebreak is cargo. The naive ranking would have bought a 272 tile oil route.

**A station platform sets the RAIL bit.** Flags 40 is rail|station. Treating "bit 8 is set" as
"this is running line" put a depot against a platform, where no track piece can ever be added:
every curve answered ERR_AREA_NOT_CLEAR, the depot never joined, and the train sat in it. Test
`flags & 8 and not flags & 32`.

**Speed is not movement.** The train in that unjoined depot reported `current_speed` cycling
0, 39, 21, 0, 36 across eight days while `x,y` never left (95,188). It was rocking inside the
depot. A movement check that samples speed passes this; one that samples POSITION catches it.
That is the check worth wiring into every network.

**Ground beside a line is not necessarily buildable.** Tree tiles report flags 0, and
`build_rail_depot` answers "this tile is not buildable, so it must be cleared or levelled
first". They are still usable, at the cost of a `demolish_tile` first, so they belong in a
fallback tier rather than being filtered out: requiring the BUILDABLE bit reported "nowhere
flat beside a line within 20 tiles" while the line had level ground on both sides.

**Do not re-issue a build to re-read its status.** `build_rail_depot` returns a `connected`
flag, but issuing it a second time answers ERR_ALREADY_BUILT with no flag, so a helper that
re-built to confirm never saw success and walked on to build a second, third and fourth depot.

**Failed actions cost what successful ones cost.** 15 of this session's first 38 actions failed,
14 of them one helper firing both candidate curve pieces at six candidate spots. A helper must
read the state and commit, not spray attempts: the action budget is scored, and a run that
spends 40 percent of it on predictable refusals has thrown that much away.

**Two stations on one industry: the older one takes everything.** The clearest single finding of
the session, and the reason the wood route earned nothing for 120 days. A first, abandoned
attempt had built a station at (94,189); the retry built another at (93,190), one tile away, and
the train served the second. At day 738019:

    station 0 (94,189)  WOOD waiting 422, rating 27     <- nobody served it
    station 2 (93,190)  nothing waiting                 <- the train's actual stop

An industry delivers to ONE station, and it is not necessarily the newest or nearest. The train
ran its route correctly, at speed, on a verified line, with a correct consist and a sensible load
flag, and carried nothing, because the cargo was accumulating four tiles away. Re-pointing the
orders at station 0 fixed it.

Two consequences for the networks. First, a failed build attempt must be CLEANED UP, not
abandoned in place: leftover stations poach the cargo of the route that replaces them. Second,
the health check every network needs is not "is the vehicle moving" but **"is the station my
vehicle serves accumulating cargo"**. Three distinct failure modes now, each invisible to the
one before it:

    line verified        -> says nothing about whether a vehicle can path it
    vehicle moved        -> says nothing about whether it is carrying anything
    station accumulating -> says nothing about whether MY vehicle is the one collecting

Final shape: three routes running (wood 31t, oil 50t, iron ore 33t), one abandoned when its
train failed the movement check. Only the oil route earned from the start, at 7,663 by day 120;
the other two were each losing money for a diagnosable reason rather than a mysterious one.
Abandoning the dead route cost one train; not checking would have cost the train AND the rest
of the run's attention.

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

## 6b. What the second and third sessions added

**Roads work end to end now.** Three routes verified out of five attempted on one map, so expect
around 50 percent attrition on road corridors and plan surplus candidates. The two that failed
cost nothing but a plan and a build_path, because the verify gate ran before any vehicle spend.

**The map dictates the strategy, so no distance rule survives contact.** Seed 19566827 had NO
town pair closer than 20 tiles, so "prefer 6 to 14 tiles" selected nothing and had to widen on
the spot. A pair ranker must adapt its band to the world rather than carry a constant.

**Idle cash is a real cost.** Borrowing the full 300,000 early left 150,000 sitting for about a
hundred game days paying interest against nothing. Borrow late, deploy immediately, and only
against a route already carrying.

**Rail siting by approach works.** Deriving the axis from the planned corridor and then asking
for a spot whose valid_directions contains it produced a line that verified FIRST TRY, where
siting by distance had failed three separate ways. Of 14 spots offered at each end, 8 and 7
respectively faced the needed axis, so the constraint is cheap to satisfy once it is asked for.

**Rolling stock is gated by rail type, and the default is wrong.** In 2020 the engine list is
dominated by maglev and monorail: of 40 train engines, only 12 are rail_type 0, which is what
connect_rail builds by default. The only conventional loco is the Dash at 120 km/h. An agent that
picks the fastest engine gets a maglev that cannot run on the track it just built. Either choose
the engine first and build that rail type, or filter engines by the rail type actually laid.

**build_train exists and is the right tool.** Buying a loco and then wagons separately half
worked: the loco and one wagon appeared, three more wagons failed, and nothing was attached.
build_train takes engine_id, wagon_id, num_wagons and cargo_id and assembles the whole thing.

**Unresolved, and the next thing to fix.** The oil train loaded 150 units and then stopped dead
two tiles past its own station at speed 0, profit negative. So loading works and the line
verified, but the train will not run the route. Suspects, in order: the order flag I passed as 64
for full load may be holding it, the train may have left by the far platform end and be unable to
turn, or a train needs a signal or a second platform to reverse. Resolve this before the rail
network is designed, because it is the last thing between rail and revenue.

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
4. **Cargo delivered was read off a counter that resets every quarter.** Fixed. The game reports
   the quarter IN PROGRESS, so the series sawtooths, and the growth checkpoints at 25/50/75
   percent of a 366 day run land on the resets. A run that carried 3,526 units reported 0.
5. **Every business metric in every result ever written was zero.** Fixed, and the worse of the
   two. The result was scored BEFORE the recorder merged its fragments into `snapshots.parquet`,
   so the metrics read a file that did not exist yet and silently returned an empty record.
   Recomputing one finished session from disk afterwards gave 30 vehicles, 6 stations, 37,909
   value at the halfway mark, against 0 for all of them in the file. Nothing raised.
6. **`trace_route` and OpenTTD's own train pathfinder disagree.** Not filed yet, and the most
   consequential of the open ones: it means a route can pass every build-time check nttd offers
   and still never move a train. See section 4.
