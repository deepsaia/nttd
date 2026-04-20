# Orientation and Direction: Research for Next Iteration

Investigation of how orientation/direction affects station, depot, and stop placement
across the nttd GS API pipeline. Documents current behavior, known gaps, and gameplay
impact to inform the next round of fixes.

---

## How orientation works in OpenTTD

Every placed structure has an orientation that determines how vehicles enter/exit it:

- **Rail stations**: NE_SW (direction=0, horizontal) or NW_SE (direction=1, vertical).
  Platforms run along the orientation axis. Track must approach from matching axis ends.
- **Rail depots**: Direction 0-3 determines which adjacent tile has the entrance.
  A train exits the depot onto the tile specified by `_GetAdjacentTile(tile, dir)`.
- **Road stops**: Direction 0-3 determines which adjacent tile is the vehicle entrance.
  Drive-through stops allow vehicles from both directions along one axis.
- **Road depots**: Same as rail depots -- direction points at the entrance tile.

Direction mapping (shared across all structure types):
- 0 = East (+x), 1 = South (+y), 2 = West (-x), 3 = North (-y)

---

## Current state of the API pipeline

### What returns direction to the agent

| Tool | Returns direction? | How determined |
|------|--------------------|----------------|
| `find_bus_stop_spots` | Yes (`direction`) | `_GetAdjacentRoads` + dry-run |
| `find_depot_spots` (road) | Yes (`depot_direction`) | `_GetAdjacentRoads` + dry-run |
| `find_rail_depot_spot` | Yes (`depot_direction`) | `_GetAdjacentRailTrack` + dry-run |
| `find_station_spot` | **No** | Hardcoded NE_SW in dry-run |
| `find_flat_spots` (station_test) | **No** | Hardcoded NE_SW in dry-run |
| `find_airport_spots` | No (airports have fixed orientation) | N/A |
| `find_dock_spots` | No (docks auto-orient to coast) | N/A |

### What accepts direction from the agent

| Build command | Accepts direction? | Default |
|---------------|-------------------|---------|
| `build_road_stop` | Yes (`direction`, 0-3) | 0 |
| `build_road_depot` | Yes (`direction`, 0-3) | 0 |
| `build_rail_depot` | Yes (`direction`, 0-3) | 0 |
| `build_rail_station` | Yes (`direction`, 0 or 1) | 0 (NE_SW) |
| `build_water_depot` | Yes (`direction`, 0-3) | 0 |
| `build_airport` | No | Fixed |
| `build_dock` | No | Auto |

### The gap

`find_station_spot` hardcodes NE_SW in its dry-run
(`main.nut:1458`). `build_rail_station` accepts direction 0 or 1.
So the find tool only validates spots where NE_SW works. Spots where only NW_SE works
are silently skipped. The agent has no way to discover NW_SE-valid spots and no returned
orientation to pass to `build_rail_station`.

---

## Gameplay impact analysis

### Rail station orientation vs connect_rail

This is the most nuanced interaction.

**How `connect_rail` builds track at endpoints (`_BuildRailPath`, main.nut:2499-2528):**

The pathfinder approaches from any direction. At the station tile (first or last in
path), it constructs a 3-tile context (prev, cur, next) and calls
`GSRail.BuildRail(prev, cur, next)`. OpenTTD infers track orientation from the context.

**The mismatch scenario:**

1. Agent builds station with direction=0 (NE_SW, the default and only validated option)
2. `connect_rail` pathfinder approaches from the NW_SE axis
3. `BuildRail` attempts to place NW_SE track on the NE_SW station tile
4. OpenTTD rejects this -- station tile already has NE_SW track
5. Error is `ERR_ALREADY_BUILT`, which the code treats as success (line 2526)
6. Track appears "built" but is NOT connected to the station

**Result:** The train path ends one tile short of the station. The train may be able to
reach the station tile via NE_SW track from the station's own orientation, OR it may
be completely disconnected depending on approach angle. This is a **silent failure** --
no error is reported, but the train cannot reach the station.

**When this does NOT matter:**
- When the two stations are roughly aligned on the NE_SW axis (same Y, different X),
  the pathfinder naturally approaches from the correct direction
- When terrain forces the path to approach from the correct axis

**When this DOES matter:**
- When stations are aligned on the NW_SE axis (same X, different Y) and the path
  approaches straight from north or south
- When terrain or obstacles force the path to approach at 90 degrees to the station

### Road stops and depots

Road orientation is handled well. Both `find_bus_stop_spots` and `find_depot_spots`
return direction based on adjacent road detection, and `connect_road` builds road that
connects to existing road tiles. The direction returned by find tools is used directly
in build commands. No known silent failures here.

### Rail depots

Now handled by `find_rail_depot_spot` (Fix 1), which validates adjacent track before
returning. No orientation gap for depots.

---

## Recommended fixes for next iteration

### 1. Try both orientations in `find_station_spot`

Currently (`main.nut:1458`):
```squirrel
if (!GSRail.BuildRailStation(tile, GSRail.RAILTRACK_NE_SW, 1, platform_length, ...))
    continue;
```

Change to try NE_SW first, then NW_SE. Return `orientation` field (0 or 1) with each spot:
```squirrel
local orientations = [GSRail.RAILTRACK_NE_SW, GSRail.RAILTRACK_NW_SE];
local built_orientation = -1;
foreach (idx, track in orientations) {
    if (GSRail.BuildRailStation(tile, track, 1, platform_length, ...)) {
        built_orientation = idx;
        break;
    }
}
if (built_orientation == -1) continue;
// Return built_orientation as "orientation" field
```

This doubles the search space but finds valid spots that are currently invisible.

### 2. Return `orientation` from `find_station_spot`

Add `orientation` (0=NE_SW, 1=NW_SE) to each returned spot. The agent then passes this
to `build_rail_station(direction=<orientation>)`.

### 3. Expose `direction` in `build_rail_station` tool schema

Currently `observation_tools.py` does not include `direction` in the `build_rail_station`
parameter schema (agents use the action reference, not tool schema, for build actions).
The action reference at `agent_instructions.py:215` lists:
```
build_rail_station    tile, num_platforms, platform_length, rail_type
```
Add `direction` to this list.

### 4. Orientation-aware approach in `connect_rail`

The harder fix. After pathfinding, check if the endpoint tiles are stations and verify
the path approach direction matches station orientation. If mismatched, adjust the last
1-2 path tiles to approach from the correct axis.

This is complex but would prevent the silent `ERR_ALREADY_BUILT` failure. Lower priority
than fixes 1-3 because if `find_station_spot` returns orientation and the agent uses it,
the pathfinder will usually approach correctly for short routes.

### 5. Audit `find_flat_spots` station_test mode

Same hardcoded NE_SW issue at `main.nut:1380`. Apply the same dual-orientation fix.
Lower priority since agents should use `find_station_spot` instead.

---

## Priority assessment

| Fix | Impact | Effort | Priority |
|-----|--------|--------|----------|
| Try both orientations in find_station_spot | High -- finds more valid spots | Low | P1 |
| Return orientation field | Medium -- agents can use correct direction | Low | P1 |
| Add direction to build_rail_station schema | Low -- documentation change | Trivial | P1 |
| Orientation-aware connect_rail | Medium -- prevents silent mismatch | High | P2 |
| Fix find_flat_spots station_test | Low -- agents should use find_station_spot | Low | P3 |

Fixes 1-3 are small, low-risk, and should be bundled in the next iteration.
Fix 4 is a pathfinder change and needs careful testing to avoid regressions.
