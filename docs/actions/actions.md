# Actions

Change the world. These cost money, take effect in the game, and are recorded against your company.

**These are submitted as actions**, through `POST /actions/submit` in real-time play or in a step's batch. Anything on the [observations page](observations.md) is a query instead, asked a different way.

**Generated. Do not edit.** Run `uv run python scripts/generate_action_manifest.py`.
Part of the [action reference](../action_reference.md). 78 of 133 actions.

## Contents

- **air_and_other**: `build_airport`, `build_bridge`, `build_dock`, `build_tunnel`, `demolish_tile`, `open_close_airport`, `remove_airport`
- **company**: `build_company_hq`, `rename_company`, `set_loan`
- **group**: `create_group`, `delete_group`, `move_to_group`, `set_auto_replace`
- **landscape**: `level_tiles`, `lower_tile`, `plant_tree`, `plant_tree_rectangle`, `raise_tile`
- **marine**: `build_buoy`, `build_canal`, `build_lock`, `build_path`, `build_water_depot`, `remove_buoy`, `remove_canal`, `remove_lock`, `remove_water_depot`
- **order**: `add_order`, `copy_orders`, `insert_order`, `move_order`, `remove_order`, `set_order_compare_function`, `set_order_compare_value`, `set_order_condition`, `set_order_flags`, `set_stop_location`, `share_orders`, `skip_to_order`
- **planning**: `estimate_cost`
- **rail**: `build_rail_depot`, `build_rail_signal`, `build_rail_station`, `build_rail_track`, `build_rail_waypoint`, `connect_depot`, `connect_rail`, `convert_rail`, `remove_rail`, `remove_rail_station`, `remove_rail_track`, `remove_signal`
- **road**: `build_one_way_road`, `build_one_way_road_full`, `build_road_depot`, `build_road_stop`, `connect_road`, `convert_road_type`, `remove_road`, `remove_road_depot`, `remove_road_stop`
- **sign**: `build_sign`, `remove_sign`
- **town**: `perform_town_action`
- **vehicle**: `build_train`, `buy_vehicle`, `clone_vehicle`, `move_wagon`, `refit_vehicle`, `rename_vehicle`, `reverse_vehicle`, `sell_vehicle`, `sell_wagon`, `send_to_depot`, `send_to_depot_service`, `start_vehicle`, `stop_vehicle`

Every action on one line, across all three pages: [index.md](index.md).

## air_and_other

### `build_airport`

Build an airport with its north corner at the given tile. The whole footprint must be clear and level, and larger types only become available from the year they are introduced.

Supply one of: `tile` or `x` and `y`.

- `airport_type` (integer, default 0) Which airport layout to build. Availability depends on the year and the map.
- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

`airport_type` accepts (GSAirport): `AT_COMMUTER` = 5, `AT_HELIDEPOT` = 6, `AT_HELIPORT` = 2, `AT_HELISTATION` = 8, `AT_INTERCON` = 7, `AT_INTERNATIONAL` = 4, `AT_LARGE` = 1, `AT_METROPOLITAN` = 3, `AT_SMALL` = 0

Returns `station_id`, `tile`, `type`.

### `build_bridge`

Bridge the gap between two tiles. The ends must be in line and at the same height, with the span clear between them.

- `bridge_type` (integer, default 0) Which bridge design to use. Numbered by the running game: ask get_bridge_types. Designs differ in speed limit and cost.
- `end_x` (integer, required) X coordinate of the far end.
- `end_y` (integer, required) Y coordinate of the far end.
- `start_x` (integer, required) X coordinate of the near end.
- `start_y` (integer, required) Y coordinate of the near end.
- `transport_type` (string, default "road") What crosses the bridge: rail, water, or road. Anything else is treated as road.

Returns `end_pos`, `start`.

### `build_dock`

Build a dock on a coastal tile, giving ships somewhere to load. The tile must slope into water.

Supply one of: `tile` or `x` and `y`.

- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns `station_id`, `tile`.

### `build_tunnel`

Bore a tunnel into the hillside at the given tile. OpenTTD picks the far end itself, following the slope until the land rises again, so the exit is reported back rather than chosen.

Supply one of: `tile` or `x` and `y`.

- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `transport_type` (string, default "rail") What runs through the tunnel: rail or road. Anything else is treated as rail.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns `entrance`, `exit_pos`.

### `demolish_tile`

Clear whatever is on the tile. Works on your own structures and on trees and rocks, and costs money.

Supply one of: `tile` or `x` and `y`.

- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns `tile`.

### `open_close_airport`

Toggle an airport between accepting and refusing arrivals. Aircraft already inbound still land.

- `station_id` (integer, required) Which station.

Returns `station_id`.

### `remove_airport`

Remove an airport, given any tile of it.

Supply one of: `tile` or `x` and `y`.

- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns `tile`.

## company

### `build_company_hq`

Place the company headquarters, which occupies four tiles with its north corner at the given tile. Building it again moves it, at the cost of the old one.

Supply one of: `tile` or `x` and `y`.

- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns `tile`.

### `rename_company`

Rename your company.

- `name` (string, required) A name to give.

Returns `name`.

### `set_loan`

Set the loan to an exact amount rather than adjusting it. Raising it pays out immediately, lowering it repays from the bank balance, and the amount is rounded to the game's loan interval.

- `amount` (integer, required) An amount of money, in the game's currency units.

Returns `balance`, `loan`.

## group

### `create_group`

Create a group to organise vehicles of one type. Groups carry their own profit figures and can drive automatic replacement.

- `parent_group_id` (integer, default GSGroup.GROUP_INVALID) Group to nest the new group inside. Omit for a top-level group.
- `vehicle_type` (string, default "train") One of train, road, ship or aircraft. An unrecognised value silently becomes train.

Returns `group_id`.

### `delete_group`

Delete a group. The vehicles in it are not sold, they return to being ungrouped.

- `group_id` (integer, required) Which vehicle group.

Returns no data beyond success.

### `move_to_group`

Move a vehicle into a group.

- `group_id` (integer, required) Which vehicle group.
- `vehicle_id` (integer, required) Which vehicle.

Returns no data beyond success.

### `set_auto_replace`

Have vehicles in a group replaced with a newer model when they next visit a depot. Set the new engine equal to the old one to cancel.

- `engine_id_new` (integer, required) The engine model to replace with.
- `engine_id_old` (integer, required) The engine model to replace.
- `group_id` (integer, required) Which vehicle group.

Returns no data beyond success.

## landscape

### `level_tiles`

Flatten the rectangle between two corners to a single height. Cost rises steeply with the amount of earth moved.

- `x1` (integer, required) X coordinate of the first corner.
- `x2` (integer, required) X coordinate of the opposite corner.
- `y1` (integer, required) Y coordinate of the first corner.
- `y2` (integer, required) Y coordinate of the opposite corner.

Returns `x1`, `x2`, `y1`, `y2`.

### `lower_tile`

Lower the named corners of a tile by one step.

Supply one of: `tile` or `x` and `y`.

- `slope` (integer, required) Which corners of the tile to move, as a bitmask of the four compass corners.
- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

`slope` accepts (GSTile): `SLOPE_E` = 4, `SLOPE_ELEVATED` = 15, `SLOPE_ENW` = 13, `SLOPE_EW` = 5, `SLOPE_FLAT` = 0, `SLOPE_N` = 8, `SLOPE_NE` = 12, `SLOPE_NS` = 10, `SLOPE_NW` = 9, `SLOPE_NWS` = 11, `SLOPE_S` = 2, `SLOPE_SE` = 6, `SLOPE_SEN` = 14, `SLOPE_STEEP` = 16, `SLOPE_STEEP_E` = 30, `SLOPE_STEEP_N` = 29, `SLOPE_STEEP_S` = 23, `SLOPE_STEEP_W` = 27, `SLOPE_SW` = 3, `SLOPE_W` = 1, `SLOPE_WSE` = 7

Returns `x`, `y`.

### `plant_tree`

Plant a tree on a tile. Trees raise the town's opinion of you and offset the rating lost to construction.

Supply one of: `tile` or `x` and `y`.

- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns `x`, `y`.

### `plant_tree_rectangle`

Plant trees across a rectangle given as a corner and a size. Note this takes width and height, not a second corner.

Supply one of: `tile` or `x` and `y`.

- `height` (integer, required) Extent along y, in tiles.
- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `width` (integer, required) Extent along x, in tiles.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns `height`, `width`, `x`, `y`.

### `raise_tile`

Raise the named corners of a tile by one step.

Supply one of: `tile` or `x` and `y`.

- `slope` (integer, required) Which corners of the tile to move, as a bitmask of the four compass corners.
- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

`slope` accepts (GSTile): `SLOPE_E` = 4, `SLOPE_ELEVATED` = 15, `SLOPE_ENW` = 13, `SLOPE_EW` = 5, `SLOPE_FLAT` = 0, `SLOPE_N` = 8, `SLOPE_NE` = 12, `SLOPE_NS` = 10, `SLOPE_NW` = 9, `SLOPE_NWS` = 11, `SLOPE_S` = 2, `SLOPE_SE` = 6, `SLOPE_SEN` = 14, `SLOPE_STEEP` = 16, `SLOPE_STEEP_E` = 30, `SLOPE_STEEP_N` = 29, `SLOPE_STEEP_S` = 23, `SLOPE_STEEP_W` = 27, `SLOPE_SW` = 3, `SLOPE_W` = 1, `SLOPE_WSE` = 7

Returns `x`, `y`.

## marine

### `build_buoy`

Place a buoy on a water tile. Ships route through buoys, which is how a sea lane is steered around a headland.

Supply one of: `tile` or `x` and `y`.

- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns `tile`.

### `build_canal`

Turn a flat land tile into canal. The tile must be at sea level or bounded by water or lock.

Supply one of: `tile` or `x` and `y`.

- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns `tile`.

### `build_lock`

Build a lock so ships can change height. It must sit on the slope between two water levels.

Supply one of: `tile` or `x` and `y`.

- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns `tile`.

### `build_path`

Lay a route you have already chosen, tile by tile. This is how you build a line of your own design: give the tiles and nttd works out how each piece must sit, including the three-tile context rail needs, so nothing has to reason about track orientation. Bridges and tunnels are steps like any other. Steps that only pass over infrastructure already there are skipped rather than paid for. It succeeds only if nothing was refused, and the reply reports what was built, what was already there, what was skipped and what failed. Use connect_rail or connect_road instead when you would rather nttd chose the route.

- `rail_type` (integer, default 0) Which rail technology to build with. Numbered by the running game and gated by year, so ask get_rail_types.
- `road_type` (integer, default 0) Which road technology to build with. Numbered by the running game, so ask get_road_types. Tram tracks are road types too.
- `steps` (array, required) The path to lay, as objects carrying x, y and an action. At least two are needed.
- `transport_type` (string, default "road") What the path carries: rail or road. Anything else is treated as road.

Returns `built`, `errors`, `existing`, `failed`, `skipped`, `status`, `total_steps`.

Each `failed` carries `action`, `error`, `error_category`, `error_code`, `x`, `y`.

### `build_water_depot`

Build a ship depot on water. It occupies two tiles, the second chosen by direction.

Supply one of: `tile` or `x` and `y`.

- `direction` (integer, default 0) Which neighbouring tile the vehicle enters from: 0 is +x, 1 is +y, 2 is -x, 3 is -y. Any other value means the tile itself.
- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns `tile`.

### `remove_buoy`

Remove a buoy. It fails while a ship still has an order pointing at it.

Supply one of: `tile` or `x` and `y`.

- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns no data beyond success.

### `remove_canal`

Turn a canal tile back into land.

Supply one of: `tile` or `x` and `y`.

- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns no data beyond success.

### `remove_lock`

Remove a lock.

Supply one of: `tile` or `x` and `y`.

- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns no data beyond success.

### `remove_water_depot`

Remove a ship depot.

Supply one of: `tile` or `x` and `y`.

- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns no data beyond success.

## order

### `add_order`

Append an order to the end of a vehicle's list. The destination may be given as a station id or as a tile, and a station is checked against the vehicle type first, so a ship is not sent to a bus stop. Non-stop flags are dropped for aircraft and ships, which have no use for them.

Supply one of: `station_id` or `dest_tile` or `destination`.

- `dest_tile` (integer, optional) Tile index the order sends the vehicle to.
- `destination` (integer, optional) Where the order sends the vehicle. Read as a tile index, and as a station id if that is not a valid tile.
- `order_flags` (integer, default 0) Bitmask combining loading, unloading, non-stop and depot behaviour. Add the constants together.
- `station_id` (integer, optional) Which station.
- `vehicle_id` (integer, required) Which vehicle.

`order_flags` accepts (GSOrder): `OF_DEPOT_FLAGS` = 268, `OF_FULL_LOAD` = 64, `OF_FULL_LOAD_ANY` = 96, `OF_GOTO_NEAREST_DEPOT` = 256, `OF_LOAD_FLAGS` = 224, `OF_NONE` = 0, `OF_NON_STOP_DESTINATION` = 2, `OF_NON_STOP_FLAGS` = 3, `OF_NON_STOP_INTERMEDIATE` = 1, `OF_NO_LOAD` = 128, `OF_NO_UNLOAD` = 16, `OF_SERVICE_IF_NEEDED` = 4, `OF_STOP_IN_DEPOT` = 8, `OF_TRANSFER` = 8, `OF_UNLOAD` = 4, `OF_UNLOAD_FLAGS` = 28

Returns `order_count`.

### `copy_orders`

Replace a vehicle's orders with a copy of another's. The two lists are independent afterwards, unlike share_orders.

- `main_vehicle_id` (integer, required) The vehicle whose orders are the source.
- `vehicle_id` (integer, required) Which vehicle.

Returns `order_count`.

### `insert_order`

Insert an order at a position, pushing later orders down. Takes the same destination forms as add_order.

Supply one of: `station_id` or `dest_tile` or `destination`.

Supply one of: `order_index` or `order_position`.

- `dest_tile` (integer, optional) Tile index the order sends the vehicle to.
- `destination` (integer, optional) Where the order sends the vehicle. Read as a tile index, and as a station id if that is not a valid tile.
- `order_flags` (integer, default 0) Bitmask combining loading, unloading, non-stop and depot behaviour. Add the constants together.
- `order_index` (integer, optional) Position in the order list, counting from 0.
- `order_position` (integer, optional) Position in the order list, counting from 0.
- `station_id` (integer, optional) Which station.
- `vehicle_id` (integer, required) Which vehicle.

`order_flags` accepts (GSOrder): `OF_DEPOT_FLAGS` = 268, `OF_FULL_LOAD` = 64, `OF_FULL_LOAD_ANY` = 96, `OF_GOTO_NEAREST_DEPOT` = 256, `OF_LOAD_FLAGS` = 224, `OF_NONE` = 0, `OF_NON_STOP_DESTINATION` = 2, `OF_NON_STOP_FLAGS` = 3, `OF_NON_STOP_INTERMEDIATE` = 1, `OF_NO_LOAD` = 128, `OF_NO_UNLOAD` = 16, `OF_SERVICE_IF_NEEDED` = 4, `OF_STOP_IN_DEPOT` = 8, `OF_TRANSFER` = 8, `OF_UNLOAD` = 4, `OF_UNLOAD_FLAGS` = 28

Returns `order_count`.

### `move_order`

Move an order to a different position in the list.

Supply one of: `from_index` or `from_position`.

Supply one of: `to_index` or `to_position`.

- `from_index` (integer, optional) Position in the order list to move from, counting from 0.
- `from_position` (integer, optional) Position in the order list to move from, counting from 0.
- `to_index` (integer, optional) Position in the order list to move to, counting from 0.
- `to_position` (integer, optional) Position in the order list to move to, counting from 0.
- `vehicle_id` (integer, required) Which vehicle.

Returns no data beyond success.

### `remove_order`

Remove one order from a vehicle's list.

Supply one of: `order_index` or `order_position`.

- `order_index` (integer, optional) Position in the order list, counting from 0.
- `order_position` (integer, optional) Position in the order list, counting from 0.
- `vehicle_id` (integer, required) Which vehicle.

Returns `order_count`.

### `set_order_compare_function`

Set how a conditional order compares the value it tests.

- `compare_function` (integer, required) How a conditional order compares its value.
- `order_pos` (integer, required) Position in the order list, counting from 0.
- `vehicle_id` (integer, required) Which vehicle.

`compare_function` accepts (GSOrder): `CF_EQUALS` = 0, `CF_IS_FALSE` = 7, `CF_IS_TRUE` = 6, `CF_LESS_EQUALS` = 3, `CF_LESS_THAN` = 2, `CF_MORE_EQUALS` = 5, `CF_MORE_THAN` = 4, `CF_NOT_EQUALS` = 1

Returns `order_pos`, `vehicle_id`.

### `set_order_compare_value`

Set the value a conditional order compares against.

- `order_pos` (integer, required) Position in the order list, counting from 0.
- `value` (integer, required) The value to set.
- `vehicle_id` (integer, required) Which vehicle.

Returns `order_pos`, `vehicle_id`.

### `set_order_condition`

Turn an order into a conditional one and choose what it tests. Paired with a compare function and a value, this is how a vehicle skips part of its route.

- `condition` (integer, required) What a conditional order tests.
- `order_pos` (integer, required) Position in the order list, counting from 0.
- `vehicle_id` (integer, required) Which vehicle.

`condition` accepts (GSOrder): `OC_AGE` = 3, `OC_LOAD_PERCENTAGE` = 0, `OC_MAX_RELIABILITY` = 7, `OC_MAX_SPEED` = 2, `OC_RELIABILITY` = 1, `OC_REMAINING_LIFETIME` = 6, `OC_REQUIRES_SERVICE` = 4, `OC_UNCONDITIONALLY` = 5

Returns `order_pos`, `vehicle_id`.

### `set_order_flags`

Replace the flags on an existing order. This overwrites rather than adds, so include every flag you still want.

- `order_flags` (integer, required) Bitmask combining loading, unloading, non-stop and depot behaviour. Add the constants together.
- `order_index` (integer, optional) Position in the order list, counting from 0.
- `order_position` (integer, optional) Position in the order list, counting from 0.
- `vehicle_id` (integer, required) Which vehicle.

`order_flags` accepts (GSOrder): `OF_DEPOT_FLAGS` = 268, `OF_FULL_LOAD` = 64, `OF_FULL_LOAD_ANY` = 96, `OF_GOTO_NEAREST_DEPOT` = 256, `OF_LOAD_FLAGS` = 224, `OF_NONE` = 0, `OF_NON_STOP_DESTINATION` = 2, `OF_NON_STOP_FLAGS` = 3, `OF_NON_STOP_INTERMEDIATE` = 1, `OF_NO_LOAD` = 128, `OF_NO_UNLOAD` = 16, `OF_SERVICE_IF_NEEDED` = 4, `OF_STOP_IN_DEPOT` = 8, `OF_TRANSFER` = 8, `OF_UNLOAD` = 4, `OF_UNLOAD_FLAGS` = 28

Returns no data beyond success.

### `set_stop_location`

Choose where along the platform a train comes to rest. Only affects trains shorter than the platform.

- `order_pos` (integer, required) Position in the order list, counting from 0.
- `stop_location` (integer, required) Where along the platform a train stops.
- `vehicle_id` (integer, required) Which vehicle.

`stop_location` accepts (GSOrder): `STOPLOCATION_FAR` = 2, `STOPLOCATION_MIDDLE` = 1, `STOPLOCATION_NEAR` = 0

Returns `order_pos`, `vehicle_id`.

### `share_orders`

Make a vehicle share another's order list. Editing either afterwards changes both, which is how a fleet is kept consistent.

- `main_vehicle_id` (integer, required) The vehicle whose orders are the source.
- `vehicle_id` (integer, required) Which vehicle.

Returns no data beyond success.

### `skip_to_order`

Send a vehicle straight to a given order now, abandoning the current one.

Supply one of: `order_index` or `order_position`.

- `order_index` (integer, optional) Position in the order list, counting from 0.
- `order_position` (integer, optional) Position in the order list, counting from 0.
- `vehicle_id` (integer, required) Which vehicle.

Returns no data beyond success.

## planning

### `estimate_cost`

Report what an action would cost without doing it. The action runs in test mode, so nothing is built and no money moves. A failure here is a genuine refusal and worth reading before committing.

- `action` (string, required) Name of the action to price, exactly as it would be submitted.
- `params` (object, required) The parameters of the action being estimated, exactly as they would be submitted.

Returns `action`, `depot_x`, `depot_y`, `dest_tile`, `estimated_cost`, `from_x`, `from_y`, `to_x`, `to_y`, `x`, `y`.

## rail

### `build_rail_depot`

Build a rail depot at a tile, entered from the neighbour picked by direction. Trains are built and serviced here.

Supply one of: `tile` or `x` and `y`.

- `direction` (integer, default 0) Which neighbouring tile the vehicle enters from: 0 is +x, 1 is +y, 2 is -x, 3 is -y. Any other value means the tile itself.
- `rail_type` (integer, default 0) Which rail technology to build with. Numbered by the running game and gated by year, so ask get_rail_types.
- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns `connected`, `tile`.

### `build_rail_signal`

Place a signal on a track tile. Signals divide a line into blocks, which is what allows more than one train to use it safely.

Supply one of: `tile` or `x` and `y`.

- `signal_type` (integer, default 0) Which kind of signal to place.
- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

`signal_type` accepts (GSRail): `SIGNALTYPE_COMBO` = 3, `SIGNALTYPE_COMBO_TWOWAY` = 11, `SIGNALTYPE_ENTRY` = 1, `SIGNALTYPE_ENTRY_TWOWAY` = 9, `SIGNALTYPE_EXIT` = 2, `SIGNALTYPE_EXIT_TWOWAY` = 10, `SIGNALTYPE_NONE` = 255, `SIGNALTYPE_NORMAL` = 0, `SIGNALTYPE_NORMAL_TWOWAY` = 8, `SIGNALTYPE_PBS` = 4, `SIGNALTYPE_PBS_ONEWAY` = 5, `SIGNALTYPE_TWOWAY` = 8

Returns `tile`.

### `build_rail_station`

Build a rail station with its north corner at the given tile. The whole footprint must be clear and level.

Supply one of: `tile` or `x` and `y`.

- `direction` (integer, default 0) Which way the platforms run: 0 lays them north-east to south-west, 1 north-west to south-east.
- `num_platforms` (integer, default 2) How many parallel platforms to build.
- `platform_length` (integer, default 5) How many tiles long each platform is. A train longer than its platform will not load fully.
- `rail_type` (integer, default 0) Which rail technology to build with. Numbered by the running game and gated by year, so ask get_rail_types.
- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns `length`, `platforms`, `station_id`, `tile`.

### `build_rail_track`

Lay one track piece on one tile, in a chosen orientation. This is the inverse of remove_rail_track and the one shape build_path cannot express, because a path implies its orientations from the tiles either side. Reach for it where there is no path to imply anything: a siding, a junction stub, a passing loop. To lay a line, use build_path, which works the orientations out for you.

Supply one of: `tile` or `x` and `y`.

- `rail_type` (integer, default 0) Which rail technology to build with. Numbered by the running game and gated by year, so ask get_rail_types.
- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `track` (integer, default GSRail.RAILTRACK_NE_SW) Which of the six track pieces on the tile to act on, as a GSRail RAILTRACK value. These are bit flags, not an index: 0 is not a piece and is refused. A straight north-east to south-west piece is 1, north-west to south-east is 2, and the four diagonals are 4, 8, 16 and 32.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

`track` accepts (GSRail): `RAILTRACK_NE_SE` = 32, `RAILTRACK_NE_SW` = 1, `RAILTRACK_NW_NE` = 4, `RAILTRACK_NW_SE` = 2, `RAILTRACK_NW_SW` = 16, `RAILTRACK_SW_SE` = 8

Returns `tile`.

### `build_rail_waypoint`

Build a waypoint on a track tile. Trains can be ordered through one without stopping, which is how a route is forced along a particular line.

Supply one of: `tile` or `x` and `y`.

- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns `tile`.

### `connect_depot`

Join a rail depot to the running line beside it. A depot is not connected by building it: the neighbouring track needs a curve piece facing the depot's entrance, and connect_rail cannot supply one because it lays rail on both endpoints and so fails against the depot itself. Reports which tile it joined to and whether the connection already existed. Refuses when the only neighbouring rail is a station platform, which can never take a track piece.

Supply one of: `tile` or `x` and `y`.

- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns `already_connected`, `joined_at`, `tile`, `track`, `tried`.

Each `tried` carries `error`, `x`, `y`.

### `connect_rail`

Lay track between two tiles, finding the route itself. This is the pathfinding build: it handles curves, and the hint parameters name the tiles to join up with at each end so the result connects to your station rather than merely reaching it. It succeeds only if every segment was laid, because one gap means no route. A partial build keeps whatever it managed and reports which segments failed, so read the status rather than taking a reply as a working line.

Supply one of: `tile_from` or `from_x` and `from_y`.

Supply one of: `tile_to` or `to_x` and `to_y`.

- `from_hint_x` (integer, optional) X coordinate of the tile the path should leave from, usually a station platform. Guides the first step so the track connects rather than merely reaching.
- `from_hint_y` (integer, optional) Y coordinate of the tile the path should leave from, usually a station platform.
- `from_x` (integer, optional) X coordinate of the starting tile.
- `from_y` (integer, optional) Y coordinate of the starting tile.
- `max_iterations` (integer, default 50000) How hard the pathfinder may try before giving up. Raising it costs time, not money.
- `rail_type` (integer, default 0) Which rail technology to build with. Numbered by the running game and gated by year, so ask get_rail_types.
- `tile_from` (integer, optional) Tile index to start from. An alternative to from_x and from_y.
- `tile_to` (integer, optional) Tile index to finish at. An alternative to to_x and to_y.
- `to_hint_x` (integer, optional) X coordinate of the tile the path should arrive at, usually a station platform.
- `to_hint_y` (integer, optional) Y coordinate of the tile the path should arrive at, usually a station platform.
- `to_x` (integer, optional) X coordinate of the finishing tile.
- `to_y` (integer, optional) Y coordinate of the finishing tile.

Returns `built`, `existing`, `failed`, `gaps`, `iterations`, `path`, `path_length`, `status`.

### `convert_rail`

Convert existing track in a rectangle to another rail type. Trains that cannot run on the new type are stranded, so check the fleet first.

Supply one of: `tile` or `x` and `y`.

- `rail_type` (integer, default 0) Which rail technology to build with. Numbered by the running game and gated by year, so ask get_rail_types.
- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `x1` (integer, optional) X coordinate of the first corner.
- `x2` (integer, optional) X coordinate of the opposite corner.
- `y` (integer, optional) Y coordinate on the map, counting from 0.
- `y1` (integer, optional) Y coordinate of the first corner.
- `y2` (integer, optional) Y coordinate of the opposite corner.

Returns no data beyond success.

### `remove_rail`

Remove the single piece of track at one tile, naming the two tiles it joins. Takes the same prev, current, next triple that building rail takes: from_x and from_y for where the track comes from, x and y for the piece being removed, and to_x and to_y for where it leads. All three are required. It does not remove a whole line.

Supply one of: `tile` or `x` and `y`.

Supply one of: `tile_from` or `from_x` and `from_y`.

Supply one of: `tile_to` or `to_x` and `to_y`.

- `from_tile` (integer, optional) Tile index to start from. An alternative to from_x and from_y.
- `from_x` (integer, optional) X coordinate of the starting tile.
- `from_y` (integer, optional) Y coordinate of the starting tile.
- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `tile_from` (integer, optional) Tile index to start from. An alternative to from_x and from_y.
- `tile_to` (integer, optional) Tile index to finish at. An alternative to to_x and to_y.
- `to_tile` (integer, optional) Tile index to finish at. An alternative to to_x and to_y.
- `to_x` (integer, optional) X coordinate of the finishing tile.
- `to_y` (integer, optional) Y coordinate of the finishing tile.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns no data beyond success.

### `remove_rail_station`

Remove the part of a rail station inside a rectangle.

Supply one of: `tile` or `x` and `y`.

- `keep_rail` (boolean, default false) Leave the track behind when the station is removed.
- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `x1` (integer, optional) X coordinate of the first corner.
- `x2` (integer, optional) X coordinate of the opposite corner.
- `y` (integer, optional) Y coordinate on the map, counting from 0.
- `y1` (integer, optional) Y coordinate of the first corner.
- `y2` (integer, optional) Y coordinate of the opposite corner.

Returns `name`, `station_gone`, `station_id`, `tiles_requested`.

### `remove_rail_track`

Remove one track piece from a tile. A tile can carry several, so the piece is named rather than implied.

Supply one of: `tile` or `x` and `y`.

- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `track` (integer, default GSRail.RAILTRACK_NE_SW) Which of the six track pieces on the tile to act on, as a GSRail RAILTRACK value. These are bit flags, not an index: 0 is not a piece and is refused. A straight north-east to south-west piece is 1, north-west to south-east is 2, and the four diagonals are 4, 8, 16 and 32.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

`track` accepts (GSRail): `RAILTRACK_NE_SE` = 32, `RAILTRACK_NE_SW` = 1, `RAILTRACK_NW_NE` = 4, `RAILTRACK_NW_SE` = 2, `RAILTRACK_NW_SW` = 16, `RAILTRACK_SW_SE` = 8

Returns `tile`.

### `remove_signal`

Remove a signal from a track tile. Give the tile it faces, or omit that and all four neighbours are tried.

Supply one of: `tile` or `x` and `y`.

- `front_tile` (integer, optional) Tile index the signal faces. Omit it and all four neighbours are tried.
- `front_x` (integer, optional) X coordinate of the tile the signal faces.
- `front_y` (integer, optional) Y coordinate of the tile the signal faces.
- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns no data beyond success.

## road

### `build_one_way_road`

Build road between two tiles that may be driven in one direction only, running from the first tile to the second.

- `x1` (integer, required) X coordinate of the first corner.
- `x2` (integer, required) X coordinate of the opposite corner.
- `y1` (integer, required) Y coordinate of the first corner.
- `y2` (integer, required) Y coordinate of the opposite corner.

Returns `from`, `to`.

### `build_one_way_road_full`

Build one-way road between two tiles, covering both end tiles fully rather than stopping at their edges. Use this when the road must meet what is already there.

- `x1` (integer, required) X coordinate of the first corner.
- `x2` (integer, required) X coordinate of the opposite corner.
- `y1` (integer, required) Y coordinate of the first corner.
- `y2` (integer, required) Y coordinate of the opposite corner.

Returns `from`, `to`.

### `build_road_depot`

Build a road depot at a tile, entered from the neighbour picked by direction. Road vehicles are built and serviced here.

Supply one of: `tile` or `x` and `y`.

- `direction` (integer, default 0) Which neighbouring tile the vehicle enters from: 0 is +x, 1 is +y, 2 is -x, 3 is -y. Any other value means the tile itself.
- `road_type` (integer, default 0) Which road technology to build with. Numbered by the running game, so ask get_road_types. Tram tracks are road types too.
- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns `tile`, `x`, `y`.

### `build_road_stop`

Build a bus or truck stop. A drive-through stop sits on the road and is passed through; a bay is entered and reversed out of, which is slower but takes less room.

Supply one of: `tile` or `x` and `y`.

- `direction` (integer, default 0) Which neighbouring tile the vehicle enters from: 0 is +x, 1 is +y, 2 is -x, 3 is -y. Any other value means the tile itself.
- `is_drive_through` (boolean, default false) Build a drive-through stop, which vehicles pass through, rather than a bay they reverse out of.
- `is_truck_stop` (boolean, default false) Build for freight rather than passengers.
- `road_type` (integer, default 0) Which road technology to build with. Numbered by the running game, so ask get_road_types. Tram tracks are road types too.
- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns `station_id`, `tile`, `type`, `x`, `y`.

### `connect_road`

Build road between two tiles, finding the route itself. It succeeds only if every segment was laid, because one gap means no route. A partial build keeps whatever it managed and reports which segments failed, so read the status rather than taking a reply as a working road.

Supply one of: `tile_from` or `from_x` and `from_y`.

Supply one of: `tile_to` or `to_x` and `to_y`.

- `from_x` (integer, optional) X coordinate of the starting tile.
- `from_y` (integer, optional) Y coordinate of the starting tile.
- `max_iterations` (integer, default 50000) How hard the pathfinder may try before giving up. Raising it costs time, not money.
- `road_type` (integer, default 0) Which road technology to build with. Numbered by the running game, so ask get_road_types. Tram tracks are road types too.
- `tile_from` (integer, optional) Tile index to start from. An alternative to from_x and from_y.
- `tile_to` (integer, optional) Tile index to finish at. An alternative to to_x and to_y.
- `to_x` (integer, optional) X coordinate of the finishing tile.
- `to_y` (integer, optional) Y coordinate of the finishing tile.

Returns `built`, `existing`, `failed`, `gaps`, `iterations`, `path`, `path_length`, `status`.

### `convert_road_type`

Convert existing road in a rectangle to another road type.

- `road_type` (integer, required) Which road technology to build with. Numbered by the running game, so ask get_road_types. Tram tracks are road types too.
- `x1` (integer, required) X coordinate of the first corner.
- `x2` (integer, required) X coordinate of the opposite corner.
- `y1` (integer, required) Y coordinate of the first corner.
- `y2` (integer, required) Y coordinate of the opposite corner.

Returns `road_type`.

### `remove_road`

Remove road along a line between two tiles.

Supply one of: `tile_from` or `from_x` and `from_y`.

Supply one of: `tile_to` or `to_x` and `to_y`.

- `from_x` (integer, optional) X coordinate of the starting tile.
- `from_y` (integer, optional) Y coordinate of the starting tile.
- `road_type` (integer, default 0) Which road technology to build with. Numbered by the running game, so ask get_road_types. Tram tracks are road types too.
- `tile_from` (integer, optional) Tile index to start from. An alternative to from_x and from_y.
- `tile_to` (integer, optional) Tile index to finish at. An alternative to to_x and to_y.
- `to_x` (integer, optional) X coordinate of the finishing tile.
- `to_y` (integer, optional) Y coordinate of the finishing tile.

Returns `from_tile`, `to_tile`.

### `remove_road_depot`

Remove a road depot.

Supply one of: `tile` or `x` and `y`.

- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns `tile`.

### `remove_road_stop`

Remove a bus or truck stop.

Supply one of: `tile` or `x` and `y`.

- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns `tile`.

## sign

### `build_sign`

Place a named sign on a tile. Signs are annotation only and affect nothing in the game.

Supply one of: `tile` or `x` and `y`.

- `name` (string, required) A name to give.
- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns `name`, `sign_id`.

### `remove_sign`

Remove a sign.

- `sign_id` (integer, required) Which sign.

Returns no data beyond success.

## town

### `perform_town_action`

Do something for a town: advertise, fund buildings, rebuild its roads, build a statue, buy exclusive rights, or bribe it. Each costs money and most raise the town's opinion of you. Not every action is available in every town, and that is refused rather than charged for.

- `action` (string, required) The action to run.
- `town_id` (integer, required) Which town.

`action` accepts (GSTown): `TOWN_ACTION_ADVERTISE_LARGE` = 2, `TOWN_ACTION_ADVERTISE_MEDIUM` = 1, `TOWN_ACTION_ADVERTISE_SMALL` = 0, `TOWN_ACTION_BRIBE` = 7, `TOWN_ACTION_BUILD_STATUE` = 4, `TOWN_ACTION_BUY_RIGHTS` = 6, `TOWN_ACTION_FUND_BUILDINGS` = 5, `TOWN_ACTION_ROAD_REBUILD` = 3

Returns `action`, `town_id`.

## vehicle

### `build_train`

Build a locomotive in a depot and optionally couple wagons to it. Wagons that cannot be attached are sold again rather than left loose, and the reply reports how many were attached.

Supply one of: `depot_tile` or `depot_x` and `depot_y`.

Supply one of: `depot_tile` or `depot_x` and `depot_y`.

- `cargo_id` (integer, optional) Which cargo. Numbered by the running game, so ask get_cargo_types rather than assuming.
- `depot_tile` (integer, optional) Tile index of the depot the vehicle is built in.
- `depot_x` (integer, optional) X coordinate of the depot the vehicle is built in.
- `depot_y` (integer, optional) Y coordinate of the depot the vehicle is built in.
- `engine_id` (integer, required) Which engine model to build. Numbered by the running game and gated by year, so ask get_engines.
- `num_wagons` (integer, default 1) How many wagons to build and couple on.
- `wagon_id` (integer, optional) Which wagon model to build and couple on.

Returns `capacity_by_cargo`, `carries_one_cargo`, `name`, `refitted`, `vehicle_id`, `wagons_attached`, `wagons_failed`.

### `buy_vehicle`

Build a vehicle of any type in a depot. It starts stopped, so it needs orders and a start before it does anything.

Supply one of: `depot_tile` or `depot_x` and `depot_y`.

Supply one of: `depot_tile` or `depot_x` and `depot_y`.

- `depot_tile` (integer, optional) Tile index of the depot the vehicle is built in.
- `depot_x` (integer, optional) X coordinate of the depot the vehicle is built in.
- `depot_y` (integer, optional) Y coordinate of the depot the vehicle is built in.
- `engine_id` (integer, required) Which engine model to build. Numbered by the running game and gated by year, so ask get_engines.

Returns `name`, `vehicle_id`.

### `clone_vehicle`

Build a copy of an existing vehicle, optionally sharing the original's orders. Give depot_tile or depot_x and depot_y to say which depot builds the copy; without them the vehicle's current tile is used, which only works while it is parked in a depot.

Supply one of: `depot_tile` or `depot_x` and `depot_y`.

- `depot_tile` (integer, optional) Tile index of the depot the vehicle is built in.
- `depot_x` (integer, optional) X coordinate of the depot the vehicle is built in.
- `depot_y` (integer, optional) Y coordinate of the depot the vehicle is built in.
- `share_orders` (boolean, default true) Share the original's order list rather than taking a copy. Shared orders change together afterwards.
- `vehicle_id` (integer, required) Which vehicle.

Returns `name`, `vehicle_id`.

### `move_wagon`

Move a wagon from one train to another. Both must be stopped in a depot.

- `dest_vehicle_id` (integer, required) The vehicle the wagon is moved to.
- `dest_wagon` (integer, required) Position in the destination vehicle to attach at. Use -1 for the end of the chain.
- `move_chain` (boolean, default false) Move the wagon and everything coupled behind it, rather than that wagon alone.
- `source_vehicle_id` (integer, required) The vehicle the wagon is taken from.
- `source_wagon` (integer, required) Position of the wagon within the source vehicle, counting from 0.

Returns no data beyond success.

### `refit_vehicle`

Convert a vehicle to carry a different cargo. It must be stopped in a depot, and not every vehicle can carry everything.

Supply one of: `cargo_id` or `cargo_type`.

- `cargo_id` (integer, optional) Which cargo. Numbered by the running game, so ask get_cargo_types rather than assuming.
- `cargo_type` (integer, optional) Which cargo. Numbered by the running game, so ask get_cargo_types rather than assuming.
- `vehicle_id` (integer, required) Which vehicle.

Returns no data beyond success.

### `rename_vehicle`

Rename a vehicle.

- `name` (string, required) A name to give.
- `vehicle_id` (integer, required) Which vehicle.

Returns `name`, `vehicle_id`.

### `reverse_vehicle`

Turn a vehicle around.

- `vehicle_id` (integer, required) Which vehicle.

Returns no data beyond success.

### `sell_vehicle`

Sell a vehicle. It must be stopped in a depot.

- `vehicle_id` (integer, required) Which vehicle.

Returns no data beyond success.

### `sell_wagon`

Sell one wagon from a train, or that wagon and everything behind it. The train must be stopped in a depot.

- `sell_chain` (boolean, default false) Sell the wagon and everything coupled behind it, rather than that wagon alone.
- `vehicle_id` (integer, required) Which vehicle.
- `wagon` (integer, required) Position of the wagon within the vehicle, counting from 0.

Returns no data beyond success.

### `send_to_depot`

Order a vehicle to the nearest depot and stop there. It finishes the current leg first.

- `vehicle_id` (integer, required) Which vehicle.

Returns no data beyond success.

### `send_to_depot_service`

Order a vehicle to the nearest depot for servicing, after which it resumes its orders rather than waiting.

- `vehicle_id` (integer, required) Which vehicle.

Returns no data beyond success.

### `start_vehicle`

Start a stopped vehicle. A newly built vehicle is stopped until this is called.

- `vehicle_id` (integer, required) Which vehicle.

Returns `already_running`, `running`.

### `stop_vehicle`

Stop a vehicle where it is. Stopping outside a depot blocks the line behind it, and only a vehicle stopped in a depot can be sold or refitted.

- `vehicle_id` (integer, required) Which vehicle.

Returns `already_stopped`.

