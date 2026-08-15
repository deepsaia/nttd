# Observations

Read the world. These cost nothing, change nothing, and can be repeated freely.

**These are queries, and they are not submitted as actions.** Ask one with `POST /state/gs/query?action=get_stations`, with the parameters as the whole body: `{"industry_id": 7}`, or `{}` for a query that takes none. The action name is a QUERY STRING parameter, not a body field, and putting it in the body returns 422. Submitting one as an action is refused, because a query endpoint that also executed actions would be a way around the action allowlist, and that hole was real: `set_max_loan` once raised a scored company's credit ceiling from 300,000 to 9,000,000 through it.

The distinction is worth reading once rather than discovering. An agent that submitted `get_hangars` as an action spent two of its five actions on it, never found its hangar, and could then not buy the aircraft it was for.

**Generated. Do not edit.** Run `uv run python scripts/generate_action_manifest.py`.
Part of the [action reference](../action_reference.md). 46 of 133 actions.

## Contents

- **query**: `find_airport_spots`, `find_bus_stop_spots`, `find_depot_spots`, `find_dock_spots`, `find_flat_spots`, `find_rail_depot_spot`, `find_station_spot`, `find_water_depot_spots`, `get_airport_types`, `get_bridge_types`, `get_cargo_flows`, `get_cargo_income`, `get_cargo_types`, `get_clients`, `get_companies`, `get_company_finance`, `get_date`, `get_engine_details`, `get_engines`, `get_expense_breakdown`, `get_game_settings`, `get_groups`, `get_hangars`, `get_industries`, `get_industry_info`, `get_infrastructure_costs`, `get_map_size`, `get_map_terrain`, `get_orders`, `get_rail_types`, `get_road_types`, `get_signs`, `get_station_info`, `get_stations`, `get_subsidies`, `get_tile_area`, `get_tile_info`, `get_town_info`, `get_town_rating`, `get_towns`, `get_vehicle_info`, `get_vehicles`, `get_waypoints`, `ping`, `scan_town_area`, `trace_route`

Every action on one line, across all three pages: [index.md](index.md).

## query

### `find_airport_spots`

Search near a town for places an airport of the given type would fit.

- `airport_type` (integer, default 0) Which airport layout to build. Availability depends on the year and the map.
- `max_results` (integer, default 5) How many results to return at most.
- `radius` (integer, default 20) How far from the centre tile to search, in tiles.
- `town_id` (integer, required) Which town.

`airport_type` accepts (GSAirport): `AT_COMMUTER` = 5, `AT_HELIDEPOT` = 6, `AT_HELIPORT` = 2, `AT_HELISTATION` = 8, `AT_INTERCON` = 7, `AT_INTERNATIONAL` = 4, `AT_LARGE` = 1, `AT_METROPOLITAN` = 3, `AT_SMALL` = 0

Returns a list of `cargo_acceptance`, `coverage`, `distance`, `height`, `tile`, `width`, `within_coverage`, `x`, `y`.

### `find_bus_stop_spots`

Search near a town for roadside tiles a bus or truck stop could be built on.

- `is_truck_stop` (boolean, default false) Build for freight rather than passengers.
- `max_results` (integer, default 10) How many results to return at most.
- `radius` (integer, default 15) How far from the centre tile to search, in tiles.
- `road_type` (integer, default 0) Which road technology to build with. Numbered by the running game, so ask get_road_types. Tram tracks are road types too.
- `town_id` (integer, required) Which town.

Returns a list of `adjacent_road_count`, `adjacent_road_x`, `adjacent_road_y`, `cargo_acceptance`, `direction`, `distance`, `has_adjacent_road`, `tile`, `x`, `y`.

### `find_depot_spots`

Search near a town for places a road depot would fit.

- `max_results` (integer, default 5) How many results to return at most.
- `radius` (integer, default 15) How far from the centre tile to search, in tiles.
- `road_type` (integer, default 0) Which road technology to build with. Numbered by the running game, so ask get_road_types. Tram tracks are road types too.
- `town_id` (integer, required) Which town.

Returns a list of `adjacent_road_x`, `adjacent_road_y`, `depot_direction`, `distance`, `tile`, `x`, `y`.

### `find_dock_spots`

Search near a town for coastal tiles a dock could be built on.

- `max_results` (integer, default 5) How many results to return at most.
- `radius` (integer, default 20) How far from the centre tile to search, in tiles.
- `town_id` (integer, required) Which town.

Returns a list of `cargo_acceptance`, `distance`, `slope`, `tile`, `x`, `y`.

### `find_flat_spots`

Search around a tile for level ground. With station_test it goes further and checks that a station would really be buildable there, which is slower and worth the cost before committing.

Supply one of: `tile` or `x` and `y`.

- `max_results` (integer, default 10) How many results to return at most.
- `min_size` (integer, default 1) Smallest acceptable square of flat land, in tiles on a side.
- `platform_length` (integer, default 3) How many tiles long each platform is. A train longer than its platform will not load fully.
- `radius` (integer, default 10) How far from the centre tile to search, in tiles.
- `rail_type` (integer, default 0) Which rail technology to build with. Numbered by the running game and gated by year, so ask get_rail_types.
- `required_cargo` (integer, default null) Only report spots where a station would accept or produce this cargo.
- `station_test` (boolean, default false) Check that a station would actually fit and be buildable, rather than only that the land is flat. Slower and more truthful.
- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns a list of `cargo_acceptance`, `distance`, `max_height`, `tile`, `x`, `y`.

### `find_rail_depot_spot`

Find a tile near the given one where a rail depot would fit.

Supply one of: `tile` or `x` and `y`.

- `max_results` (integer, default 5) How many results to return at most.
- `radius` (integer, default 10) How far from the centre tile to search, in tiles.
- `rail_type` (integer, default 0) Which rail technology to build with. Numbered by the running game and gated by year, so ask get_rail_types.
- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `town_id` (integer, optional) Which town.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns a list of `adjacent_track_x`, `adjacent_track_y`, `depot_direction`, `distance`, `tile`, `x`, `y`.

### `find_station_spot`

Find somewhere to put a station serving a given industry or town.

- `industry_id` (integer, optional) Which industry.
- `max_results` (integer, default 5) How many results to return at most.
- `platform_length` (integer, default 3) How many tiles long each platform is. A train longer than its platform will not load fully.
- `radius` (integer, default 15) How far from the centre tile to search, in tiles.
- `rail_type` (integer, default 0) Which rail technology to build with. Numbered by the running game and gated by year, so ask get_rail_types.
- `town_id` (integer, optional) Which town.

Returns `cargo_labels`, `spots`, `target_name`, `target_x`, `target_y`.

Each `spots` carries `cargo_acceptance`, `distance`, `max_height`, `reachable_directions`, `tile`, `valid_directions`, `x`, `y`.

### `find_water_depot_spots`

Search near a town for water a ship depot could be built on.

Supply one of: `tile` or `x` and `y`.

- `max_results` (integer, default 5) How many results to return at most.
- `radius` (integer, default 20) How far from the centre tile to search, in tiles.
- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `town_id` (integer, optional) Which town.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns a list of `depot_direction`, `distance`, `tile`, `x`, `y`.

### `get_airport_types`

List the airport types this game has, with their sizes and whether they are available yet.

Takes no parameters.

Returns a list of `coverage`, `height`, `id`, `width`.

### `get_bridge_types`

List the bridge designs available, with their speed limits, maximum spans and costs.

Takes no parameters.

Returns a list of `id`, `max_length`, `max_speed`, `min_length`, `name`, `price`.

### `get_cargo_flows`

Report how much cargo your company has picked up and delivered per town and industry since the monitors were last read. Reading resets the counters unless keep_monitoring is set, so two reads in a row report different things.

- `keep_monitoring` (boolean, default true) Leave the cargo monitors armed. Reading a monitor resets it, so a report covers only what moved since the last read.

Returns a list of `amount`, `cargo_id`, `cargo_label`, `direction`, `entity_id`, `entity_name`, `entity_type`.

### `get_cargo_income`

Ask the game what it pays to carry one unit of a cargo a given distance in a given number of days. Payment falls off with time in transit, so a slower route earns less for the same haul. This is the game's own figure, not a model of it.

- `cargo_id` (integer, required) Which cargo. Numbered by the running game, so ask get_cargo_types rather than assuming.
- `days_in_transit` (integer, default this._DEFAULT_TRANSIT_DAYS) How many days the cargo spends travelling. Defaults to 20, a mid length haul, so that corridors compared without it are compared on the same assumption.
- `distance` (integer, required) How far the cargo travels, in tiles. Manhattan distance between the two stations is what the game measures, which /state/routes already reports for every candidate.

Returns `cargo_id`, `days_in_transit`, `distance`, `income_per_100_units`, `income_per_unit`, `label`.

### `get_cargo_types`

List the cargoes this game has, with their labels and ids.

Takes no parameters.

Returns a list of `id`, `is_freight`, `label`, `name`.

### `get_clients`

List the clients connected to the server.

Takes no parameters.

Returns a list of `client_id`, `company_id`, `name`.

### `get_companies`

List the companies in the game, with their names, values and performance ratings.

Takes no parameters.

Returns a list of `cargo_delivered_total`, `company_value`, `hq_x`, `hq_y`, `id`, `loan`, `max_loan`, `money`, `name`, `performance_rating`, `q0_cargo`, `q0_expenses`, `q0_income`, `q1_cargo`.

### `get_company_finance`

Report your company's money, loan, income, expenses and value.

Takes no parameters.

Returns `balance`, `company_id`, `loan`, `max_loan`, `q1_expenses`, `q1_income`, `q1_value`, `q2_expenses`, `q2_income`, `q2_value`.

### `get_date`

Report the current in-game date.

Takes no parameters.

Returns `date`, `day`, `month`, `year`.

### `get_engine_details`

Report everything about one engine model: capacity, speed, power, running cost, reliability and what it can carry.

- `engine_id` (integer, required) Which engine model to build. Numbered by the running game and gated by year, so ask get_engines.

Returns `can_refit`, `capacity`, `cargo_type`, `engine_id`, `max_age`, `max_speed`, `max_tractive_effort`, `name`, `plane_type`, `power`, `price`, `rail_type`, `reliability`, `road_type`, `running_cost`, `vehicle_type`, `weight`.

### `get_engines`

List engine models that can be bought now. What is available changes with the year, so this is worth re-reading rather than caching for the whole game.

- `vehicle_type` (string, default "train") One of train, road, ship or aircraft. The integers 0 to 3 mean the same, in that order.

Returns a list of `capacity`, `cargo_label`, `cargo_type`, `id`, `is_wagon`, `max_speed`, `name`, `plane_type`, `power`, `price`, `rail_type`, `reliability`, `running_cost`, `weight`.

### `get_expense_breakdown`

Report income and costs split by category, which is where a fleet that runs at a loss becomes visible.

Takes no parameters.

Returns `balance`, `company_id`, `quarterly`.

Each `quarterly` carries `cargo_delivered`, `company_value`, `expenses`, `income`, `performance_rating`, `quarter`.

### `get_game_settings`

Read named game settings. An unknown name reads back as null rather than failing the call.

- `keys` (array, required) Names of game settings to read. An unknown name reads back as null rather than failing the call.

Returns no data beyond success.

### `get_groups`

List your vehicle groups, with their profits and how they nest.

Takes no parameters.

Returns a list of `id`, `name`, `parent_id`, `profit_last_year`, `profit_this_year`, `vehicle_type`.

### `get_hangars`

List the hangar tiles of an airport, which is where aircraft are built and serviced.

Takes no parameters.

Returns a list of `airport_type`, `airport_x`, `airport_y`, `hangar_tile`, `hangar_x`, `hangar_y`, `station_id`, `station_name`.

### `get_industries`

List the industries on the map, with their locations, types and production.

Takes no parameters.

Returns a list of `accepted`, `accepts_cargo`, `id`, `is_processing`, `is_raw`, `name`, `produces_cargo`, `production`, `served_by`, `type_id`, `type_name`, `x`, `y`.

### `get_industry_info`

Report one industry in detail: what it produces and accepts, recent production, and how much is waiting.

- `industry_id` (integer, required) Which industry.

Returns `accepted`, `accepts_cargo`, `id`, `is_processing`, `is_raw`, `name`, `produces_cargo`, `production`, `type_id`, `type_name`, `x`, `y`.

Each `accepted` carries `cargo_id`, `cargo_label`, `stockpile`.

### `get_infrastructure_costs`

Report how much track, road and station you own and what it costs to maintain each month.

Takes no parameters.

Returns `airport_cost`, `airport_pieces`, `company_id`, `rail_cost`, `rail_pieces`, `road_cost`, `road_pieces`, `station_cost`, `station_pieces`, `water_cost`, `water_pieces`.

### `get_map_size`

Report the map dimensions in tiles.

Takes no parameters.

Returns `max_x`, `max_y`, `size_x`, `size_y`.

### `get_map_terrain`

Report terrain across a band of the map: height, slope, and whether each tile is water, coast or buildable. Bounded by max_tiles at every map size, and the reply says whether it was cut short and where to resume. With occupancy, each tile's flags also carry what is built on it, as bits: 1 water, 2 coast, 4 buildable, 8 rail, 16 road, 32 station, 64 trees, 128 bridge, 256 tunnel, 512 rail RUNNING LINE, 1024 road running line, 2048 depot. A station platform sets the rail or road bit too, so 8 and 16 answer "is there track here" with yes for a platform; 512 and 1024 are track a vehicle can run along and nothing else, which is what a depot has to be joined to.

- `from_y` (integer, default 1) Y coordinate of the starting tile.
- `max_tiles` (integer, default 4000) How many tiles to report at most. Guards against asking for more than a reply can carry.
- `occupancy` (boolean, default false) Also report what is built on each tile: the rail, road, station, tree, bridge and tunnel bits in flags, plus the tile owner. Off by default because it costs seven extra reads per tile, and a large band of them slows the game enough that other commands time out.
- `to_y` (integer, default max_y) Y coordinate of the finishing tile.

Returns `from_y`, `next_from_y`, `rows`, `tiles_returned`, `to_y`, `truncated`.

Each `rows` carries `tiles`, `y`.

### `get_orders`

List a vehicle's orders, with their destinations and flags.

- `vehicle_id` (integer, required) Which vehicle.

Returns `order_count`, `orders`, `vehicle_id`.

Each `orders` carries `destination`, `flags`, `index`, `is_conditional`, `is_goto_depot`, `is_goto_station`, `is_goto_waypoint`.

### `get_rail_types`

List the rail technologies this game has and which are available yet.

Takes no parameters.

Returns a list of `available`, `build_cost_per_tile`, `id`, `name`.

### `get_road_types`

List the road technologies this game has, tram tracks included, and which are available yet.

Takes no parameters.

Returns a list of `id`, `is_tram`, `name`.

### `get_signs`

List the signs on the map.

Takes no parameters.

Returns a list of `id`, `name`, `x`, `y`.

### `get_station_info`

Report one station in detail: what is waiting, what it accepts, and its cargo ratings.

- `station_id` (integer, required) Which station.

Returns `cargo_waiting`, `entry_tiles`, `has_airport`, `has_bus`, `has_dock`, `has_rail`, `has_truck`, `id`, `name`, `platform_axis`, `x`, `y`.

Each `cargo_waiting` carries `cargo_id`, `cargo_label`, `rating`, `waiting`.
Each `entry_tiles` carries `enterable`, `has_rail`, `tile`, `usable`, `x`, `y`.

### `get_stations`

List your stations, with what is waiting at each and how it is rated.

Takes no parameters.

Returns a list of `cargo_acceptance`, `cargo_waiting`, `has_airport`, `has_bus`, `has_dock`, `has_rail`, `has_truck`, `id`, `name`, `x`, `y`.

### `get_subsidies`

List the subsidies on offer and those already awarded.

Takes no parameters.

Returns a list of `cargo_type`, `destination_index`, `destination_type`, `id`, `is_awarded`, `remaining`, `source_index`, `source_type`.

### `get_tile_area`

Report a rectangle of ground, tile by tile: height, slope, whether it is buildable, water or coast, whether it already carries road, rail, a station, a tree, a bridge or a tunnel, and who owns it. This is the right tool for almost any question about a piece of ground, including whether your own track is already there. Bounds are INCLUSIVE, so a single tile is x1 equal to x2. max_tiles bounds the reply and the request is REFUSED, not truncated, if the area exceeds it; the default is 400.

- `max_tiles` (integer, default 400) How many tiles to report at most. Guards against asking for more than a reply can carry.
- `x1` (integer, required) X coordinate of the first corner.
- `x2` (integer, required) X coordinate of the opposite corner.
- `y1` (integer, required) Y coordinate of the first corner.
- `y2` (integer, required) Y coordinate of the opposite corner.

Returns a list of `buildable`, `coast`, `has_rail`, `has_road`, `has_tree`, `height`, `is_bridge`, `is_station`, `is_tunnel`, `owner`, `slope`, `water`, `x`, `y`.

### `get_tile_info`

Report one tile in detail: height, slope, what is on it, who owns it and which town it belongs to.

Supply one of: `tile` or `x` and `y`.

- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

Returns `has_tree`, `height`, `is_bridge`, `is_buildable`, `is_coast`, `is_rail`, `is_road`, `is_station`, `is_tunnel`, `is_water`, `min_height`, `other_end`, `owner`, `slope`, `x`, `y`.

### `get_town_info`

Report one town in detail: population, houses, what it accepts and how fast it is growing.

- `town_id` (integer, required) Which town.

Returns `accepts_cargo`, `exclusive_rights_company`, `exclusive_rights_duration`, `fund_buildings_duration`, `growth_rate`, `has_statue`, `houses`, `id`, `is_city`, `name`, `population`, `produces_cargo`, `road_layout`, `x`, `y`.

### `get_town_rating`

Report how a town regards your company. A poor rating blocks building there, and planting trees is the usual remedy.

- `town_id` (integer, required) Which town.

Returns `company_id`, `detailed_rating`, `rating`, `town_id`.

### `get_towns`

List the towns on the map, with their locations and populations.

Takes no parameters.

Returns a list of `id`, `name`, `population`, `x`, `y`.

### `get_vehicle_info`

Report one vehicle in detail: where it is, what it carries, its orders, age, reliability and profit.

- `vehicle_id` (integer, required) Which vehicle.

Returns `age`, `age_left`, `cargo`, `current_speed`, `engine_id`, `has_shared_orders`, `id`, `idle_reason`, `in_depot`, `is_articulated`, `length`, `lost`, `max_age`, `name`, `orders`, `profit_last_year`, `profit_this_year`, `state`, `type`, `x`, `y`.

Each `orders` carries `destination`, `flags`, `index`, `is_conditional`, `is_goto_depot`, `is_goto_station`, `is_goto_waypoint`.

### `get_vehicles`

List your vehicles, optionally of one type only, with their positions, cargo and orders.

- `vehicle_type` (string, default null) One of train, road, ship or aircraft. The integers 0 to 3 mean the same, in that order.

Returns a list of `age`, `capacity`, `current_speed`, `engine_id`, `id`, `in_depot`, `is_articulated`, `max_age`, `name`, `order_count`, `orders`, `profit_last_year`, `profit_this_year`, `running`, `running_cost`, `state`, `type`, `x`, `y`.

### `get_waypoints`

List your waypoints.

Takes no parameters.

Returns a list of `id`, `is_buoy`, `is_rail`, `name`, `x`, `y`.

### `ping`

Check that the GameScript is answering. Costs nothing and changes nothing.

Takes no parameters.

### `scan_town_area`

Report the land around a town: what is buildable, what is already built, and where the roads run.

- `radius` (integer, default 15) How far from the centre tile to search, in tiles.
- `town_id` (integer, required) Which town.

Returns `buildable`, `buildings`, `center_x`, `center_y`, `counts`, `radius`, `roads`, `town_name`, `water`.

Each `buildable` carries `height`, `slope`, `x`, `y`.
Each `buildings` carries `x`, `y`.
Each `roads` carries `x`, `y`.
Each `water` carries `x`, `y`.

### `trace_route`

Walk existing track from one point to another and say whether the chain of pieces joins up. Answers rail and road; a ship crosses open water, so a track walk does not describe one. Track geometry IS modelled: each step tests whether a vehicle can come from the previous tile, through this one, and out to the next, so a curve that does not join or track meeting side-on is rejected. What it does NOT model is everything about the endpoints and the vehicle: whether a platform can be entered on the approach axis, whether a train would have to reverse in a dead end, train length against platform length, or signals. So a yes means the track exists, not that a vehicle will run it. The exact answer is only available after dispatch, from `lost` on get_vehicle_info, which is the game's own signal.

Supply one of: `tile_from` or `from_x` and `from_y`.

Supply one of: `tile_to` or `to_x` and `to_y`.

- `from_x` (integer, optional) X coordinate of the starting tile.
- `from_y` (integer, optional) Y coordinate of the starting tile.
- `max_iterations` (integer, default 20000) How hard the pathfinder may try before giving up. Raising it costs time, not money.
- `tile_from` (integer, optional) Tile index to start from. An alternative to from_x and from_y.
- `tile_to` (integer, optional) Tile index to finish at. An alternative to to_x and to_y.
- `to_x` (integer, optional) X coordinate of the finishing tile.
- `to_y` (integer, optional) Y coordinate of the finishing tile.
- `transport_type` (string, default "rail") rail or road. Defaults to rail.

Returns `exhausted`, `from_x`, `from_y`, `line_exists`, `steps`, `tiles_reachable`, `to_x`, `to_y`, `transport_type`.

