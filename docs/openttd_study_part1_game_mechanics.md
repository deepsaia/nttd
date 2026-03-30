# OpenTTD Comprehensive Study - Part 1: Game Mechanics

> This is Part 1 of 3. See also:
> - [Part 2: GameScript API Reference](./openttd_study_part2_gs_api_reference.md)
> - [Part 3: nttd Implementation Analysis & API Design](./openttd_study_part3_nttd_analysis.md)

---

## 1. Game Overview

OpenTTD is a transport simulation where players build and manage transport networks (road, rail, water, air) to move cargo between industries and towns for profit. The game runs on a tile-based map with real-time simulation ticks.

### 1.1 Map & Tiles

- **Map sizes**: 64x64 to 4096x4096 tiles
- **Tile**: Basic map unit with terrain type, slope (16 slope values), height (0-15 per corner), owner, and infrastructure
- **Tile index**: Linear index `tile = y * map_size_x + x`; convert with `GSMap.GetTileIndex(x, y)` and `GSMap.GetTileX/Y(tile)`
- **Edge tiles**: First and last row/column are unbuildable (effective buildable area is `(size-2) x (size-2)`)

### 1.2 Time System

- **Tick**: Smallest time unit; 74 ticks = 1 day
- **Day**: 74 ticks
- **Month**: ~30 days (varies)
- **Year**: 365 or 366 days
- **Economy month**: Production/finance cycles
- **Start year**: Typically 1950 (configurable)
- **GS API**: `GSDate.GetCurrentDate()` returns days since epoch; `GSDate.GetYear/Month/DayOfMonth(date)` for components

### 1.3 Four Climates

| Cargo Type     | Temperate | Sub-Arctic | Sub-Tropical | Toyland |
| -------------- | --------- | ---------- | ------------ | ------- |
| **Mail**       | ✓         | ✓          | ✓            | ✓       |
| **Passengers** | ✓         | ✓          | ✓            | ✓       |
| Batteries      | -         | -          | -            | ✓       |
| Bubbles        | -         | -          | -            | ✓       |
| Candyfloss     | -         | -          | -            | ✓       |
| Coal           | ✓         | ✓          | -            | -       |
| Cola           | -         | -          | -            | ✓       |
| Copper Ore     | -         | -          | ✓            | -       |
| Diamonds       | -         | -          | ✓            | -       |
| Fizzy Drinks   | -         | -          | -            | ✓       |
| Food           | -         | ✓          | ✓            | -       |
| Fruit          | -         | -          | ✓            | -       |
| Gold           | -         | ✓          | -            | -       |
| Goods          | ✓         | ✓          | ✓            | -       |
| Grain          | ✓         | -          | -            | -       |
| Iron Ore       | ✓         | -          | -            | -       |
| Livestock      | ✓         | ✓          | -            | -       |
| Maize          | -         | -          | ✓            | -       |
| Oil            | ✓         | ✓          | ✓            | -       |
| Paper          | -         | ✓          | -            | -       |
| Plastic        | -         | -          | -            | ✓       |
| Rubber         | -         | -          | ✓            | -       |
| Steel          | ✓         | -          | -            | -       |
| Sugar          | -         | -          | -            | ✓       |
| Sweets         | -         | -          | -            | ✓       |
| Toffee         | -         | -          | -            | ✓       |
| Toys           | -         | -          | -            | ✓       |
| Valuables      | ✓         | -          | -            | -       |
| Water          | -         | -          | ✓            | -       |
| Wheat          | -         | ✓          | -            | -       |
| Wood           | ✓         | ✓          | ✓            | -       |

#### Special Requirements
- Temperate: None
- Sub-Arctic: Towns above snow line need food
- Sub-Tropical: Desert towns need food + water
- Toyland: None

---

## 2. Four Transport Types

### 2.1 Road Transport

| Component | Details |
|-----------|---------|
| **Infrastructure** | Roads, tram tracks (separate type), one-way roads |
| **Vehicles** | Buses (passengers), trucks (freight), trams |
| **Stations** | Bus stops (passengers), loading bays (freight), drive-through stops (both) |
| **Depots** | Road depots (must face a road tile) |
| **Speed** | 37 km-ish/h daily acceleration; **half speed on corners** |
| **Capacity** | Low per vehicle; good for short distances and town networks |
| **Cost** | Cheapest to build; lowest revenue per unit |

**Key mechanics**:
- Road vehicles follow roads automatically (no manual pathfinding needed)
- Drive-through stops allow vehicles to pass without turning around
- One-way roads can restrict traffic flow
- Road vehicles slow to half speed on every corner tile

### 2.2 Rail Transport

| Component | Details |
|-----------|---------|
| **Infrastructure** | Tracks (6+ rail types), signals, junctions, level crossings |
| **Vehicles** | Trains = locomotive(s) + wagon(s); articulated vehicles |
| **Stations** | Rail stations (N platforms x M tile length); waypoints |
| **Depots** | Rail depots (entrance faces track) |
| **Speed** | Power-dependent; realistic acceleration model |
| **Capacity** | Highest per train; best for long-distance bulk |
| **Cost** | Moderate to expensive; highest revenue potential |

**Rail types** (era-dependent):
- Railroad (early), Electrified (mid), Monorail (late), Maglev (latest)
- Each has different max speeds, costs, and available engines
- Can convert existing tracks between types

**Key mechanics**:
- Trains are composed: buy locomotive, then add wagons of specific cargo types
- Platform length matters: train must fit or loading is slower
- Signals control traffic flow and prevent collisions (see Section 8)
- Curve speed limits: sharper curves = slower speeds

### 2.3 Water Transport

| Component | Details |
|-----------|---------|
| **Infrastructure** | Canals, locks (height transitions), buoys (waypoints) |
| **Vehicles** | Ships (various cargo types) |
| **Stations** | Docks (built on coast tiles) |
| **Depots** | Ship depots (on water) |
| **Speed** | 37 km-ish/h daily acceleration; slowest transport type |
| **Capacity** | Very high per ship |
| **Cost** | Low running costs; canals expensive to build |

**Key mechanics**:
- Ships navigate water tiles automatically
- Buoys serve as waypoints for long ocean routes
- Locks allow ships to traverse height differences (3 tiles: entry + lock + exit)
- Canals create artificial waterways through land

### 2.4 Air Transport

| Component | Details |
|-----------|---------|
| **Infrastructure** | Airports are self-contained (runways, taxiways, terminals, hangars) |
| **Vehicles** | Planes (small/large/helicopter) |
| **Stations** | Airports (12+ types of varying size and capacity) |
| **Depots** | Hangars (built into airports) |
| **Speed** | Fastest; fly at 1/4 listed speed (configurable) |
| **Capacity** | Moderate; best for very long distances |
| **Cost** | Airports expensive; aircraft expensive; highest per-unit revenue for long routes |

**Airport types**:

| Type | Size | Helipads | Noise | Era |
|------|------|----------|-------|-----|
| Small | 3x4 | 0 | Low | Early |
| Commuter | 4x5 | 0 | Low | Mid |
| City | 6x6 | 0 | Medium | Mid |
| Metropolitan | 6x6 | 0 | High | Mid-Late |
| International | 7x7 | 1 | High | Late |
| Intercontinental | 9x11 | 2 | Very High | Latest |
| Heliport | 1x1 | 1 | Low | Mid |
| Helidepot | 2x2 | 1 | Low | Mid |
| Helistation | 2x4 | 3 | Low | Late |

**Key mechanics**:
- Airport noise affects nearby towns; towns can refuse airports if noise limit exceeded
- Small airports only accept small planes
- Aircraft crash risk on small airports (higher for large planes)
- Broken-down planes fly at 320 km-ish/h; taxi at 150 km-ish/h

---

## 3. Economy & Cargo Payment

### 3.1 Payment Formula

Revenue for a cargo delivery:

```
Payment = cargo_units * cargo_base_value * f(distance) * f(time)
```

Where:
- **cargo_units**: Number of units delivered
- **cargo_base_value**: Per-cargo constant (see table below)
- **f(distance)**: Manhattan distance `|dx| + |dy|` between source and destination station **name tiles** (the tile that defines the station's position)
- **f(time)**: Time penalty factor based on days in transit

### 3.2 Time Penalty

Each cargo type has two thresholds:
- **Early delivery days**: No penalty if delivered within this
- **Late delivery days**: Increased penalty after this

Penalty calculation:
1. If `days_in_transit <= early_days`: No penalty
2. If `early_days < days <= late_days`: **0.4% penalty per day** past early threshold
3. If `days > late_days`: Additional **0.4% per day** past late threshold
4. **Maximum penalty**: 88%
5. Beyond max: Formula becomes `31 / (excess_days + 32)`

### 3.3 Cargo Values (Temperate)

| Cargo | Base Value (per 100 units/tile) | Early Days | Late Days |
|-------|--------------------------------|------------|-----------|
| Passengers | 39 | 0 | 24 |
| Mail | 55 | 20 | 90 |
| Coal | 50 | 7 | 255 |
| Oil | 54 | 25 | 255 |
| Livestock | 47 | 4 | 18 |
| Goods | 62 | 5 | 28 |
| Grain | 40 | 4 | 40 |
| Wood | 61 | 15 | 255 |
| Iron Ore | 42 | 9 | 255 |
| Steel | 54 | 7 | 255 |
| Valuables | 91 | 1 | 32 |

**GS API**: `GSCargo.GetCargoIncome(cargo_type, distance, days_in_transit)` calculates exact payment.

### 3.4 Key Economic Insights for AI

1. **Longer distances = more revenue** (but also more time)
2. **Fast delivery matters** for passengers, mail, goods, livestock (short early/late thresholds)
3. **Bulk cargo** (coal, ore, wood) has generous time windows - distance matters more than speed
4. **Valuables** have highest base value but very tight time window (1 day early!)
5. **Transfer orders** provide partial payment for multi-hop routes

---

## 4. Station Ratings

Station ratings determine what percentage of nearby industry/town production is delivered to your station. **This is critical for AI agents** - low ratings mean less cargo, less revenue.

### 4.1 Rating Factors (per cargo type, 0-100%)

| Factor | Contribution | Formula/Details |
|--------|-------------|-----------------|
| **Vehicle speed** | 0-17% | `max(0, (Speed - 85) / 4)` for fastest vehicle visiting station |
| **Vehicle age** | 10-33% | Age 0 years: 33%, Age 1: 20%, Age 2: 10%, Age 3+: 10% |
| **Days since last pickup** | 10-51% | <15 days: 51%, 15-30: 25%, 30-60: 10%, 60-105: 10% |
| **Waiting cargo amount** | -35% to 16% | <100: 16%, 100-500: 8%, 500-1000: 0%, 1000-1500: -16%, >1500: -35% |
| **Town statue** | 0 or 10% | 10% bonus if company has statue in town |
| **Advertising** | 0-63% | Small: +25%, Medium: +44%, Large: +63% (temporary) |

### 4.2 Rating Effects

- **Below 50%**: Cargo starts being randomly lost from station
- **Higher ratings**: More industry output is routed to your station (vs competitors)
- **Ratings recalculate**: Every 2.5 days, with max 2-point swings (0.78%)
- **Crash penalty**: -63% to -100% (devastating)
- **Failed bribe**: -100% (complete rating destruction)

### 4.3 AI Strategy for Maintaining Ratings

1. **Use fast vehicles** (>85 km/h) for speed bonus
2. **Replace old vehicles** regularly (age penalty)
3. **Maintain frequent service** (<15 days between pickups = max 51%)
4. **Don't let cargo accumulate** (>1500 units = -35% penalty)
5. **Build statues** in key towns (+10% permanent)
6. **Avoid crashes** at all costs

---

## 5. Town Growth

### 5.1 Growth Mechanics

Towns grow by building new houses on road-adjacent tiles. Growth rate depends on:

1. **Active stations**: 0-4 stations serviced in last 50 days → slow growth; **5+ stations = fastest growth**
2. **Monthly cargo delivery**: More delivery = faster growth
3. **Funding**: "Fund new buildings" town action temporarily increases growth rate
4. **Road layout**: Towns build roads according to their layout type (Original, Better Roads, 2x2, 3x3, Random)

### 5.2 Climate-Specific Requirements

| Climate | Growth Requirement |
|---------|-------------------|
| Temperate | None - grows freely |
| Sub-Arctic | Towns above snow line need **food** delivered monthly |
| Sub-Tropical | Desert towns need **food AND water** delivered monthly |

### 5.3 Passenger/Mail Generation

Every 256 ticks, for each house tile:
- **Passengers**: Random value 0-255; if `random < population_density`, generate `population_density/8 + 1` passengers
- **Mail**: Similar formula with lower base values
- **Recession**: Halves all output (rounded up)

### 5.4 Company HQ Generation

Company HQ produces passengers and mail based on company performance level (1-5):
- **Passengers per tile**: `256 / 4 / (6 - level)` per 256 ticks
- **Mail per tile**: `196 / 4 / (6 - level)` per 256 ticks
- HQ occupies 4 tiles, so multiply by 4

### 5.5 GS-Exclusive Town Controls

| Action | GS Method | Effect |
|--------|-----------|--------|
| Found new town | `GSTown.FoundTown(tile, size, city, layout, name)` | Create town at location |
| Expand town | `GSTown.ExpandTown(town_id, houses)` | Add N houses immediately |
| Set growth rate | `GSTown.SetGrowthRate(town_id, days)` | Override automatic growth |
| Set cargo goal | `GSTown.SetCargoGoal(town_id, effect, goal)` | Custom cargo requirements |
| Change rating | `GSTown.ChangeRating(town_id, company, delta)` | Directly modify authority rating |
| Perform town action | `GSTown.PerformTownAction(town_id, action)` | Advertise, fund buildings, etc. |

---

## 6. Industry Production

### 6.1 Industry Types

Industries are either **raw** (produce cargo from nothing) or **processing** (consume cargo, produce different cargo).

**Temperate industry chains**:
```
Coal Mine ──────────────────────────→ Power Station
Iron Ore Mine → Steel Mill → Factory → Town (accepts goods)
Farm (grain/livestock) ────────────→ Factory
Forest → Sawmill ──────────────────→ (produces goods)
Oil Wells/Rig → Oil Refinery ──────→ (produces goods)
```

### 6.2 Production Frequency

- Production occurs **8-9 times per month** (every 256 ticks)
- Each production cycle outputs the industry's per-cycle amount

### 6.3 Production Changes (Default Economy)

- **One change per 256x256 map area per month** (larger maps = more changes)
- **50% chance** for "only_decrease" industries (Oil Wells) to decline
- Other industries: **16.7% monthly change chance**
- If transported percentage < 60%: 67% chance decrease, 33% increase
- If transported percentage >= 60%: 67% chance increase, 33% decrease
- Change amount: Production doubles or halves

### 6.4 Production Changes (Smooth Economy)

- **4.5% monthly change rate** across all producing industries
- Transport-based:
  - >80% transported: 83% increase, 17% decrease
  - 60-80% transported: 67% increase, 33% decrease
  - <60% transported: 33% increase, 67% decrease
- Change amount: 3-23% per change (gradual)
- **Maximum production**: 2,040-2,295 units per month

### 6.5 Initial Production Ranges

| Industry | Min | Max |
|----------|-----|-----|
| Coal Mine | 56 | 176 |
| Forest | 48 | 152 |
| Oil Wells/Rig | 56 | 176 |
| Iron Ore Mine | 40 | 112 |
| Farm | 40 | 112 |

### 6.6 GS-Exclusive Industry Controls

| Action | GS Method | Effect |
|--------|-----------|--------|
| Set production | `GSIndustry.SetProductionLevel(id, level, show_news, text)` | Override production amount |
| Control flags | `GSIndustry.SetControlFlags(id, flags)` | Prevent closure, freeze production |
| Exclusive supplier | `GSIndustry.SetExclusiveSupplier(id, company)` | Only one company can deliver |
| Exclusive consumer | `GSIndustry.SetExclusiveConsumer(id, company)` | Only one company can pick up |

---

## 7. Company & Authority Ratings

### 7.1 Company Performance Rating (0-1000 points)

This determines the "league" title and is used for end-game scoring.

| Component | Max Points | Threshold for Max | Formula |
|-----------|-----------|-------------------|---------|
| Profitable vehicles (count) | 100 (10%) | 120+ vehicles | `min(vehicles, 120) * 100 / 120` |
| Station coverage (parts) | 100 (10%) | 80+ station parts | `min(parts, 80) * 100 / 80` |
| Vehicle profit (per vehicle) | 100 (10%) | Min profit >10,000 | All 2+ year vehicles earn >10k |
| Quarterly revenue (low) | 50 (5%) | 50,000+ | Linear scale |
| Quarterly revenue (high) | 50 (5%) | 100,000+ | Linear scale |
| Annual cargo delivery | 400 (40%) | 40,000+ units | `min(cargo, 40000) * 400 / 40000` |
| Cargo diversity | 50 (5%) | 8+ cargo types | `min(types, 8) * 50 / 8` |
| Cash reserve | 50 (5%) | 10,000,000+ | Linear scale |
| No loan | 50 (5%) | Loan = 0 | 50 if no loan, 0 if >250k loan |

**League titles**: Engineer (0-127), Traffic Manager (128-255), Transport Coordinator (256-383), Route Supervisor (384-511), Director (512-639), Chief Executive (640-767), Chairman (768-895), President (896-959), **Tycoon** (960-1000)

### 7.2 Local Authority Rating (-1000 to +1000)

This determines whether you can build stations in a town.

**Starting value**: +500

| Action | Rating Change |
|--------|--------------|
| Build station | Requires minimum -200 rating |
| Destroy building/house | -125 per building |
| Destroy road | -18 to -50 per tile |
| Remove trees near town | -35 per tree |
| Plant trees | +7 per tree (cap at 220 before diminishing) |
| Active station (monthly) | +12 per station with cargo transferred |
| Inactive station (monthly) | -15 per station (no cargo in 50 days) |
| Successful bribe | +200 (max 800) |
| Failed bribe | Set to -50 |
| "Build statue" town action | Permanent +10% station rating bonus |

**Rating titles**: Atrocious (-1000 to -400), Very Poor (-400 to -200), Poor (-200 to 0), Mediocre (0 to 200), Good (200 to 400), Very Good (400 to 600), Excellent (600 to 800), **Outstanding** (800 to 1000)

**Key for AI**: Must maintain at least -200 to build new stations. Planting trees (+7 each) is the safest way to recover. Bribes are risky (failure = -50 and caught).

---

## 8. Signals System

Signals are critical for railway operations. They prevent collisions and control train flow.

### 8.1 Signal Types

| Signal | Type | Direction | Behavior |
|--------|------|-----------|----------|
| **Path Signal** | Modern | One-way | Reserves path through junction; multiple trains can share block if paths don't conflict |
| **One-Way Path Signal** | Modern | One-way (strict) | Same as path signal but trains cannot pass from behind |
| **Block Signal** | Basic | Two-way or one-way | Prevents entry if any train in the block ahead |
| **Entry Pre-Signal** | Advanced | Two-way or one-way | Green only if at least one exit signal is green |
| **Exit Pre-Signal** | Advanced | Two-way or one-way | Marks exit from a pre-signal group |
| **Combo Pre-Signal** | Advanced | Two-way or one-way | Acts as both entry and exit |

### 8.2 Recommended Signal Usage

**Path signals are recommended for 95% of cases.** They are simpler and more efficient.

**Rules of thumb**:
1. Place one-way path signals **where trains should wait** (facing the direction trains come from)
2. Space signals by train length (e.g., every 5 tiles for 5-tile trains)
3. Never place signals **on** junctions
4. Signals cannot be placed on bridges or in tunnels
5. Double-track mainlines: One-way path signals at regular intervals on each track

### 8.3 Signal Placement via GS

```
GSRail.BuildSignal(tile, front_tile, signal_type)
```

Signal types (constants):
- `SIGNALTYPE_NORMAL` = Block signal
- `SIGNALTYPE_ENTRY` = Entry pre-signal
- `SIGNALTYPE_EXIT` = Exit pre-signal
- `SIGNALTYPE_COMBO` = Combo pre-signal
- `SIGNALTYPE_PBS` = Path signal
- `SIGNALTYPE_PBS_ONEWAY` = One-way path signal

The `front_tile` determines which direction the signal faces.

---

## 9. Orders System (Complete Reference)

### 9.1 Order Types

| Type | Description | GS Check |
|------|-------------|----------|
| **Go to Station** | Vehicle visits a station | `GSOrder.IsGotoStationOrder()` |
| **Go to Depot** | Vehicle visits a depot (for service/refit) | `GSOrder.IsGotoDepotOrder()` |
| **Go to Waypoint** | Vehicle passes through waypoint (trains/ships) | `GSOrder.IsGotoWaypointOrder()` |
| **Conditional** | Branch to different order based on condition | `GSOrder.IsConditionalOrder()` |

### 9.2 Order Flags (Bitfield)

**Loading behavior**:
- `OF_LOAD_IF_POSSIBLE` — Load available cargo and depart
- `OF_FULL_LOAD_ALL` — Wait until completely full of all cargo
- `OF_FULL_LOAD_ANY` — Wait until full of any single cargo type
- `OF_NO_LOAD` — Skip loading entirely

**Unloading behavior**:
- `OF_UNLOAD_IF_POSSIBLE` — Unload accepted cargo
- `OF_UNLOAD_ALL` — Unload everything regardless of acceptance
- `OF_TRANSFER` — Unload and receive partial payment for distance traveled (for feeder routes)
- `OF_NO_UNLOAD` — Skip unloading entirely

**Stop behavior**:
- `OF_GOTO` — Stop at intermediate stations
- `OF_NON_STOP` — Don't stop at any station except the destination
- `OF_VIA` — Use station as waypoint (pass through)
- `OF_NON_STOP_VIA` — Non-stop waypoint

### 9.3 Conditional Orders

Conditional orders allow branching logic. They jump to a specified order position if a condition is met.

**Conditions** (`GSOrder.OrderCondition`):
- `OC_LOAD_PERCENTAGE` — Current load as percentage
- `OC_RELIABILITY` — Vehicle reliability percentage
- `OC_MAX_SPEED` — Vehicle's current max speed
- `OC_AGE` — Vehicle age in years
- `OC_REQUIRES_SERVICE` — Vehicle needs servicing (bool)
- `OC_UNCONDITIONALLY` — Always jump
- `OC_REMAINING_LIFETIME` — Days until retirement
- `OC_MAX_RELIABILITY` — Maximum possible reliability

**Comparison functions** (`GSOrder.CompareFunction`):
- `CF_EQUALS`, `CF_NOT_EQUALS`
- `CF_LESS_THAN`, `CF_LESS_EQUALS`
- `CF_MORE_THAN`, `CF_MORE_EQUALS`
- `CF_IS_TRUE`, `CF_IS_FALSE`

**GS API for conditional orders**:
```
GSOrder.AppendConditionalOrder(vehicle_id, jump_to_order)
GSOrder.SetOrderCondition(vehicle_id, order_pos, condition)
GSOrder.SetOrderCompareFunction(vehicle_id, order_pos, compare_fn)
GSOrder.SetOrderCompareValue(vehicle_id, order_pos, value)
GSOrder.SetOrderJumpTo(vehicle_id, order_pos, jump_to)
```

### 9.4 Shared Orders

Multiple vehicles can share one order list. Changing one vehicle's orders changes all.

```
GSOrder.ShareOrders(vehicle_id, source_vehicle_id)  // Share
GSOrder.CopyOrders(vehicle_id, source_vehicle_id)    // One-time copy
GSOrder.UnshareOrders(vehicle_id)                     // Break sharing
```

### 9.5 Depot Orders

Depot orders can include:
- **Service**: Vehicle gets maintained
- **Refit**: Vehicle changes cargo type at depot
- **Stop**: Vehicle stops in depot (useful for retiring vehicles)

```
GSOrder.SetOrderRefit(vehicle_id, order_pos, cargo_type)
```

### 9.6 Stop Location (Trains Only)

Controls where trains stop at platforms:
- `STOPLOCATION_NEAR` — Stop at near end of platform
- `STOPLOCATION_MIDDLE` — Stop in middle
- `STOPLOCATION_FAR` — Stop at far end

```
GSOrder.SetStopLocation(vehicle_id, order_pos, stop_location)
```

---

## 10. Vehicle Speed Mechanics

### 10.1 Speed Unit

OpenTTD uses "km-ish/h" internally. One tile = 664.216 km-ish (668 km or 415 miles).

### 10.2 Train Speed (Realistic Acceleration)

**Acceleration formula** (per half-tick):
```
acceleration = (force - friction) / mass
force = min(power * 746 / speed, tractive_effort * 1000 * 9.8)
friction = air_drag * speed^2 / 1000 + mass * slope_factor * 9.8
```

**Curve speed limits** (depends on curvature tightness):

| Wagon-to-curve ratio | Railroad | Electrified | Monorail | Maglev |
|---------------------|----------|-------------|----------|--------|
| 0 (very tight) | 61 km/h | 61 km/h | 91 km/h | 346 km/h |
| 1 | 88 km/h | 88 km/h | 132 km/h | 346 km/h |
| 2 | 111 km/h | 111 km/h | 166 km/h | 346 km/h |
| 3 | 132 km/h | 132 km/h | 198 km/h | 346 km/h |
| 4 | 151 km/h | 151 km/h | 226 km/h | 346 km/h |
| 5+ | 231 km/h | 231 km/h | 346 km/h | 461 km/h |

**AI implication**: Build tracks with gentle curves. Straight tracks allow maximum speed.

### 10.3 Road Vehicle Speed

- **Acceleration**: 37 km-ish/h per day
- **Cornering**: **Half speed** on every turn
- **Downhill bonus**: +74 km-ish/h acceleration
- **AI implication**: Keep roads straight for maximum efficiency

### 10.4 Aircraft Speed

- **Listed speed vs actual**: Aircraft fly at **1/4 of listed speed** (configurable)
- **Acceleration**: 144-400 km-ish/h daily
- **Broken planes**: Fixed 320 km-ish/h
- **Taxi speed**: 150 km-ish/h (on airport)
- **AI implication**: Aircraft speed is deceptive; check actual speed for income calculations

### 10.5 Ship Speed

- **Acceleration**: 37 km-ish/h daily
- **Generally**: Slowest transport type
- **AI implication**: Ships are profitable for high-volume, long-distance routes where speed doesn't matter (e.g., oil from offshore rigs)

---

## 11. Construction Mechanics

### 11.1 Building on Slopes

- Most construction requires **flat land** or specific slope orientations
- Stations generally need flat tiles
- Roads and rail can be built on slopes (with restrictions on direction)
- Bridges span gaps; tunnels go through hills
- **Landscaping**: `GSTile.RaiseTile()`, `LowerTile()`, `LevelTiles()` can modify terrain

### 11.2 Station Spread

- Stations can be composed of multiple parts (e.g., bus stop + loading bay = one combined station)
- Parts must be within the **station spread limit** (game setting, typically 12-20 tiles)
- All parts share the same station ID and cargo pool
- **AI tactic**: Attach a bus stop to a train station to pick up passengers generated by train deliveries

### 11.3 Bridge Construction

- Bridges connect two tiles at the same height on opposite sides of a gap
- Bridge types have different max lengths and max speeds
- Road bridges automatically include road; rail bridges need existing rail type set
- **GS API**: `GSBridge.BuildBridge(vehicle_type, bridge_type, start, end)`

### 11.4 Tunnel Construction

- Tunnel entrance must be on a slope facing into the hill
- Tunnel automatically finds the exit on the other side
- No signals allowed inside tunnels
- **GS API**: `GSTunnel.BuildTunnel(vehicle_type, start_tile)` — exit tile is automatic

### 11.5 Cost Factors

Construction costs scale with:
- **Base cost**: Per tile type (road < rail < water < air)
- **Terrain modification**: Raising/lowering land costs money
- **Demolition**: Removing buildings/infrastructure costs money
- **Water**: Building on water (canals) is expensive
- **Bridge length**: Longer bridges cost more

**GS API for cost queries**:
- `GSTile.GetBuildCost(build_type)` — base costs
- `GSRail.GetBuildCost(rail_type, build_type)` — rail-specific
- `GSRoad.GetBuildCost(road_type, build_type)` — road-specific
- `GSMarine.GetBuildCost(build_type)` — marine-specific
- `GSBridge.GetPrice(bridge_type, length)` — bridge costs
- `GSAirport.GetPrice(airport_type)` — airport costs
- `GSEngine.GetPrice(engine_id)` — vehicle purchase costs
- `GSEngine.GetRunningCost(engine_id)` — annual running costs

---

## 12. Multiplayer Considerations

### 12.1 Key Differences from Single Player

- **No pause control**: Players cannot pause/unpause (server admin only)
- **No fast-forward**: Game runs at server speed only
- **Global pause**: When game pauses, ALL players are affected
- **Up to 15 companies**, 255 clients
- **Chat system**: Players communicate via text messages

### 12.2 Company Management

- Players can create, join, or spectate companies
- Companies can be password-protected
- Players can move between companies without disconnecting
- AI companies can coexist with human companies

### 12.3 Implications for nttd

- GameScript can act as any company via `GSCompanyMode`
- Admin port provides server-level control
- Pause/unpause affects all players — must coordinate in multiplayer
- Game speed changes affect everyone

---

## 13. Vehicle Replacement & Auto-Replace

### 13.1 Manual Replacement

Send vehicle to depot, sell it, buy new one with same orders. Tedious.

### 13.2 Auto-Replace

Set up automatic engine replacement rules per group:
- `GSGroup.SetAutoReplace(group_id, old_engine_id, new_engine_id)`
- `GSGroup.StopAutoReplace(group_id, engine_id)`
- `GSGroup.EnableAutoReplaceProtection(group_id, enable)` — exclude group from global rules
- `GSGroup.EnableWagonRemoval(keep_length)` — remove excess wagons when replacing

### 13.3 Auto-Renew

Company-level setting for automatically replacing vehicles nearing retirement:
- `GSCompany.SetAutoRenewStatus(bool)` — enable/disable
- `GSCompany.SetAutoRenewMonths(months)` — how many months before/after max age
- `GSCompany.SetAutoRenewMoney(money)` — minimum balance required

---

## 14. Vehicle Groups

Groups organize vehicles for management:
- Create groups with vehicle type filter
- Hierarchical (parent/child groups)
- Per-group auto-replace rules
- Per-group profit tracking
- Per-group livery colors

**GS API**:
```
GSGroup.CreateGroup(vehicle_type, parent_group_id)
GSGroup.MoveVehicle(group_id, vehicle_id)
GSGroup.GetProfitThisYear(group_id) / GetProfitLastYear(group_id)
GSGroup.GetNumVehicles(group_id, vehicle_type)
GSGroup.SetPrimaryColour(group_id, colour)
```

---

## 15. Subsidies

Subsidies are temporary bonus payments for transporting specific cargo between specific locations.

- **Duration**: Offered for ~1 year; if claimed, lasts ~1 year
- **Bonus**: 1.5x to 2x normal payment
- **Source/Destination**: Town or Industry
- **GS-exclusive**: `GSSubsidy.Create(cargo, src_type, src_id, dst_type, dst_id)`

**Query API**:
```
GSSubsidy.GetCargoType(id)
GSSubsidy.GetSourceType/Index(id)
GSSubsidy.GetDestinationType/Index(id)
GSSubsidy.GetExpireDate(id)
GSSubsidy.IsAwarded(id)
GSSubsidy.GetAwardedTo(id)
```

---

## 16. Cargo Distribution

### 16.1 Production Distribution

When an industry produces cargo, it distributes among nearby stations based on:
1. **Station rating** (higher = more cargo)
2. **Company tier** (better-performing companies get priority)
3. **Station presence** (station must accept that cargo type)

### 16.2 Cargo Acceptance

Tiles accept cargo based on buildings/industries within station coverage:
- Houses accept passengers and mail
- Industries accept their input cargo types
- Minimum acceptance threshold: 8/8 (some tiles contribute fractional acceptance)

**GS API**: `GSTile.GetCargoAcceptance(tile, cargo, width, height, radius)` — calculates total acceptance in area

### 16.3 Cargo Waiting & Routing (Cargodist)

Modern OpenTTD uses **cargodist** — cargo has origin, next-hop, and destination information:
- `GSStation.GetCargoWaiting(station_id, cargo)` — total waiting
- `GSStation.GetCargoWaitingFrom(station_id, from_station, cargo)` — from specific origin
- `GSStation.GetCargoWaitingVia(station_id, via_station, cargo)` — heading to specific next hop
- `GSStation.GetCargoPlanned(station_id, cargo)` — expected monthly flow

---

## Summary: What AI Agents Need to Know

1. **Revenue optimization**: Distance x speed x cargo value. Long routes with fast vehicles and high-value cargo win.
2. **Station ratings are crucial**: Keep them high with fast, new, frequent vehicles. Below 50% = cargo loss.
3. **Town authority matters**: Need -200+ to build stations. Plant trees to recover.
4. **Industry production responds to service**: >60% transported = growth bias.
5. **Signals enable capacity**: More trains per track with proper signaling.
6. **Orders are powerful**: Conditional orders, shared orders, and refit orders enable complex logistics.
7. **Vehicle groups simplify management**: Auto-replace, profit tracking per route.
8. **Subsidies are free money**: Always check for available subsidies.
9. **Climate affects strategy**: Sub-arctic/tropical need food/water delivery to towns.
10. **Compound actions are key**: Building a route requires 5-10 coordinated primitive actions.
