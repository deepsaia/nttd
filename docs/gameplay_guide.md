# Playing nttd well

What the score actually measures, and what it takes to earn it.

Everything here is either read out of OpenTTD's own source or measured in recorded play. Where
a number comes from the game it is linked to the line that computes it, in the 15.3 sources this
build plays. Nothing in this guide is inferred from how the game feels.

---

## 1. The score is not "how big is your company"

The leaderboard ranks `performance_rating`, which is OpenTTD's own number, computed in
[`UpdateCompanyRatingAndValue`](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/economy.cpp#L202).
It is nine components, each capped, each worth a fixed slice of 1000:

| component | what it counts | full marks at | points |
|---|---|---:|---:|
| `SCORE_DELIVERED` | cargo units delivered, **last 4 quarters** | 40,000 | **400** |
| `SCORE_VEHICLES` | vehicles whose **last year's** profit was positive | 120 | 100 |
| `SCORE_STATIONS` | station facilities served in the last 20 units of time | 80 | 100 |
| `SCORE_MIN_PROFIT` | the **worst** vehicle's last-year profit, over 256 | 10,000 | 100 |
| `SCORE_MAX_INCOME` | best quarter's income plus expenses | 100,000 | 100 |
| `SCORE_MIN_INCOME` | **worst** quarter's income plus expenses, last 12 | 50,000 | 50 |
| `SCORE_CARGO` | distinct cargo types delivered last quarter | 8 | 50 |
| `SCORE_MONEY` | bank balance | 10,000,000 | 50 |
| `SCORE_LOAN` | `250,000 - current_loan` | loan of 0 | 50 |

The weights are the
[`_score_info` table](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/economy.cpp#L91); each part
is clamped to its cap and scaled, so exceeding a cap earns nothing extra.

**Cargo delivered is 40% of the entire score.** Nothing else comes close. A run that moves
freight badly cannot be rescued by being rich: money is worth 50 points and needs ten million to
collect them.

### Three components a one-year run cannot win

The benchmark's T1 tier is 366 days. That makes three components partly or wholly unreachable,
which is worth knowing before optimising for them:

- **`SCORE_MIN_PROFIT` (100 points) is always 0.** It only considers vehicles older than
  [`VEHICLE_PROFIT_MIN_AGE`, which is two years](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/vehicle_func.h#L37).
  In a one-year run no vehicle qualifies.
- **`SCORE_MIN_INCOME` (50 points) needs every quarter profitable.** It takes the worst of the
  last twelve quarters, and a company that spends its first quarter building has a negative one.
- **`SCORE_LOAN` (50 points) is 0 if you borrow more than 250,000.** The part is
  `250,000 - current_loan`, clamped at zero. Borrowing the full 300,000 ceiling forfeits all 50,
  so a run that borrows to the limit should be sure the money buys something that earns.

So a realistic ceiling for a single year is around 800, and hand-played runs on random seeds land
well under a quarter of that. Treat the rating as a scale you are near the bottom of, not one you
are near the top of.

### Company value is a different question

`company_value` is
[assets minus loan plus cash](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/economy.cpp#L150),
where assets are station facilities plus vehicles at
[one and a half times their current value](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/economy.cpp#L115),
and the result is floored at 1.

That floor explains a result that looks like a bug. A company that borrows 300,000, spends it on
track and never earns has assets worth less than its loan, so the subtraction goes negative and
the game clamps it. A company value of exactly **1** is not a rounding error, it is a company
that owes more than it owns.

It also means **drawing a loan does not raise company value**, because the loan is subtracted
again. Borrowing is a way to buy earning assets sooner, not a way to look bigger.

---

## 2. Where the points come from

Aircraft need no infrastructure between their endpoints, so the only decisions that matter are
ones the game answers well: which town, which airport type, and whether the site is inside its
own catchment. Rail and water both depend on a junction between a depot and a line, and that
junction is the thing hardest to confirm before committing money to it. Road sits in between:
the corridor mostly exists already, but the joins do not.

That difference, not the vehicles, is what separates a strong run from an empty one. Measured
across a set of one-year runs on random seeds, air and mixed air-and-road networks scored several
times what rail and water managed, and the rail attempts that failed did not fail by a little:
they delivered nothing at all.

![A finished run, as the monitor shows it](images/monitor.png)

*A one-year air run at the end of its year: rating and company value climbing in steps as each
aircraft enters service, cargo waiting at stations oscillating as planes clear it, and a fleet of
nine against four stations. The flat "infrastructure pieces" line is the point of the mode: an
air network builds nothing between its endpoints.*

---

## 3. A playbook that survived contact

### Air, the mode that wins

1. **Rank towns by population and check the airport fits inside its own catchment.** A commuter
   airport covers 4 tiles. An airport sited 16 to 28 tiles from the town centre earns almost
   nothing: re-siting the airports alone has taken a quarter's income from 25 to 131,740.
2. **Match the plane to the airport.** Large aircraft crash at small airports. Where the good
   towns only take commuter fields, fly small planes; where they take large or international
   fields, big planes carry four times the load on the same leg.
3. **Both endpoints must be real towns.** A long leg into a 348-person village returns big planes
   almost empty, and costs the same to fly as a leg into a city. Airport capability is not a
   reason to pick a destination; population is.
4. **Long legs pay.** On one map a single big plane on a 205-tile leg earned 74,986 while small
   planes shuttling 35-tile hops earned around 13,000 each.

### Road, the mode that pays first

Towns already have roads, so most of a corridor exists: one measured route needed 6 tiles built
out of 25. That makes buses the fastest way to a positive balance early. **One pair saturates**:
past three or four buses a route has nothing left to carry, so growth is more town pairs, not
more buses.

### Water, where the map decides

Docks sited by town are frequently on **unconnected water**. On two maps in a row, no pair of
docks built for the largest towns shared a body of water at all, and ships sat circling the pool
their depot was in. Before buying ships, confirm a vessel can actually reach the far dock; the
cheapest reliable test is to run one and watch whether it moves.

### Rail, the hardest mode by a distance

Rail fails in several distinct ways, and the failure always looks like success: track built,
connectivity checks passed, trains bought, nothing delivered.

- A depot built beside a platform joins that station's **stub** of track, not the main line.
  Measured at three towns, every such depot reached 5 to 8 tiles of a 71-tile line. Put the depot
  against the middle of the corridor instead.
- A corridor that crosses water fails as `ERR_TUNNEL_CANNOT_BUILD_ON_WATER`: the connection
  reaches for a tunnel where the crossing needs a bridge, and the bridge heads must be at equal
  height. This defeated five of six routes on one map.
- Rail station catchment is small. A 3-tile platform beside a town of 2,468 reported a supply of
  **12 passengers**, against the hundreds an airport in the same town collects.

---

## 4. Traps that cost whole runs

Each of these produced a fleet that existed, had correct orders, and delivered nothing.

| symptom | cause | how to see it |
|---|---|---|
| Every vehicle parked beside its depot | `start_vehicle` was called twice and the second call stopped it | the fleet table shows every row "not moving" |
| A vehicle in the far corner of the map | it is lost, and says so | `lost` on the vehicle |
| Stations full, nothing delivered | the depot cannot reach the line | trace from the depot, not between platforms |
| Cargo total reads 0 at the end of a run | the game's quarterly counter resets on 1 January, the day a 366-day run ends | score against the banked total, never the quarter |
| Company value of exactly 1 | assets minus loan went negative | it is the floor, not a bug |

The monitor's **fleet table** answers the first three directly: it lists every vehicle worst
earner first with a plain-language problem column, so a single silent failure among thirty
vehicles is the first row rather than something to hunt for. The **actions by type** table answers
a different question the totals hide: whether one call is failing repeatedly. On a failed rail
network it reads `connect_rail: 22 submitted, 16 refused`, which is the whole diagnosis in one
line.

---

## 5. Where to look next

- `docs/agent_guide.md` for the action surface an agent drives.
- `docs/cli_guide.md` for running, analysing and submitting a session.
- `docs/actions/` for every action, its parameters and what it returns.
- `nttd analyze -s <session>` for the full post-run reports, including per-vehicle detail,
  unserved cargo routes and the world state.
