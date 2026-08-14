# Every action, one line each

The whole surface at a glance, for choosing what to call. For a parameter's type,
default, and the constants it accepts, follow the link or run
`nttd actions <name>`.

**Generated. Do not edit.** Run `uv run python scripts/generate_action_manifest.py`.

Signatures read: required parameters first, then a choice as `a|b`, then optional
ones in brackets. So `remove_order(vehicle_id, order_index|order_position)` needs
the vehicle and one of the two positions.

## Observations

Full detail in [observations.md](observations.md).

- `find_airport_spots(town_id, [airport_type, max_results, radius])` Search near a town for places an airport of the given type would fit.
- `find_bus_stop_spots(town_id, [is_truck_stop, max_results, radius, road_type])` Search near a town for roadside tiles a bus or truck stop could be built on.
- `find_depot_spots(town_id, [max_results, radius, road_type])` Search near a town for places a road depot would fit.
- `find_dock_spots(town_id, [max_results, radius])` Search near a town for coastal tiles a dock could be built on.
- `find_flat_spots(tile|x,y, [max_results, min_size, platform_length, radius, rail_type, required_cargo, station_test])` Search around a tile for level ground.
- `find_rail_depot_spot(tile|x,y, [max_results, radius, rail_type, town_id])` Find a tile near the given one where a rail depot would fit.
- `find_station_spot([industry_id, max_results, platform_length, radius, rail_type, town_id])` Find somewhere to put a station serving a given industry or town.
- `find_water_depot_spots(tile|x,y, [max_results, radius, town_id])` Search near a town for water a ship depot could be built on.
- `get_airport_types()` List the airport types this game has, with their sizes and whether they are available yet.
- `get_bridge_types()` List the bridge designs available, with their speed limits, maximum spans and costs.
- `get_cargo_flows([keep_monitoring])` Report how much cargo your company has picked up and delivered per town and industry since the monitors were last read.
- `get_cargo_income(cargo_id, distance, [days_in_transit])` Ask the game what it pays to carry one unit of a cargo a given distance in a given number of days.
- `get_cargo_types()` List the cargoes this game has, with their labels and ids.
- `get_clients()` List the clients connected to the server.
- `get_companies()` List the companies in the game, with their names, values and performance ratings.
- `get_company_finance()` Report your company's money, loan, income, expenses and value.
- `get_date()` Report the current in-game date.
- `get_engine_details(engine_id)` Report everything about one engine model: capacity, speed, power, running cost, reliability and what it can carry.
- `get_engines([vehicle_type])` List engine models that can be bought now.
- `get_expense_breakdown()` Report income and costs split by category, which is where a fleet that runs at a loss becomes visible.
- `get_game_settings(keys)` Read named game settings.
- `get_groups()` List your vehicle groups, with their profits and how they nest.
- `get_hangars()` List the hangar tiles of an airport, which is where aircraft are built and serviced.
- `get_industries()` List the industries on the map, with their locations, types and production.
- `get_industry_info(industry_id)` Report one industry in detail: what it produces and accepts, recent production, and how much is waiting.
- `get_infrastructure_costs()` Report how much track, road and station you own and what it costs to maintain each month.
- `get_map_size()` Report the map dimensions in tiles.
- `get_map_terrain([from_y, max_tiles, occupancy, to_y])` Report terrain across a band of the map: height, slope, and whether each tile is water, coast or buildable.
- `get_orders(vehicle_id)` List a vehicle's orders, with their destinations and flags.
- `get_rail_types()` List the rail technologies this game has and which are available yet.
- `get_road_types()` List the road technologies this game has, tram tracks included, and which are available yet.
- `get_signs()` List the signs on the map.
- `get_station_info(station_id)` Report one station in detail: what is waiting, what it accepts, and its cargo ratings.
- `get_stations()` List your stations, with what is waiting at each and how it is rated.
- `get_subsidies()` List the subsidies on offer and those already awarded.
- `get_tile_area(x1, x2, y1, y2, [max_tiles])` Report a rectangle of ground, tile by tile: height, slope, whether it is buildable, water or coast, whether it already carries road, rail, a station, a tree, a bridge or a tunnel, and who owns it.
- `get_tile_info(tile|x,y)` Report one tile in detail: height, slope, what is on it, who owns it and which town it belongs to.
- `get_town_info(town_id)` Report one town in detail: population, houses, what it accepts and how fast it is growing.
- `get_town_rating(town_id)` Report how a town regards your company.
- `get_towns()` List the towns on the map, with their locations and populations.
- `get_vehicle_info(vehicle_id)` Report one vehicle in detail: where it is, what it carries, its orders, age, reliability and profit.
- `get_vehicles([vehicle_type])` List your vehicles, optionally of one type only, with their positions, cargo and orders.
- `get_waypoints()` List your waypoints.
- `ping()` Check that the GameScript is answering.
- `scan_town_area(town_id, [radius])` Report the land around a town: what is buildable, what is already built, and where the roads run.
- `trace_route(tile_from|from_x,from_y, tile_to|to_x,to_y, [max_iterations, transport_type])` Whether a vehicle can travel from one tile to another over track that already exists.

## Actions

Full detail in [actions.md](actions.md).

- `add_order(vehicle_id, station_id|dest_tile|destination, [order_flags])` Append an order to the end of a vehicle's list.
- `build_airport(tile|x,y, [airport_type])` Build an airport with its north corner at the given tile.
- `build_bridge(end_x, end_y, start_x, start_y, [bridge_type, transport_type])` Bridge the gap between two tiles.
- `build_buoy(tile|x,y)` Place a buoy on a water tile.
- `build_canal(tile|x,y)` Turn a flat land tile into canal.
- `build_company_hq(tile|x,y)` Place the company headquarters, which occupies four tiles with its north corner at the given tile.
- `build_dock(tile|x,y)` Build a dock on a coastal tile, giving ships somewhere to load.
- `build_lock(tile|x,y)` Build a lock so ships can change height.
- `build_one_way_road(x1, x2, y1, y2)` Build road between two tiles that may be driven in one direction only, running from the first tile to the second.
- `build_one_way_road_full(x1, x2, y1, y2)` Build one-way road between two tiles, covering both end tiles fully rather than stopping at their edges.
- `build_path(steps, [rail_type, road_type, transport_type])` Lay a route you have already chosen, tile by tile.
- `build_rail_depot(tile|x,y, [direction, rail_type])` Build a rail depot at a tile, entered from the neighbour picked by direction.
- `build_rail_signal(tile|x,y, [signal_type])` Place a signal on a track tile.
- `build_rail_station(tile|x,y, [direction, num_platforms, platform_length, rail_type])` Build a rail station with its north corner at the given tile.
- `build_rail_track(tile|x,y, [rail_type, track])` Lay one track piece on one tile, in a chosen orientation.
- `build_rail_waypoint(tile|x,y)` Build a waypoint on a track tile.
- `build_road_depot(tile|x,y, [direction, road_type])` Build a road depot at a tile, entered from the neighbour picked by direction.
- `build_road_stop(tile|x,y, [direction, is_drive_through, is_truck_stop, road_type])` Build a bus or truck stop.
- `build_sign(name, tile|x,y)` Place a named sign on a tile.
- `build_train(engine_id, depot_tile|depot_x,depot_y, depot_tile|depot_x,depot_y, [cargo_id, num_wagons, wagon_id])` Build a locomotive in a depot and optionally couple wagons to it.
- `build_tunnel(tile|x,y, [transport_type])` Bore a tunnel into the hillside at the given tile.
- `build_water_depot(tile|x,y, [direction])` Build a ship depot on water.
- `buy_vehicle(engine_id, depot_tile|depot_x,depot_y, depot_tile|depot_x,depot_y)` Build a vehicle of any type in a depot.
- `clone_vehicle(vehicle_id, depot_tile|depot_x,depot_y, [share_orders])` Build a copy of an existing vehicle, optionally sharing the original's orders.
- `connect_rail(tile_from|from_x,from_y, tile_to|to_x,to_y, [from_hint_x, from_hint_y, max_iterations, rail_type, to_hint_x, to_hint_y])` Lay track between two tiles, finding the route itself.
- `connect_road(tile_from|from_x,from_y, tile_to|to_x,to_y, [max_iterations, road_type])` Build road between two tiles, finding the route itself.
- `convert_rail(tile|x,y, [rail_type, x1, x2, y1, y2])` Convert existing track in a rectangle to another rail type.
- `convert_road_type(road_type, x1, x2, y1, y2)` Convert existing road in a rectangle to another road type.
- `copy_orders(main_vehicle_id, vehicle_id)` Replace a vehicle's orders with a copy of another's.
- `create_group([parent_group_id, vehicle_type])` Create a group to organise vehicles of one type.
- `delete_group(group_id)` Delete a group.
- `demolish_tile(tile|x,y)` Clear whatever is on the tile.
- `estimate_cost(action, params)` Report what an action would cost without doing it.
- `insert_order(vehicle_id, station_id|dest_tile|destination, order_index|order_position, [order_flags])` Insert an order at a position, pushing later orders down.
- `level_tiles(x1, x2, y1, y2)` Flatten the rectangle between two corners to a single height.
- `lower_tile(slope, tile|x,y)` Lower the named corners of a tile by one step.
- `move_order(vehicle_id, from_index|from_position, to_index|to_position)` Move an order to a different position in the list.
- `move_to_group(group_id, vehicle_id)` Move a vehicle into a group.
- `move_wagon(dest_vehicle_id, dest_wagon, source_vehicle_id, source_wagon, [move_chain])` Move a wagon from one train to another.
- `open_close_airport(station_id)` Toggle an airport between accepting and refusing arrivals.
- `perform_town_action(action, town_id)` Do something for a town: advertise, fund buildings, rebuild its roads, build a statue, buy exclusive rights, or bribe it.
- `plant_tree(tile|x,y)` Plant a tree on a tile.
- `plant_tree_rectangle(height, width, tile|x,y)` Plant trees across a rectangle given as a corner and a size.
- `raise_tile(slope, tile|x,y)` Raise the named corners of a tile by one step.
- `refit_vehicle(vehicle_id, cargo_id|cargo_type)` Convert a vehicle to carry a different cargo.
- `remove_airport(tile|x,y)` Remove an airport, given any tile of it.
- `remove_buoy(tile|x,y)` Remove a buoy.
- `remove_canal(tile|x,y)` Turn a canal tile back into land.
- `remove_lock(tile|x,y)` Remove a lock.
- `remove_order(vehicle_id, order_index|order_position)` Remove one order from a vehicle's list.
- `remove_rail(tile|x,y, tile_from|from_x,from_y, tile_to|to_x,to_y, [from_tile, to_tile])` Remove the single piece of track at one tile, naming the two tiles it joins.
- `remove_rail_station(tile|x,y, [keep_rail, x1, x2, y1, y2])` Remove the part of a rail station inside a rectangle.
- `remove_rail_track(tile|x,y, [track])` Remove one track piece from a tile.
- `remove_road(tile_from|from_x,from_y, tile_to|to_x,to_y, [road_type])` Remove road along a line between two tiles.
- `remove_road_depot(tile|x,y)` Remove a road depot.
- `remove_road_stop(tile|x,y)` Remove a bus or truck stop.
- `remove_sign(sign_id)` Remove a sign.
- `remove_signal(tile|x,y, [front_tile, front_x, front_y])` Remove a signal from a track tile.
- `remove_water_depot(tile|x,y)` Remove a ship depot.
- `rename_company(name)` Rename your company.
- `rename_vehicle(name, vehicle_id)` Rename a vehicle.
- `reverse_vehicle(vehicle_id)` Turn a vehicle around.
- `sell_vehicle(vehicle_id)` Sell a vehicle.
- `sell_wagon(vehicle_id, wagon, [sell_chain])` Sell one wagon from a train, or that wagon and everything behind it.
- `send_to_depot(vehicle_id)` Order a vehicle to the nearest depot and stop there.
- `send_to_depot_service(vehicle_id)` Order a vehicle to the nearest depot for servicing, after which it resumes its orders rather than waiting.
- `set_auto_replace(engine_id_new, engine_id_old, group_id)` Have vehicles in a group replaced with a newer model when they next visit a depot.
- `set_loan(amount)` Set the loan to an exact amount rather than adjusting it.
- `set_order_compare_function(compare_function, order_pos, vehicle_id)` Set how a conditional order compares the value it tests.
- `set_order_compare_value(order_pos, value, vehicle_id)` Set the value a conditional order compares against.
- `set_order_condition(condition, order_pos, vehicle_id)` Turn an order into a conditional one and choose what it tests.
- `set_order_flags(order_flags, vehicle_id, [order_index, order_position])` Replace the flags on an existing order.
- `set_stop_location(order_pos, stop_location, vehicle_id)` Choose where along the platform a train comes to rest.
- `share_orders(main_vehicle_id, vehicle_id)` Make a vehicle share another's order list.
- `skip_to_order(vehicle_id, order_index|order_position)` Send a vehicle straight to a given order now, abandoning the current one.
- `start_vehicle(vehicle_id)` Start a stopped vehicle.
- `stop_vehicle(vehicle_id)` Stop a vehicle where it is.

