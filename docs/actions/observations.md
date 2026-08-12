# Observations

Read the world. These cost nothing, change nothing, and can be repeated freely.

**These are queries, and they are not submitted as actions.** Ask one with `POST /state/gs/query`, body `{"action": "get_stations", "params": {}}`. Submitting one as an action is refused, because a query endpoint that also executed actions would be a way around the action allowlist, and that hole was real: `set_max_loan` once raised a scored company's credit ceiling from 300,000 to 9,000,000 through it.

The distinction is worth reading once rather than discovering. An agent that submitted `get_hangars` as an action spent two of its five actions on it, never found its hangar, and could then not buy the aircraft it was for.

**Generated. Do not edit.** Run `uv run python scripts/generate_action_manifest.py`.
Part of the [action reference](../action_reference.md). 45 of 131 actions.

## Contents

- **query**: `find_airport_spots`, `find_bus_stop_spots`, `find_depot_spots`, `find_dock_spots`, `find_flat_spots`, `find_rail_depot_spot`, `find_station_spot`, `find_water_depot_spots`, `get_airport_types`, `get_bridge_types`, `get_cargo_flows`, `get_cargo_income`, `get_cargo_types`, `get_clients`, `get_companies`, `get_company_finance`, `get_date`, `get_engine_details`, `get_engines`, `get_expense_breakdown`, `get_game_settings`, `get_groups`, `get_hangars`, `get_industries`, `get_industry_info`, `get_infrastructure_costs`, `get_map_size`, `get_map_terrain`, `get_orders`, `get_rail_types`, `get_road_types`, `get_signs`, `get_station_info`, `get_stations`, `get_subsidies`, `get_tile_area`, `get_tile_info`, `get_town_info`, `get_town_rating`, `get_towns`, `get_vehicle_info`, `get_vehicles`, `get_waypoints`, `ping`, `scan_town_area`

Every action on one line, across all three pages: [index.md](index.md).

## query

### `find_airport_spots`

Search near a town for places an airport of the given type would fit.

- `airport_type` (integer, default 0) Which airport layout to build. Availability depends on the year and the map.
- `max_results` (integer, default 5) How many results to return at most.
- `radius` (integer, default 20) How far from the centre tile to search, in tiles.
- `town_id` (integer, required) Which town.

`airport_type` accepts (GSAirport): `AT_COMMUTER` = 5, `AT_HELIDEPOT` = 6, `AT_HELIPORT` = 2, `AT_HELISTATION` = 8, `AT_INTERCON` = 7, `AT_INTERNATIONAL` = 4, `AT_LARGE` = 1, `AT_METROPOLITAN` = 3, `AT_SMALL` = 0

### `find_bus_stop_spots`

Search near a town for roadside tiles a bus or truck stop could be built on.

- `is_truck_stop` (boolean, default false) Build for freight rather than passengers.
- `max_results` (integer, default 10) How many results to return at most.
- `radius` (integer, default 15) How far from the centre tile to search, in tiles.
- `road_type` (integer, default 0) Which road technology to build with. Numbered by the running game, so ask get_road_types. Tram tracks are road types too.
- `town_id` (integer, required) Which town.

### `find_depot_spots`

Search near a town for places a road depot would fit.

- `max_results` (integer, default 5) How many results to return at most.
- `radius` (integer, default 15) How far from the centre tile to search, in tiles.
- `road_type` (integer, default 0) Which road technology to build with. Numbered by the running game, so ask get_road_types. Tram tracks are road types too.
- `town_id` (integer, required) Which town.

### `find_dock_spots`

Search near a town for coastal tiles a dock could be built on.

- `max_results` (integer, default 5) How many results to return at most.
- `radius` (integer, default 20) How far from the centre tile to search, in tiles.
- `town_id` (integer, required) Which town.

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

### `find_rail_depot_spot`

Find a tile near the given one where a rail depot would fit.

- `max_results` (integer, default 5) How many results to return at most.
- `radius` (integer, default 10) How far from the centre tile to search, in tiles.
- `rail_type` (integer, default 0) Which rail technology to build with. Numbered by the running game and gated by year, so ask get_rail_types.
- `tile` (integer, required) Tile index. Takes precedence over x and y when both are given.

### `find_station_spot`

Find somewhere to put a station serving a given industry or town.

- `industry_id` (integer, optional) Which industry.
- `max_results` (integer, default 5) How many results to return at most.
- `platform_length` (integer, default 3) How many tiles long each platform is. A train longer than its platform will not load fully.
- `radius` (integer, default 15) How far from the centre tile to search, in tiles.
- `rail_type` (integer, default 0) Which rail technology to build with. Numbered by the running game and gated by year, so ask get_rail_types.
- `town_id` (integer, optional) Which town.

### `find_water_depot_spots`

Search near a town for water a ship depot could be built on.

Supply one of: `tile` or `x` and `y`.

- `max_results` (integer, default 5) How many results to return at most.
- `radius` (integer, default 20) How far from the centre tile to search, in tiles.
- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `town_id` (integer, optional) Which town.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

### `get_airport_types`

List the airport types this game has, with their sizes and whether they are available yet.

Takes no parameters.

### `get_bridge_types`

List the bridge designs available, with their speed limits, maximum spans and costs.

Takes no parameters.

### `get_cargo_flows`

Report how much cargo your company has picked up and delivered per town and industry since the monitors were last read. Reading resets the counters unless keep_monitoring is set, so two reads in a row report different things.

- `keep_monitoring` (boolean, default true) Leave the cargo monitors armed. Reading a monitor resets it, so a report covers only what moved since the last read.

### `get_cargo_income`

Ask the game what it pays to carry one unit of a cargo a given distance in a given number of days. Payment falls off with time in transit, so a slower route earns less for the same haul. This is the game's own figure, not a model of it.

- `cargo_id` (integer, required) Which cargo. Numbered by the running game, so ask get_cargo_types rather than assuming.
- `days_in_transit` (integer, default this._DEFAULT_TRANSIT_DAYS) How many days the cargo spends travelling. Defaults to 20, a mid length haul, so that corridors compared without it are compared on the same assumption.
- `distance` (integer, required) How far the cargo travels, in tiles. Manhattan distance between the two stations is what the game measures, which /state/routes already reports for every candidate.

### `get_cargo_types`

List the cargoes this game has, with their labels and ids.

Takes no parameters.

### `get_clients`

List the clients connected to the server.

Takes no parameters.

### `get_companies`

List the companies in the game, with their names, values and performance ratings.

Takes no parameters.

### `get_company_finance`

Report your company's money, loan, income, expenses and value.

Takes no parameters.

### `get_date`

Report the current in-game date.

Takes no parameters.

### `get_engine_details`

Report everything about one engine model: capacity, speed, power, running cost, reliability and what it can carry.

- `engine_id` (integer, required) Which engine model to build. Numbered by the running game and gated by year, so ask get_engines.

### `get_engines`

List engine models that can be bought now. What is available changes with the year, so this is worth re-reading rather than caching for the whole game.

- `vehicle_type` (string, default "train") One of train, road, ship or aircraft. The integers 0 to 3 mean the same, in that order.

### `get_expense_breakdown`

Report income and costs split by category, which is where a fleet that runs at a loss becomes visible.

Takes no parameters.

### `get_game_settings`

Read named game settings. An unknown name reads back as null rather than failing the call.

- `keys` (array, required) Names of game settings to read. An unknown name reads back as null rather than failing the call.

### `get_groups`

List your vehicle groups, with their profits and how they nest.

Takes no parameters.

### `get_hangars`

List the hangar tiles of an airport, which is where aircraft are built and serviced.

Takes no parameters.

### `get_industries`

List the industries on the map, with their locations, types and production.

Takes no parameters.

### `get_industry_info`

Report one industry in detail: what it produces and accepts, recent production, and how much is waiting.

- `industry_id` (integer, required) Which industry.

### `get_infrastructure_costs`

Report how much track, road and station you own and what it costs to maintain each month.

Takes no parameters.

### `get_map_size`

Report the map dimensions in tiles.

Takes no parameters.

### `get_map_terrain`

Report terrain across a band of the map: height, slope, and whether each tile is water, coast or buildable. Bounded by max_tiles at every map size, and the reply says whether it was cut short and where to resume, so a band that did not fit is never mistaken for the whole answer. Reading a whole map is not a reasonable request: 256x256 is over half a megabyte. Where something will actually fit is better asked of the find_ family, which dry-runs the real build inside the game.

- `from_y` (integer, default 1) Y coordinate of the starting tile.
- `max_tiles` (integer, default 4000) How many tiles to report at most. Guards against asking for more than a reply can carry.
- `occupancy` (boolean, default false) Also report what is built on each tile: the rail, road, station, tree, bridge and tunnel bits in flags, plus the tile owner. Off by default because it costs seven extra reads per tile, and a large band of them slows the game enough that other commands time out.
- `to_y` (integer, default max_y) Y coordinate of the finishing tile.

### `get_orders`

List a vehicle's orders, with their destinations and flags.

- `vehicle_id` (integer, required) Which vehicle.

### `get_rail_types`

List the rail technologies this game has and which are available yet.

Takes no parameters.

### `get_road_types`

List the road technologies this game has, tram tracks included, and which are available yet.

Takes no parameters.

### `get_signs`

List the signs on the map.

Takes no parameters.

### `get_station_info`

Report one station in detail: what is waiting, what it accepts, and its cargo ratings.

- `station_id` (integer, required) Which station.

### `get_stations`

List your stations, with what is waiting at each and how it is rated.

Takes no parameters.

### `get_subsidies`

List the subsidies on offer and those already awarded.

Takes no parameters.

### `get_tile_area`

Report height, slope and buildability across a rectangle. max_tiles bounds the reply.

- `max_tiles` (integer, default 400) How many tiles to report at most. Guards against asking for more than a reply can carry.
- `x1` (integer, required) X coordinate of the first corner.
- `x2` (integer, required) X coordinate of the opposite corner.
- `y1` (integer, required) Y coordinate of the first corner.
- `y2` (integer, required) Y coordinate of the opposite corner.

### `get_tile_info`

Report one tile in detail: height, slope, what is on it, who owns it and which town it belongs to.

Supply one of: `tile` or `x` and `y`.

- `tile` (integer, optional) Tile index. Takes precedence over x and y when both are given.
- `x` (integer, optional) X coordinate on the map, counting from 0.
- `y` (integer, optional) Y coordinate on the map, counting from 0.

### `get_town_info`

Report one town in detail: population, houses, what it accepts and how fast it is growing.

- `town_id` (integer, required) Which town.

### `get_town_rating`

Report how a town regards your company. A poor rating blocks building there, and planting trees is the usual remedy.

- `town_id` (integer, required) Which town.

### `get_towns`

List the towns on the map, with their locations and populations.

Takes no parameters.

### `get_vehicle_info`

Report one vehicle in detail: where it is, what it carries, its orders, age, reliability and profit.

- `vehicle_id` (integer, required) Which vehicle.

### `get_vehicles`

List your vehicles, optionally of one type only, with their positions, cargo and orders.

- `vehicle_type` (string, default null) One of train, road, ship or aircraft. The integers 0 to 3 mean the same, in that order.

### `get_waypoints`

List your waypoints.

Takes no parameters.

### `ping`

Check that the GameScript is answering. Costs nothing and changes nothing.

Takes no parameters.

### `scan_town_area`

Report the land around a town: what is buildable, what is already built, and where the roads run.

- `radius` (integer, default 15) How far from the centre tile to search, in tiles.
- `town_id` (integer, required) Which town.

