# nttd GameScript

The `game/nttd-gs/` directory contains the nttd GameScript — Squirrel code that runs inside OpenTTD and handles all queries and game actions that the admin port cannot provide natively.

Communication is JSON over the OpenTTD admin port GameScript channel. The Python admin client (`src/nttd/bridge/admin_client.py`) sends commands and reassembles chunked responses.

## Protocol

```
Client  →  { "id": "gs_1", "action": "get_towns", "params": { ... } }
Server  →  { "id": "gs_1", "success": true, "result": { ... } }

Large arrays are chunked (CHUNK_SIZE = 10):
Server  →  { "id": "gs_1", "success": true, "result": [...], "_chunk": 0, "_total": 3 }
Server  →  { "id": "gs_1", "success": true, "result": [...], "_chunk": 1, "_total": 3 }
Server  →  { "id": "gs_1", "success": true, "result": [...], "_chunk": 2, "_total": 3 }

On error:
Server  →  { "id": "gs_1", "success": false, "error": "ERR_NOT_ENOUGH_CASH" }
```

All action commands require `company_id` in params. OpenTTD's `GSCompanyMode` is used to run commands on behalf of a specific company.

---

## How to Add or Modify Commands

### Adding a new command

**Step 1 — Add a case to `_Dispatch()` in `main.nut`:**
```squirrel
case "my_new_action": return this.CmdMyNewAction(p);
```

**Step 2 — Implement the handler function:**
```squirrel
function CmdMyNewAction(p) {
  local company_mode = GSCompanyMode(p.company_id);  // if company-scoped
  local tile = GSMap.GetTileIndex(p.x, p.y);

  if (GSSomething.DoSomething(tile)) {
    return { success = true, result = { tile = [p.x, p.y] } };
  }
  return { success = false, error = GSError.GetLastErrorString() };
}
```

**Step 3 — Register it in the Python action registry** (`src/nttd/api/action_routes.py`, `_KNOWN_ACTIONS` set) if agents should be able to call it via `POST /actions/submit`.

**Step 4 — Restart the server** (OpenTTD recompiles the GS on startup):
```bash
./scripts/start_openttd_server.sh
```
Check server output for compile errors — they show `file.nut:LINE/COL: error message`.

### Squirrel gotchas
- **Reserved keywords**: `clone`, `parent`, `delete`, `in`, `for`, `function`, `class`, `extends`, `null`, `true`, `false`. Use `cid` instead of `clone`, `parent_id` instead of `parent`.
- **No null coalescing**: Use `("key" in table) ? table.key : default` for optional params.
- **GSCompany.GetLoanAmount()** takes **no arguments** — it uses the current `GSCompanyMode` context.
- **GSBridge.GetName(type, vehicle_type)** takes two args (second is `GSVehicle.VT_ROAD` etc.).
- **GSAirport.GetNoiseLevelIncrease(tile, type)** — tile comes first.
- **Table keys with rawset**: Use `resp.rawset("key", value)` when the key name conflicts with a Squirrel built-in.
- **Array responses**: Return `result = [...]` to get automatic chunking. Return `result = {...}` for single-packet table responses.

### Modifying an existing command

Edit the `CmdXxx()` function body. Parameters are read from `p` (the params table). All changes take effect on next server restart. If you change the response shape, also update the Python schema and `WorldState.apply_gs_*()` if the command feeds WorldState.

### API reference sources

The full OpenTTD GameScript API is in `~/exp/OpenTTD/src/script/api/`. Key files:
- `script_tile.hpp` — tile queries and demolish
- `script_road.hpp` — road build/remove
- `script_rail.hpp` — rail build/remove/convert
- `script_marine.hpp` — waterways
- `script_airport.hpp` — airports
- `script_bridge.hpp` / `script_tunnel.hpp` — bridges and tunnels
- `script_vehicle.hpp` — vehicle management
- `script_order.hpp` — order management
- `script_company.hpp` — company data and actions
- `script_town.hpp` — town data; GS-exclusive: FoundTown, ExpandTown, SetGrowthRate, ChangeRating, SetCargoGoal
- `script_industry.hpp` — industry data
- `script_station.hpp` / `script_basestation.hpp` — station data
- `script_group.hpp` — vehicle groups
- `script_sign.hpp` — signs
- `script_subsidy.hpp` — subsidies; GS-exclusive: Create

---

## Command Reference

### Notation
- `*` = required parameter
- `?` = optional, default shown
- `company_id*` = always required for action commands
- Direction: `0`=NE, `1`=SE, `2`=SW, `3`=NW

---

### Queries — No Side Effects

#### `ping`
No params. Returns `{ pong: true }`. Use to verify the GS is alive.

#### `get_date`
No params. Returns `{ date, year, month, day }`.

#### `get_map_size`
No params. Returns `{ size_x, size_y, max_x, max_y }`.

#### `get_tile_info`
| Param | Type | |
|-------|------|-|
| `x`* | int | Tile X coordinate |
| `y`* | int | Tile Y coordinate |

Returns `{ x, y, height, min_height, slope, is_buildable, is_water, is_coast, has_tree, is_road, is_rail, is_station, owner }`.

#### `get_towns`
No params. Returns array of `{ id, name, population, x, y }`.

#### `get_town_info`
| Param | Type | |
|-------|------|-|
| `town_id`* | int | |

Returns `{ id, name, population, houses, x, y, is_city, growth_rate, has_statue, road_layout, exclusive_rights_company, exclusive_rights_duration, fund_buildings_duration }`.

#### `get_town_rating`
| Param | Type | |
|-------|------|-|
| `town_id`* | int | |
| `company_id`* | int | |

Returns `{ town_id, company_id, rating, detailed_rating }`.

#### `get_industries`
No params. Returns array of `{ id, name, type_id, type_name, x, y }`.

#### `get_industry_info`
| Param | Type | |
|-------|------|-|
| `industry_id`* | int | |

Returns `{ id, name, type_id, type_name, x, y, is_raw, is_processing, production: [{ cargo_id, cargo_label, last_month, transported }] }`.

#### `get_companies`
No params. Returns array of `{ id, name, money, loan, max_loan, hq_x, hq_y }`.

#### `get_company_finance`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |

Returns `{ company_id, balance, loan, max_loan, q1_income, q1_expenses, q1_value, q2_income, q2_expenses, q2_value }`.

#### `get_stations`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |

Returns array of `{ id, name, x, y, has_rail, has_truck, has_bus, has_airport, has_dock }`.

#### `get_station_info`
| Param | Type | |
|-------|------|-|
| `station_id`* | int | |

Returns `{ id, name, x, y, has_rail, has_truck, has_bus, has_airport, has_dock, cargo_waiting: [{ cargo_id, cargo_label, waiting }] }`.

#### `get_waypoints`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |

Returns array of `{ id, name, x, y, is_rail, is_buoy }`.

#### `get_vehicles`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `vehicle_type`? | string | `"train"` \| `"road"` \| `"ship"` \| `"aircraft"` |

Returns array of `{ id, name, type, x, y, engine_id, age, max_age, profit_this_year, profit_last_year, current_speed, state, in_depot, order_count, is_articulated }`.

#### `get_vehicle_info`
| Param | Type | |
|-------|------|-|
| `vehicle_id`* | int | |

Returns full vehicle record including `cargo: [{ cargo_id, capacity, loaded }]` and `orders: [{ index, destination, flags, is_goto_station, is_goto_depot, is_goto_waypoint, is_conditional }]`.

#### `get_engines`
| Param | Type | |
|-------|------|-|
| `vehicle_type`? | string | Default: `"train"` |

Returns array of buildable engines: `{ id, name, cargo_type, capacity, max_speed, price, running_cost, power, weight, reliability, is_wagon }`.

#### `get_cargo_types`
No params. Returns array of `{ id, label, name, is_freight }`.

#### `get_rail_types`
No params. Returns array of `{ id, name }`.

#### `get_road_types`
No params. Returns array of `{ id, name, is_tram }`.

#### `get_groups`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |

Returns array of `{ id, name, vehicle_type, parent_id, profit_this_year, profit_last_year }`.

#### `get_signs`
No params. Returns array of `{ id, name, x, y }`.

#### `get_subsidies`
No params. Returns array of `{ id, is_awarded, cargo_type, source_type, source_index, destination_type, destination_index, remaining }`.

#### `get_airport_types`
No params. Returns array of `{ id, width, height, coverage }`.

#### `get_bridge_types`
No params. Returns array of `{ id, name, max_length, min_length, max_speed, price }`.

---

### Smart Queries

#### `scan_town_area`
| Param | Type | |
|-------|------|-|
| `town_id`* | int | |
| `radius`? | int | Default: `15` |

Returns `{ town_name, center_x, center_y, radius, buildable, roads, buildings, water, counts }`. Each tile list is `[{ x, y }]` (buildable also has `height`, `slope`).

#### `find_bus_stop_spots`
| Param | Type | |
|-------|------|-|
| `town_id`* | int | |
| `radius`? | int | Default: `15` |
| `max_results`? | int | Default: `10` |

Returns array sorted by distance from town center: `{ x, y, distance, adjacent_road_x, adjacent_road_y, adjacent_road_count }`.

#### `find_depot_spots`
| Param | Type | |
|-------|------|-|
| `town_id`* | int | |
| `radius`? | int | Default: `15` |
| `max_results`? | int | Default: `5` |

Returns array sorted by distance: `{ x, y, distance, adjacent_road_x, adjacent_road_y, depot_direction }`.

---

### Road

#### `build_road`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `from_x`*, `from_y`* | int | Start tile |
| `to_x`*, `to_y`* | int | End tile |
| `road_type`? | int | Default: `0` (first road type) |

#### `build_road_line`
Same params as `build_road`. Builds tile-by-tile along a straight axis (same X or same Y). Returns `{ built, failed: [{ x, y, error }], total }`.

#### `build_road_depot`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `x`*, `y`* | int | Depot tile |
| `direction`? | int | Front tile direction. Default: `0` |
| `road_type`? | int | Default: `0` |

#### `build_road_stop`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `x`*, `y`* | int | |
| `direction`? | int | Default: `0` |
| `road_type`? | int | Default: `0` |
| `is_truck_stop`? | bool | Default: `false` (bus stop) |
| `is_drive_through`? | bool | Default: `false` |

#### `remove_road`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `from_x`*, `from_y`* | int | |
| `to_x`*, `to_y`* | int | |
| `road_type`? | int | Default: `0` |

#### `remove_road_depot` / `remove_road_stop`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `x`*, `y`* | int | Tile to remove |

---

### Rail

#### `build_rail`
Two modes:

**3-tile mode** (precise track placement):
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `prev_x`*, `prev_y`* | int | Previous tile |
| `x`*, `y`* | int | Current tile |
| `next_x`*, `next_y`* | int | Next tile |
| `rail_type`? | int | Default: `0` |

**2-tile mode** (segment):
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `from_x`*, `from_y`* | int | |
| `to_x`*, `to_y`* | int | |
| `rail_type`? | int | Default: `0` |

#### `build_rail_track`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `x`*, `y`* | int | |
| `track`? | int | `GSRail.RAILTRACK_*` constant. Default: `RAILTRACK_NE_SW` |
| `rail_type`? | int | Default: `0` |

#### `build_rail_station`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `x`*, `y`* | int | Top-left tile |
| `direction`? | int | `0`=NE-SW, `1`=NW-SE. Default: `0` |
| `num_platforms`? | int | Default: `2` |
| `platform_length`? | int | Default: `5` |
| `rail_type`? | int | Default: `0` |

#### `build_rail_depot`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `x`*, `y`* | int | |
| `direction`? | int | Front direction. Default: `0` |
| `rail_type`? | int | Default: `0` |

#### `build_rail_signal`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `x`*, `y`* | int | |
| `signal_type`? | int | `GSRail.SIGNALTYPE_*`. Default: `0` (normal) |

#### `build_rail_waypoint`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `x`*, `y`* | int | Must be a rail tile |

#### `remove_rail`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `from_x`*, `from_y`* | int | |
| `x`*, `y`* | int | Tile to remove from |
| `to_x`*, `to_y`* | int | |

#### `remove_rail_track`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `x`*, `y`* | int | |
| `track`? | int | Default: `RAILTRACK_NE_SW` |

#### `remove_signal`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `x`*, `y`* | int | Signal tile |
| `front_x`*, `front_y`* | int | Front tile |

#### `remove_rail_station`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `x1`*, `y1`* | int | Corner 1 |
| `x2`*, `y2`* | int | Corner 2 |
| `keep_rail`? | bool | Default: `false` |

#### `convert_rail`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `x1`*, `y1`* | int | Area corner 1 |
| `x2`*, `y2`* | int | Area corner 2 |
| `rail_type`* | int | Target rail type |

---

### Marine

All marine commands take `company_id`* and `x`*, `y`* (tile).

| Command | Extra params | Notes |
|---------|-------------|-------|
| `build_canal` | — | |
| `build_lock` | — | Placed on a slope next to water |
| `build_buoy` | — | Navigation waypoint for ships |
| `build_water_depot` | `direction`? (default `0`) | Front tile direction |
| `remove_canal` | — | |
| `remove_lock` | — | |
| `remove_buoy` | — | |
| `remove_water_depot` | — | |

---

### Airports

#### `build_airport`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `x`*, `y`* | int | Top-left tile |
| `airport_type`? | int | Default: `0`. See `get_airport_types`. |

#### `remove_airport`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `x`*, `y`* | int | Any tile of the airport |

#### `open_close_airport`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `station_id`* | int | |

Toggles the airport open/closed state.

---

### Other Infrastructure

#### `build_dock`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `x`*, `y`* | int | Must be a coast tile |

#### `build_bridge`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `start_x`*, `start_y`* | int | |
| `end_x`*, `end_y`* | int | Must be same row or column |
| `bridge_type`? | int | Default: `0`. See `get_bridge_types`. |
| `transport_type`? | string | `"road"` \| `"rail"` \| `"water"`. Default: `"road"` |

#### `build_tunnel`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `x`*, `y`* | int | Entrance tile (must be on a slope) |
| `transport_type`? | string | `"rail"` \| `"road"`. Default: `"rail"` |

Returns `{ entrance: [x, y], exit_pos: [x, y] }`.

#### `demolish_tile`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `x`*, `y`* | int | |

---

### Company Management

#### `build_company_hq`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `x`*, `y`* | int | Top-left of 2×2 HQ |

#### `set_loan`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `amount`* | int | Must be a multiple of `GetLoanInterval()` |

Returns `{ loan, balance }`.

#### `rename_company`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `name`* | string | |

---

### Town (GS-Exclusive)

These commands are only available to GameScripts, not AIs or players.

#### `found_town`
| Param | Type | |
|-------|------|-|
| `x`*, `y`* | int | |
| `size`? | int | `TOWN_SIZE_SMALL/MEDIUM/LARGE`. Default: `TOWN_SIZE_SMALL` |
| `is_city`? | bool | Default: `false` |
| `road_layout`? | int | `ROAD_LAYOUT_*`. Default: `ROAD_LAYOUT_ORIGINAL` |
| `name`? | string | `null` for random name |

Returns `{ town_id, name, x, y }`.

#### `expand_town`
| Param | Type | |
|-------|------|-|
| `town_id`* | int | |
| `houses`? | int | Number of houses to add. Default: `5` |

Returns `{ town_id, population }`.

#### `set_town_growth`
| Param | Type | |
|-------|------|-|
| `town_id`* | int | |
| `days`* | int | Days between growth ticks. `0` = no growth, `0xFFFFFF` = max rate |

#### `perform_town_action`
| Param | Type | |
|-------|------|-|
| `town_id`* | int | |
| `action`* | int | `GSTown.TOWN_ACTION_*`: `0`=Advertise small, `1`=Advertise medium, `2`=Advertise large, `3`=Road rebuild, `4`=Build statue, `5`=Fund buildings, `6`=Buy exclusive rights, `7`=Bribe |

Returns error if action is not available (insufficient funds, wrong rating, etc.).

#### `get_town_rating`
| Param | Type | |
|-------|------|-|
| `town_id`* | int | |
| `company_id`* | int | |

Returns `{ town_id, company_id, rating, detailed_rating }`.

#### `change_town_rating`
| Param | Type | |
|-------|------|-|
| `town_id`* | int | |
| `company_id`* | int | |
| `delta`* | int | Positive = improve, negative = worsen |

Returns `{ town_id, company_id, new_rating }`.

#### `set_cargo_goal`
| Param | Type | |
|-------|------|-|
| `town_id`* | int | |
| `town_effect`* | int | `GSCargo.TE_*` effect type |
| `goal`* | int | Monthly cargo units required |

---

### Subsidies (GS-Exclusive)

#### `create_subsidy`
| Param | Type | |
|-------|------|-|
| `cargo_type`* | int | Cargo ID |
| `from_type`* | int | `GSSubsidy.SPT_*`: `0`=industry, `1`=town |
| `from_id`* | int | Industry or town ID |
| `to_type`* | int | Same as from_type |
| `to_id`* | int | Industry or town ID |

---

### Signs

#### `build_sign`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `x`*, `y`* | int | |
| `name`* | string | Sign text |

Returns `{ sign_id, name }`.

#### `remove_sign`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `sign_id`* | int | |

---

### Vehicle Groups

#### `create_group`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `vehicle_type`? | string | Default: `"train"` |
| `parent_group_id`? | int | Default: top-level group |

Returns `{ group_id }`.

#### `delete_group`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `group_id`* | int | |

#### `move_to_group`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `group_id`* | int | |
| `vehicle_id`* | int | |

#### `set_auto_replace`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `group_id`* | int | |
| `engine_id_old`* | int | |
| `engine_id_new`* | int | |

---

### Vehicles

#### `buy_vehicle`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `depot_x`*, `depot_y`* | int | Depot tile |
| `engine_id`* | int | From `get_engines` |

Returns `{ vehicle_id, name }`.

#### `sell_vehicle`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `vehicle_id`* | int | Vehicle must be stopped in depot |

#### `sell_wagon`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `vehicle_id`* | int | Train vehicle |
| `wagon`* | int | Wagon index (0 = front) |
| `sell_chain`? | bool | Sell all wagons from this index. Default: `false` |

#### `move_wagon`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `source_vehicle_id`* | int | |
| `source_wagon`* | int | |
| `dest_vehicle_id`* | int | |
| `dest_wagon`* | int | |
| `move_chain`? | bool | Move all attached wagons. Default: `false` |

#### `start_vehicle` / `stop_vehicle`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `vehicle_id`* | int | |

#### `send_to_depot` / `send_to_depot_service`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `vehicle_id`* | int | |

`send_to_depot_service` sends for a service run only, then resumes orders.

#### `clone_vehicle`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `vehicle_id`* | int | Vehicle to clone |
| `share_orders`? | bool | Default: `true` |

Returns `{ vehicle_id, name }` of new vehicle.

#### `refit_vehicle`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `vehicle_id`* | int | |
| `cargo_id`* | int | From `get_cargo_types` |

#### `reverse_vehicle`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `vehicle_id`* | int | |

#### `rename_vehicle`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `vehicle_id`* | int | |
| `name`* | string | |

---

### Orders

#### `add_order`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `vehicle_id`* | int | |
| `station_id`* | int | Destination station |
| `order_flags`? | int | `GSOrder.AIOF_*` flags. Default: `0` |

Appends to end of order list.

#### `insert_order`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `vehicle_id`* | int | |
| `order_position`* | int | Insert before this position |
| `station_id`* | int | |
| `order_flags`? | int | Default: `0` |

#### `remove_order`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `vehicle_id`* | int | |
| `order_position`* | int | |

#### `skip_to_order`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `vehicle_id`* | int | |
| `order_position`* | int | |

#### `move_order`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `vehicle_id`* | int | |
| `from_position`* | int | |
| `to_position`* | int | |

#### `set_order_flags`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `vehicle_id`* | int | |
| `order_position`* | int | |
| `order_flags`* | int | Replacement flags |

#### `share_orders`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `vehicle_id`* | int | Vehicle to share orders from |
| `main_vehicle_id`* | int | Vehicle whose orders to share |

#### `copy_orders`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `vehicle_id`* | int | Vehicle to copy orders to |
| `main_vehicle_id`* | int | Vehicle to copy orders from |

#### `get_orders`
| Param | Type | |
|-------|------|-|
| `company_id`* | int | |
| `vehicle_id`* | int | |

Returns `{ vehicle_id, order_count, orders: [{ index, destination, flags, is_goto_station, is_goto_depot, is_goto_waypoint, is_conditional }] }`.
