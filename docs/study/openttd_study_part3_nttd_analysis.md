# OpenTTD Comprehensive Study - Part 3: nttd Implementation Analysis & API Design

> **Note.** This part analyses an earlier nttd design in which nttd ran the
> contestant's agent in-process through framework adapters. That is no longer how
> nttd works: the contestant owns the loop and reaches the game over HTTP. The
> OpenTTD research here still holds; the nttd-side conclusions do not. See
> [../architecture.md](../architecture.md) for the current design.

> This is Part 3 of 3. See also:
> - [Part 1: Game Mechanics](./openttd_study_part1_game_mechanics.md)
> - [Part 2: GameScript API Reference](./openttd_study_part2_gs_api_reference.md)

---

## 1. Existing nttd Architecture

### 1.1 System Overview

```
AI Agent <──HTTP/WS──> nttd API Server <──Admin Port──> OpenTTD <──GS Bridge──> GameScript
                       (FastAPI)          (TCP)          (Game)     (Squirrel)
```

**Three-layer architecture**:
1. **Control Plane**: Orchestrator + runtime modes (heartbeat/async/assisted)
2. **State Plane**: WorldState + snapshot broker
3. **Agent-facing API**: REST + WebSocket

### 1.2 Key Components

| Component | File | Lines | Purpose |
|-----------|------|-------|---------|
| GameScript | `ottd_config/game/nttd-gs/main.nut` | 1488 | 93 commands, chunked responses |
| Admin Client | `src/nttd/bridge/admin_client.py` | ~200 | TCP connection, auth, GS messaging |
| Event Bridge | `src/nttd/bridge/bridge.py` | ~150 | Admin packets → WorldState |
| WorldState | `src/nttd/state/world.py` | 292 | In-memory state, snapshots |
| Orchestrator | `src/nttd/runtime/orchestrator.py` | 403 | Runtime modes, heartbeat cycles |
| Observation API | `src/nttd/api/observation_routes.py` | 208 | State queries, compact view |
| Action API | `src/nttd/api/action_routes.py` | 142 | Action submission/tracking |
| Control API | `src/nttd/api/control_routes.py` | 214 | Pause, speed, modes, save/load |
| WebSocket | `src/nttd/api/ws_routes.py` | 103 | Agent heartbeat delivery |
| Agent Base | `agents/base.py` | 204 | Abstract agent with game loop |
| Agent Client | `agents/nttd_client.py` | 179 | HTTP + WS transport |
| Agent Tools | `agents/tools.py` | 205 | Typed query tools |

### 1.3 Runtime Modes

| Mode | Flow | Use Case |
|------|------|----------|
| **Heartbeat** | Pause → GS refresh → snapshot → action window → execute → unpause → advance N days → repeat | RL/benchmarking |
| **Async Real-Time** | Game runs; GS refresh every 10s; snapshots every 2s | Human co-play |
| **Assisted** | Human triggers → pause → snapshot → AI suggests → human approves | Co-pilot |

### 1.4 Existing API Endpoints

**Control**: POST /session/{pause,unpause,speed,mode,stop,save,load,rcon,assist,scenario}, /session/heartbeat/{interval,action,action_window}

**Observation**: GET /state/{full,compact,company/{id},towns,industries,stations,vehicles,metrics}, POST /state/gs/query

**Actions**: POST /actions/{submit,validate,gs/execute}, GET /actions/{id}/status, /actions/recent

**Agents**: POST /agents/{connect,{id}/disconnect,{id}/subscriptions}, GET /agents/{list,{id}/status}

**WebSocket**: WS /ws/{agent_id}

---

## 2. All 93 Implemented GS Commands

### 2.1 Queries (28 commands)

| Command | Parameters | Returns |
|---------|-----------|---------|
| `ping` | — | `{ pong: true }` |
| `get_date` | — | `{ date, year, month, day }` |
| `get_map_size` | — | `{ size_x, size_y, max_x, max_y }` |
| `get_tile_info` | `x, y` | `{ height, slope, is_buildable, is_water, is_road, is_rail, is_station, owner }` |
| `get_towns` | — | `[{ id, name, population, x, y }]` |
| `get_town_info` | `town_id` | `{ id, name, population, houses, x, y, is_city, growth_rate, has_statue, road_layout, ... }` |
| `get_town_rating` | `town_id, company_id` | `{ rating, detailed_rating }` |
| `get_industries` | — | `[{ id, name, type_id, type_name, x, y }]` |
| `get_industry_info` | `industry_id` | `{ id, name, type_id, is_raw, is_processing, production: [{cargo_id, last_month, transported}] }` |
| `get_companies` | — | `[{ id, name, money, loan, max_loan, hq_x, hq_y }]` |
| `get_company_finance` | `company_id` | `{ balance, loan, max_loan, q1_income, q1_expenses, q1_value, q2_* }` |
| `get_stations` | `company_id` | `[{ id, name, x, y, has_rail, has_truck, has_bus, has_airport, has_dock }]` |
| `get_station_info` | `station_id` | `{ id, name, x, y, has_*, cargo_waiting: [{cargo_id, label, waiting}] }` |
| `get_waypoints` | `company_id` | `[{ id, name, x, y, is_rail, is_buoy }]` |
| `get_vehicles` | `company_id, [vehicle_type]` | `[{ id, name, type, x, y, engine_id, age, profit_*, speed, state, order_count }]` |
| `get_vehicle_info` | `vehicle_id` | `{ id, name, type, engine_id, x, y, age, profit_*, speed, state, cargo: [{cargo_id, capacity, loaded}], orders: [...] }` |
| `get_engines` | `[vehicle_type]` | `[{ id, name, cargo_type, capacity, max_speed, price, running_cost, power, weight, reliability, is_wagon }]` |
| `get_cargo_types` | — | `[{ id, label, name, is_freight }]` |
| `get_rail_types` | — | `[{ id, name }]` |
| `get_road_types` | — | `[{ id, name, is_tram }]` |
| `get_groups` | `company_id` | `[{ id, name, vehicle_type, parent_id, profit_* }]` |
| `get_signs` | — | `[{ id, name, x, y }]` |
| `get_subsidies` | — | `[{ id, is_awarded, cargo_type, source_*, destination_*, remaining }]` |
| `get_airport_types` | — | `[{ id, width, height, coverage }]` |
| `get_bridge_types` | — | `[{ id, name, max_length, min_length, max_speed, price }]` |
| `get_orders` | `company_id, vehicle_id` | `{ vehicle_id, order_count, orders: [{index, destination, flags, is_goto_*}] }` |

### 2.2 Smart Queries (3 commands)

| Command | Parameters | Returns |
|---------|-----------|---------|
| `scan_town_area` | `town_id, [radius=15]` | `{ buildable: [{x,y,height,slope}], roads: [{x,y}], buildings, water, counts }` |
| `find_bus_stop_spots` | `town_id, [radius=15], [max_results=10]` | `[{ x, y, distance, adjacent_road_x/y, adjacent_road_count }]` |
| `find_depot_spots` | `town_id, [radius=15], [max_results=5]` | `[{ x, y, distance, adjacent_road_x/y, depot_direction }]` |

### 2.3 Road Construction (7 commands)

| Command | Parameters | Returns |
|---------|-----------|---------|
| `build_road` | `company_id, from_x, from_y, to_x, to_y, [road_type=0]` | `{ from, to }` |
| `build_road_line` | `company_id, from_x, from_y, to_x, to_y, [road_type=0]` | `{ built, failed, total }` |
| `build_road_depot` | `company_id, x, y, [direction=0], [road_type=0]` | `{ tile }` |
| `build_road_stop` | `company_id, x, y, [direction=0], [is_truck_stop], [is_drive_through], [road_type=0]` | `{ tile, type }` |
| `remove_road` | `company_id, from_x, from_y, to_x, to_y, [road_type=0]` | `{ from, to }` |
| `remove_road_depot` | `company_id, x, y` | `{ tile }` |
| `remove_road_stop` | `company_id, x, y` | `{ tile }` |

### 2.4 Rail Construction (11 commands)

| Command | Parameters | Returns |
|---------|-----------|---------|
| `build_rail` | `company_id, from_x/y, to_x/y, [rail_type=0]` OR `prev_x/y, x/y, next_x/y` | `{ tile }` or `{ from, to }` |
| `build_rail_track` | `company_id, x, y, [track], [rail_type=0]` | `{ tile }` |
| `build_rail_station` | `company_id, x, y, [direction=0], [num_platforms=2], [platform_length=5], [rail_type=0]` | `{ tile, platforms, length }` |
| `build_rail_depot` | `company_id, x, y, [direction=0], [rail_type=0]` | `{ tile }` |
| `build_rail_signal` | `company_id, x, y, [signal_type=0]` | `{ tile }` |
| `build_rail_waypoint` | `company_id, x, y` | `{ tile }` |
| `remove_rail` | `company_id, from_x/y, x/y, to_x/y` | `{}` |
| `remove_rail_track` | `company_id, x, y, [track]` | `{ tile }` |
| `remove_signal` | `company_id, x, y, front_x, front_y` | `{}` |
| `remove_rail_station` | `company_id, x1/y1, x2/y2, [keep_rail=false]` | `{}` |
| `convert_rail` | `company_id, x1/y1, x2/y2, rail_type` | `{}` |

### 2.5 Marine Construction (8 commands)

| Command | Parameters | Returns |
|---------|-----------|---------|
| `build_canal` | `company_id, x, y` | `{ tile }` |
| `build_lock` | `company_id, x, y` | `{ tile }` |
| `build_buoy` | `company_id, x, y` | `{ tile }` |
| `build_water_depot` | `company_id, x, y, [direction=0]` | `{ tile }` |
| `remove_canal` | `company_id, x, y` | `{}` |
| `remove_lock` | `company_id, x, y` | `{}` |
| `remove_buoy` | `company_id, x, y` | `{}` |
| `remove_water_depot` | `company_id, x, y` | `{}` |

### 2.6 Other Construction (7 commands)

| Command | Parameters | Returns |
|---------|-----------|---------|
| `build_airport` | `company_id, x, y, [airport_type=0]` | `{ tile, type }` |
| `remove_airport` | `company_id, x, y` | `{ tile }` |
| `open_close_airport` | `company_id, station_id` | `{ station_id }` |
| `build_dock` | `company_id, x, y` | `{ tile }` |
| `build_bridge` | `company_id, start_x/y, end_x/y, [bridge_type=0], [transport_type="road"]` | `{ start, end_pos }` |
| `build_tunnel` | `company_id, x, y, [transport_type="rail"]` | `{ entrance, exit_pos }` |
| `demolish_tile` | `company_id, x, y` | `{ tile }` |

### 2.7 Company Management (3 commands)

| Command | Parameters | Returns |
|---------|-----------|---------|
| `build_company_hq` | `company_id, x, y` | `{ tile }` |
| `set_loan` | `company_id, amount` | `{ loan, balance }` |
| `rename_company` | `company_id, name` | `{ name }` |

### 2.8 Town Actions (7 commands, GS-exclusive)

| Command | Parameters | Returns |
|---------|-----------|---------|
| `found_town` | `x, y, [size], [is_city], [road_layout], [name]` | `{ town_id, name, x, y }` |
| `expand_town` | `town_id, [houses=5]` | `{ town_id, population }` |
| `set_town_growth` | `town_id, days` | `{ town_id, growth_rate }` |
| `perform_town_action` | `town_id, action` | `{ town_id, action }` |
| `get_town_rating` | `town_id, company_id` | `{ town_id, company_id, rating, detailed_rating }` |
| `change_town_rating` | `town_id, company_id, delta` | `{ town_id, company_id, new_rating }` |
| `set_cargo_goal` | `town_id, town_effect, goal` | `{ town_id, town_effect, goal }` |

### 2.9 Other Actions (4 commands)

| Command | Parameters | Returns |
|---------|-----------|---------|
| `create_subsidy` | `cargo_type, from_type, from_id, to_type, to_id` | `{}` |
| `build_sign` | `company_id, x, y, name` | `{ sign_id, name }` |
| `remove_sign` | `company_id, sign_id` | `{}` |

### 2.10 Vehicle Groups (4 commands)

| Command | Parameters | Returns |
|---------|-----------|---------|
| `create_group` | `company_id, [vehicle_type="train"], [parent_group_id]` | `{ group_id }` |
| `delete_group` | `company_id, group_id` | `{}` |
| `move_to_group` | `company_id, group_id, vehicle_id` | `{}` |
| `set_auto_replace` | `company_id, group_id, engine_id_old, engine_id_new` | `{}` |

### 2.11 Vehicle Management (12 commands)

| Command | Parameters | Returns |
|---------|-----------|---------|
| `buy_vehicle` | `company_id, depot_x, depot_y, engine_id` | `{ vehicle_id, name }` |
| `sell_vehicle` | `company_id, vehicle_id` | `{}` |
| `sell_wagon` | `company_id, vehicle_id, wagon, [sell_chain=false]` | `{}` |
| `move_wagon` | `company_id, source_vehicle_id, source_wagon, dest_vehicle_id, dest_wagon, [move_chain=false]` | `{}` |
| `start_vehicle` | `company_id, vehicle_id` | `{ running }` |
| `stop_vehicle` | `company_id, vehicle_id` | `{}` or `{ already_stopped }` |
| `send_to_depot` | `company_id, vehicle_id` | `{}` |
| `send_to_depot_service` | `company_id, vehicle_id` | `{}` |
| `clone_vehicle` | `company_id, vehicle_id, [share_orders=true]` | `{ vehicle_id, name }` |
| `refit_vehicle` | `company_id, vehicle_id, cargo_id` | `{}` |
| `reverse_vehicle` | `company_id, vehicle_id` | `{}` |
| `rename_vehicle` | `company_id, vehicle_id, name` | `{ vehicle_id, name }` |

### 2.12 Order Management (9 commands)

| Command | Parameters | Returns |
|---------|-----------|---------|
| `add_order` | `company_id, vehicle_id, station_id, [order_flags=0]` | `{ order_count }` |
| `insert_order` | `company_id, vehicle_id, order_position, station_id, [order_flags=0]` | `{ order_count }` |
| `remove_order` | `company_id, vehicle_id, order_position` | `{ order_count }` |
| `skip_to_order` | `company_id, vehicle_id, order_position` | `{}` |
| `move_order` | `company_id, vehicle_id, from_position, to_position` | `{}` |
| `set_order_flags` | `company_id, vehicle_id, order_position, order_flags` | `{}` |
| `share_orders` | `company_id, vehicle_id, main_vehicle_id` | `{}` |
| `copy_orders` | `company_id, vehicle_id, main_vehicle_id` | `{ order_count }` |

---

## 3. Gap Analysis: GS API Methods NOT Yet Exposed

### 3.1 High Priority Gaps

| Missing Command | GS API Method | Why Important |
|----------------|---------------|---------------|
| **get_game_setting** | `GSGameSettings.GetValue(setting)` | Query game speed, difficulty, vehicle limits |
| **set_game_setting** | `GSGameSettings.SetValue(setting, value)` | Control game speed, toggle features |
| **add_conditional_order** | `GSOrder.AppendConditionalOrder(vid, jump_to)` | Complex routing with load/reliability checks |
| **insert_conditional_order** | `GSOrder.InsertConditionalOrder(vid, pos, jump_to)` | Insert conditional at position |
| **set_order_condition** | `GSOrder.SetOrderCondition(vid, pos, condition)` | Set what to check |
| **set_order_compare** | `GSOrder.SetOrderCompareFunction/Value(vid, pos, ...)` | Set comparison logic |
| **set_order_jump** | `GSOrder.SetOrderJumpTo(vid, pos, target)` | Set branch target |
| **get_station_cargo_from** | `GSStation.GetCargoWaitingFrom(sid, from_sid, cargo)` | Cargo origin tracking |
| **get_station_cargo_via** | `GSStation.GetCargoWaitingVia(sid, via_sid, cargo)` | Cargo routing info |
| **get_station_cargo_rating** | `GSStation.GetCargoRating(sid, cargo)` | Per-cargo station rating |
| **get_cargo_income** | `GSCargo.GetCargoIncome(cargo, distance, days)` | Payment calculator |
| **get_cargo_monitor_town** | `GSCargoMonitor.GetTownDeliveryAmount(...)` | Track deliveries per town |
| **get_cargo_monitor_industry** | `GSCargoMonitor.GetIndustryDeliveryAmount(...)` | Track deliveries per industry |
| **buy_vehicle_with_refit** | `GSVehicle.BuildVehicleWithRefit(depot, engine, cargo)` | Buy pre-refitted |
| **unshare_orders** | `GSOrder.UnshareOrders(vid)` | Break order sharing |

### 3.2 Medium Priority Gaps

| Missing Command | GS API Method | Why Important |
|----------------|---------------|---------------|
| **change_bank_balance** | `GSCompany.ChangeBankBalance(company, delta, type, tile)` | Financial manipulation for testing/scenarios |
| **set_max_loan** | `GSCompany.SetMaxLoanAmountForCompany(company, amount)` | Scenario control |
| **get_infrastructure_count** | `GSInfrastructure.GetRailPieceCount/GetRoadPieceCount(...)` | Infrastructure analytics |
| **get_infrastructure_costs** | `GSInfrastructure.GetMonthlyRailCosts/GetMonthlyRoadCosts(...)` | Cost analysis |
| **set_industry_production** | `GSIndustry.SetProductionLevel(id, level, show_news, text)` | Scenario control |
| **set_industry_flags** | `GSIndustry.SetControlFlags(id, flags)` | Prevent closure |
| **set_industry_exclusive** | `GSIndustry.SetExclusiveSupplier/Consumer(id, company)` | Competition control |
| **get_industry_stockpile** | `GSIndustry.GetStockpiledCargo(id, cargo)` | Input cargo tracking |
| **get_industry_accepted** | `GSIndustry.IsCargoAccepted(id, cargo)` | Acceptance check |
| **set_order_stop_location** | `GSOrder.SetStopLocation(vid, pos, location)` | Train platform alignment |
| **set_order_refit** | `GSOrder.SetOrderRefit(vid, pos, cargo)` | Mid-route refit |
| **get_tile_cargo_acceptance** | `GSTile.GetCargoAcceptance(tile, cargo, w, h, radius)` | Station placement |
| **get_tile_cargo_production** | `GSTile.GetCargoProduction(tile, cargo, w, h, radius)` | Station placement |
| **raise_tile** | `GSTile.RaiseTile(tile, slope)` | Terraforming |
| **lower_tile** | `GSTile.LowerTile(tile, slope)` | Terraforming |
| **level_tiles** | `GSTile.LevelTiles(start, end)` | Flatten area |
| **plant_tree** | `GSTile.PlantTree(tile)` | Improve town rating |
| **plant_tree_rectangle** | `GSTile.PlantTreeRectangle(tile, w, h)` | Bulk tree planting |
| **remove_dock** | `GSMarine.RemoveDock(tile)` | Dock removal |
| **remove_bridge** | `GSBridge.RemoveBridge(tile)` | Bridge removal |
| **remove_tunnel** | `GSTunnel.RemoveTunnel(tile)` | Tunnel removal |
| **remove_rail_waypoint** | `GSRail.RemoveRailWaypointTileRectangle(...)` | Waypoint removal |
| **build_one_way_road** | `GSRoad.BuildOneWayRoad/Full(from, to)` | Directional roads |
| **build_drive_through_road_station** | Already via `build_road_stop` | (parameter exposed) |

### 3.3 Low Priority Gaps

| Missing Command | GS API Method | Why Important |
|----------------|---------------|---------------|
| **enable_engine** | `GSEngine.EnableForCompany(engine, company)` | Early access to engines |
| **disable_engine** | `GSEngine.DisableForCompany(engine, company)` | Restrict engines |
| **rename_group** | `GSGroup.SetName(group_id, name)` | Group labeling |
| **set_group_parent** | `GSGroup.SetParent(group_id, parent)` | Group hierarchy |
| **stop_auto_replace** | `GSGroup.StopAutoReplace(group_id, engine)` | Cancel replacement |
| **set_group_color** | `GSGroup.SetPrimaryColour/SetSecondaryColour(...)` | Visual grouping |
| **get_group_usage** | `GSGroup.GetCurrentUsage(group_id)` | Usage stats |
| **set_auto_renew** | `GSCompany.SetAutoRenewStatus/Months/Money(...)` | Auto-renewal config |
| **set_livery** | `GSCompany.SetPrimaryLiveryColour/Secondary(...)` | Company colors |
| **set_president** | `GSCompany.SetPresidentName/Gender(...)` | Cosmetic |
| **create_goal** | `GSGoal.New/Remove/SetText/SetCompleted(...)` | Scenario goals |
| **create_news** | `GSNews.Create(...)` | News messages |
| **create_story** | `GSStoryPage.New/NewElement/Show(...)` | Narrative |
| **create_league** | `GSLeagueTable.New/NewElement(...)` | Custom scoring |
| **scroll_viewport** | `GSViewport.ScrollTo/ScrollEveryoneTo(...)` | Camera control |
| **get_town_noise** | `GSTown.GetAllowedNoise(town_id)` | Airport placement |
| **get_town_monthly_prod** | `GSTown.GetLastMonthProduction/Supplied/Received(...)` | Town economics |
| **is_within_town** | `GSTown.IsWithinTownInfluence(town_id, tile)` | Area queries |
| **get_station_coverage** | `GSStation.GetStationCoverageRadius/GetCoverageRadius(...)` | Coverage analysis |
| **get_depot_list** | `GSDepotList(vehicle_type)` | Find depots |
| **is_road_connected** | `GSRoad.AreRoadTilesConnected(tile1, tile2)` | Connectivity check |
| **convert_road** | `GSRoad.ConvertRoadType(start, end, type)` | Road upgrades |
| **get_rail_tracks** | `GSRail.GetRailTracks(tile)` | Track direction query |
| **are_tiles_connected** | `GSRail.AreTilesConnected(from, tile, to)` | Rail connectivity |
| **is_vehicle_disabled** | `GSGameSettings.IsDisabledVehicleType(type)` | Feature check |
| **get_build_cost** | `GSTile/GSRail/GSRoad/GSMarine.GetBuildCost(...)` | Cost queries |

### 3.4 Query Enrichment Gaps (existing queries missing fields)

| Existing Command | Missing Fields | GS API |
|-----------------|---------------|--------|
| `get_station_info` | `cargo_rating[]`, `coverage_radius`, `nearest_town`, `construction_date` | GSStation.GetCargoRating, GetStationCoverageRadius, GetNearestTown |
| `get_station_info` | `cargo_planned[]`, `cargo_waiting_from[]` | GSStation.GetCargoPlanned*, GetCargoWaitingFrom* |
| `get_vehicle_info` | `running_cost`, `current_value`, `reliability`, `road_type`, `group_id` | GSVehicle.GetRunningCost, GetCurrentValue, GetReliability |
| `get_town_info` | `last_month_production`, `last_month_supplied`, `last_month_received`, `allowed_noise` | GSTown.GetLastMonth*, GetAllowedNoise |
| `get_industry_info` | `accepted_cargo[]`, `stockpiled_cargo`, `construction_date`, `has_heliport`, `has_dock`, `stations_around`, `exclusive_supplier/consumer`, `production_level`, `control_flags` | GSIndustry.* |
| `get_company_finance` | `q1/q2_cargo_delivered`, `q1/q2_performance_rating`, `auto_renew_*`, `hq_tile` | GSCompany.GetQuarterlyCargoDelivered, etc |
| `get_engines` | `max_tractive_effort`, `max_age`, `design_date`, `can_refit_to`, `rail_type`, `road_type`, `plane_type`, `max_order_distance` | GSEngine.* |
| `get_cargo_types` | `town_effect`, `cargo_class`, `weight`, `distribution_type` | GSCargo.GetTownEffect, HasCargoClass, GetWeight |

---

## 4. Complete Primitive Actions Taxonomy

Every primitive action maps to exactly one GS API call executed within a `GSCompanyMode` context.

### 4.1 Infrastructure Building (33 primitives)

| # | Action | GS Method | Category |
|---|--------|-----------|----------|
| 1 | Build road segment | GSRoad.BuildRoad(from, to) | Road |
| 2 | Build road full | GSRoad.BuildRoadFull(from, to) | Road |
| 3 | Build one-way road | GSRoad.BuildOneWayRoad(from, to) | Road |
| 4 | Build one-way road full | GSRoad.BuildOneWayRoadFull(from, to) | Road |
| 5 | Build road depot | GSRoad.BuildRoadDepot(tile, front) | Road |
| 6 | Build road station | GSRoad.BuildRoadStation(tile, front, type, sid) | Road |
| 7 | Build drive-through station | GSRoad.BuildDriveThroughRoadStation(...) | Road |
| 8 | Build rail track | GSRail.BuildRailTrack(tile, track) | Rail |
| 9 | Build rail (3-tile) | GSRail.BuildRail(from, tile, to) | Rail |
| 10 | Build rail station | GSRail.BuildRailStation(tile, dir, platforms, length, sid) | Rail |
| 11 | Build rail depot | GSRail.BuildRailDepot(tile, front) | Rail |
| 12 | Build rail signal | GSRail.BuildSignal(tile, front, type) | Rail |
| 13 | Build rail waypoint | GSRail.BuildRailWaypoint(tile) | Rail |
| 14 | Build canal | GSMarine.BuildCanal(tile) | Marine |
| 15 | Build lock | GSMarine.BuildLock(tile) | Marine |
| 16 | Build buoy | GSMarine.BuildBuoy(tile) | Marine |
| 17 | Build water depot | GSMarine.BuildWaterDepot(tile, front) | Marine |
| 18 | Build dock | GSMarine.BuildDock(tile, sid) | Marine |
| 19 | Build airport | GSAirport.BuildAirport(tile, type, sid) | Air |
| 20 | Build bridge | GSBridge.BuildBridge(vtype, btype, start, end) | General |
| 21 | Build tunnel | GSTunnel.BuildTunnel(vtype, start) | General |
| 22 | Build sign | GSSign.BuildSign(tile, name) | General |
| 23 | Build company HQ | GSCompany.BuildCompanyHQ(tile) | Company |
| 24 | Raise tile | GSTile.RaiseTile(tile, slope) | Landscape |
| 25 | Lower tile | GSTile.LowerTile(tile, slope) | Landscape |
| 26 | Level tiles | GSTile.LevelTiles(start, end) | Landscape |
| 27 | Demolish tile | GSTile.DemolishTile(tile) | Landscape |
| 28 | Plant tree | GSTile.PlantTree(tile) | Landscape |
| 29 | Plant tree rectangle | GSTile.PlantTreeRectangle(tile, w, h) | Landscape |
| 30 | Convert rail type | GSRail.ConvertRailType(start, end, type) | Rail |
| 31 | Convert road type | GSRoad.ConvertRoadType(start, end, type) | Road |
| 32 | Set road type | GSRoad.SetCurrentRoadType(type) | Setup |
| 33 | Set rail type | GSRail.SetCurrentRailType(type) | Setup |

### 4.2 Infrastructure Removal (18 primitives)

| # | Action | GS Method |
|---|--------|-----------|
| 34 | Remove road | GSRoad.RemoveRoad(from, to) |
| 35 | Remove road full | GSRoad.RemoveRoadFull(from, to) |
| 36 | Remove road depot | GSRoad.RemoveRoadDepot(tile) |
| 37 | Remove road station | GSRoad.RemoveRoadStation(tile) |
| 38 | Remove rail track | GSRail.RemoveRailTrack(tile, track) |
| 39 | Remove rail (3-tile) | GSRail.RemoveRail(from, tile, to) |
| 40 | Remove rail station | GSRail.RemoveRailStationTileRectangle(...) |
| 41 | Remove rail waypoint | GSRail.RemoveRailWaypointTileRectangle(...) |
| 42 | Remove signal | GSRail.RemoveSignal(tile, front) |
| 43 | Remove canal | GSMarine.RemoveCanal(tile) |
| 44 | Remove lock | GSMarine.RemoveLock(tile) |
| 45 | Remove buoy | GSMarine.RemoveBuoy(tile) |
| 46 | Remove water depot | GSMarine.RemoveWaterDepot(tile) |
| 47 | Remove dock | GSMarine.RemoveDock(tile) |
| 48 | Remove airport | GSAirport.RemoveAirport(tile) |
| 49 | Remove bridge | GSBridge.RemoveBridge(tile) |
| 50 | Remove tunnel | GSTunnel.RemoveTunnel(tile) |
| 51 | Remove sign | GSSign.RemoveSign(id) |

### 4.3 Vehicle Operations (14 primitives)

| # | Action | GS Method |
|---|--------|-----------|
| 52 | Buy vehicle | GSVehicle.BuildVehicle(depot, engine) |
| 53 | Buy vehicle with refit | GSVehicle.BuildVehicleWithRefit(depot, engine, cargo) |
| 54 | Clone vehicle | GSVehicle.CloneVehicle(depot, vid, share) |
| 55 | Sell vehicle | GSVehicle.SellVehicle(vid) |
| 56 | Sell wagon | GSVehicle.SellWagon(vid, wagon) |
| 57 | Sell wagon chain | GSVehicle.SellWagonChain(vid, wagon) |
| 58 | Move wagon | GSVehicle.MoveWagon(src_vid, src_w, dst_vid, dst_w) |
| 59 | Move wagon chain | GSVehicle.MoveWagonChain(src_vid, src_w, dst_vid, dst_w) |
| 60 | Refit vehicle | GSVehicle.RefitVehicle(vid, cargo) |
| 61 | Start/stop vehicle | GSVehicle.StartStopVehicle(vid) |
| 62 | Send to depot | GSVehicle.SendVehicleToDepot(vid) |
| 63 | Send to depot (service) | GSVehicle.SendVehicleToDepotForServicing(vid) |
| 64 | Reverse vehicle | GSVehicle.ReverseVehicle(vid) |
| 65 | Rename vehicle | GSVehicle.SetName(vid, name) |

### 4.4 Order Operations (17 primitives)

| # | Action | GS Method |
|---|--------|-----------|
| 66 | Append order | GSOrder.AppendOrder(vid, tile, flags) |
| 67 | Insert order | GSOrder.InsertOrder(vid, pos, tile, flags) |
| 68 | Remove order | GSOrder.RemoveOrder(vid, pos) |
| 69 | Move order | GSOrder.MoveOrder(vid, from, to) |
| 70 | Skip to order | GSOrder.SkipToOrder(vid, pos) |
| 71 | Set order flags | GSOrder.SetOrderFlags(vid, pos, flags) |
| 72 | Share orders | GSOrder.ShareOrders(vid, src_vid) |
| 73 | Copy orders | GSOrder.CopyOrders(vid, src_vid) |
| 74 | Unshare orders | GSOrder.UnshareOrders(vid) |
| 75 | Append conditional | GSOrder.AppendConditionalOrder(vid, jump) |
| 76 | Insert conditional | GSOrder.InsertConditionalOrder(vid, pos, jump) |
| 77 | Set order condition | GSOrder.SetOrderCondition(vid, pos, cond) |
| 78 | Set compare function | GSOrder.SetOrderCompareFunction(vid, pos, func) |
| 79 | Set compare value | GSOrder.SetOrderCompareValue(vid, pos, val) |
| 80 | Set jump target | GSOrder.SetOrderJumpTo(vid, pos, target) |
| 81 | Set stop location | GSOrder.SetStopLocation(vid, pos, loc) |
| 82 | Set order refit | GSOrder.SetOrderRefit(vid, pos, cargo) |

### 4.5 Company/Group Operations (15 primitives)

| # | Action | GS Method |
|---|--------|-----------|
| 83 | Set loan | GSCompany.SetLoanAmount(amount) |
| 84 | Rename company | GSCompany.SetName(name) |
| 85 | Set auto-renew | GSCompany.SetAutoRenewStatus/Months/Money(...) |
| 86 | Set livery | GSCompany.SetPrimaryLiveryColour/Secondary(...) |
| 87 | Create group | GSGroup.CreateGroup(vtype, parent) |
| 88 | Delete group | GSGroup.DeleteGroup(gid) |
| 89 | Rename group | GSGroup.SetName(gid, name) |
| 90 | Set group parent | GSGroup.SetParent(gid, parent) |
| 91 | Move vehicle to group | GSGroup.MoveVehicle(gid, vid) |
| 92 | Set auto-replace | GSGroup.SetAutoReplace(gid, old, new) |
| 93 | Stop auto-replace | GSGroup.StopAutoReplace(gid, engine) |
| 94 | Set group color | GSGroup.SetPrimaryColour/Secondary(gid, color) |
| 95 | Open/close airport | GSStation.OpenCloseAirport(sid) |
| 96 | Change bank balance | GSCompany.ChangeBankBalance(co, delta, type, tile) |
| 97 | Set max loan | GSCompany.SetMaxLoanAmountForCompany(co, amt) |

### 4.6 GS-Exclusive/Deity Operations (15 primitives)

| # | Action | GS Method |
|---|--------|-----------|
| 98 | Found town | GSTown.FoundTown(tile, size, city, layout, name) |
| 99 | Expand town | GSTown.ExpandTown(tid, houses) |
| 100 | Set growth rate | GSTown.SetGrowthRate(tid, days) |
| 101 | Set cargo goal | GSTown.SetCargoGoal(tid, effect, goal) |
| 102 | Change town rating | GSTown.ChangeRating(tid, co, delta) |
| 103 | Perform town action | GSTown.PerformTownAction(tid, action) |
| 104 | Set industry production | GSIndustry.SetProductionLevel(id, level, news, text) |
| 105 | Set industry flags | GSIndustry.SetControlFlags(id, flags) |
| 106 | Set exclusive supplier | GSIndustry.SetExclusiveSupplier(id, co) |
| 107 | Set exclusive consumer | GSIndustry.SetExclusiveConsumer(id, co) |
| 108 | Create subsidy | GSSubsidy.Create(cargo, src_type, src, dst_type, dst) |
| 109 | Set game setting | GSGameSettings.SetValue(setting, value) |
| 110 | Enable engine | GSEngine.EnableForCompany(engine, co) |
| 111 | Disable engine | GSEngine.DisableForCompany(engine, co) |
| 112 | Create news | GSNews.Create(type, text, co, ref_type, ref) |

**Total: ~112 distinct primitive actions**

---

## 5. Compound Actions Taxonomy

Compound actions are multi-step sequences of primitives that accomplish a gameplay goal.

### 5.1 Bus Route (Road Passenger Transport)

**Steps** (8-12 primitives):
1. `find_bus_stop_spots(town_a)` → select spot A
2. `build_road_stop(spot_a, is_truck=false)` → build bus stop in town A
3. `find_bus_stop_spots(town_b)` → select spot B
4. `build_road_stop(spot_b, is_truck=false)` → build bus stop in town B
5. `build_road_line(spot_a → spot_b)` → connect with road (may need pathfinding for non-straight)
6. `find_depot_spots(town_a)` → find depot location
7. `build_road_depot(depot_spot)` → build depot
8. `buy_vehicle(depot, bus_engine_id)` → purchase bus
9. `add_order(vehicle, station_a)` → first stop
10. `add_order(vehicle, station_b)` → second stop
11. `start_vehicle(vehicle)` → begin service
12. Optionally: `clone_vehicle(vehicle, share_orders=true)` → add more buses

### 5.2 Truck Route (Freight Transport)

**Steps** (10-15 primitives):
1. Query industries for cargo production/acceptance
2. `find_bus_stop_spots()` near source industry
3. `build_road_stop(spot, is_truck=true)` → loading bay at source
4. `find_bus_stop_spots()` near destination
5. `build_road_stop(spot, is_truck=true)` → loading bay at destination
6. Build road connecting them (possibly multi-segment with pathfinding)
7. `build_road_depot()` near source
8. `buy_vehicle(depot, truck_engine_id)` → purchase truck
9. `add_order(vehicle, station_a, OF_FULL_LOAD_ALL)` → load at source
10. `add_order(vehicle, station_b)` → deliver to destination
11. `start_vehicle(vehicle)`
12. Clone for additional capacity

### 5.3 Train Route (Point-to-Point)

**Steps** (15-25+ primitives):
1. Find source/destination locations
2. `build_rail_station(source, direction, platforms, length)` → source station
3. `build_rail_station(dest, direction, platforms, length)` → destination station
4. Plan track path (external pathfinding — A* or similar)
5. For each tile in path: `build_rail(prev, tile, next)` or `build_rail_track(tile, track)`
6. `build_rail_signal(tile, front, PBS_ONEWAY)` at intervals along track
7. `build_rail_depot(spot, direction)` → depot near source
8. `buy_vehicle(depot, locomotive_engine_id)` → buy locomotive
9. For each wagon: `buy_vehicle(depot, wagon_engine_id)` → buy cargo wagon
10. For each wagon: `move_wagon()` → attach to locomotive (may be automatic)
11. `add_order(vehicle, source_station, OF_FULL_LOAD_ALL)` → load at source
12. `add_order(vehicle, dest_station)` → deliver
13. `start_vehicle(vehicle)`
14. `create_group(vehicle_type="train")` → organize
15. `move_to_group(group, vehicle)` → assign to group

### 5.4 Ship Route

**Steps** (8-12 primitives):
1. Find coastal tiles near source/destination
2. `build_dock(coast_tile_a)` → source dock
3. `build_dock(coast_tile_b)` → destination dock
4. Optionally: `build_buoy(mid_ocean_tile)` → navigation waypoint
5. `build_water_depot(water_tile)` → ship depot
6. `buy_vehicle(depot, ship_engine_id)` → purchase ship
7. `add_order(vehicle, dock_a, OF_FULL_LOAD_ALL)`
8. Optionally: `add_order(vehicle, buoy_waypoint)` → via buoy
9. `add_order(vehicle, dock_b)`
10. `start_vehicle(vehicle)`

### 5.5 Air Route

**Steps** (6-10 primitives):
1. Check `get_town_info()` for noise tolerance
2. Find flat area near town: `scan_town_area()` or `get_tile_info()` checks
3. `build_airport(tile, airport_type)` → source airport
4. `build_airport(tile, airport_type)` → destination airport
5. `buy_vehicle(hangar_tile, aircraft_engine_id)` → purchase plane
6. `add_order(vehicle, source_airport)`
7. `add_order(vehicle, dest_airport)`
8. `start_vehicle(vehicle)`
9. Clone for more aircraft

### 5.6 Network Expansion (Add Train to Route)

**Steps** (2-3 primitives):
1. `clone_vehicle(existing_train, share_orders=true)` → clone with shared orders
2. `start_vehicle(new_train)`
3. Optionally: `move_to_group(group, new_train)`

### 5.7 Rail Upgrade

**Steps** (3-5 primitives):
1. Stop all trains on route: `stop_vehicle()` for each
2. `convert_rail(area_start, area_end, new_rail_type)` → upgrade tracks
3. For each train: `send_to_depot()`, sell, buy new engine with new rail type, attach wagons
4. Restart trains

### 5.8 Improve Town Rating

**Steps** (2-5 primitives):
1. `plant_tree_rectangle(town_center, 10, 10)` → mass tree planting
2. Repeat if needed (diminishing returns after 220 trees)
3. Optionally: `perform_town_action(town, ROAD_REBUILD)` (costs money)
4. Optionally: `perform_town_action(town, BUILD_STATUE)` (permanent +10% station rating)

### 5.9 Claim Subsidy

**Steps** (variable — essentially build a route matching the subsidy):
1. `get_subsidies()` → find unclaimed subsidies
2. Identify source and destination (town or industry)
3. Build appropriate route (bus/truck/train/ship/air) connecting them
4. Ensure first delivery happens before subsidy expires

---

## 6. API Design Recommendations

### 6.1 Layered API Architecture

```
Layer 3: Strategic API    — "establish_coal_route(mine_id, power_station_id)"
Layer 2: Composite API    — "build_bus_route(town_a, town_b)"
Layer 1: Primitive API    — "build_road(from, to)", "buy_vehicle(depot, engine)"
Layer 0: Raw GS Passthrough — "gs_execute({action: 'build_road', params: {...}})"
```

**Layer 0** already exists (`POST /actions/gs/execute`).
**Layer 1** already exists (`POST /actions/submit` with action types).
**Layers 2-3** should be implemented as agent-side logic, not server-side — keeps nttd agent-agnostic.

### 6.2 State Observation API Design

**Full snapshot** (on connect or periodically):
```json
{
  "tick": 12345,
  "game": { "date": {"year":1950,"month":3,"day":15}, "paused": false, "speed": 1 },
  "map": { "width": 256, "height": 256, "landscape": "temperate" },
  "companies": [{ "id": 0, "name": "...", "balance": 100000, "loan": 50000, ... }],
  "towns": [{ "id": 0, "name": "...", "population": 500, "x": 128, "y": 64, ... }],
  "industries": [{ "id": 0, "name": "...", "type": "Coal Mine", "x": 50, "y": 30, "production": [...] }],
  "stations": [{ "id": 0, "name": "...", "x": 45, "y": 28, "cargo_waiting": [...], "cargo_rating": [...] }],
  "vehicles": [{ "id": 0, "type": "train", "x": 46, "y": 29, "speed": 120, "cargo": [...], "orders": [...] }],
  "routes": [{ "stations": [0, 5], "vehicles": [0, 1, 2], "total_profit": 50000 }],
  "subsidies": [{ "id": 0, "cargo": "Coal", "from": "Mine A", "to": "Power Station", "remaining": 180 }]
}
```

**Delta updates** (per heartbeat):
```json
{
  "tick": 12346,
  "changed_vehicles": [{ "id": 0, "x": 47, "y": 29, "speed": 125 }],
  "changed_stations": [{ "id": 0, "coal_waiting": 45 }],
  "events": [{ "type": "subsidy_offer", "subsidy_id": 3 }]
}
```

### 6.3 Action Submission Design

**Single action**:
```json
POST /actions/submit
{
  "company_id": 0,
  "action_type": "build_road",
  "parameters": { "from_x": 10, "from_y": 20, "to_x": 10, "to_y": 25 }
}
```

**Batch actions** (recommended addition):
```json
POST /actions/batch
{
  "company_id": 0,
  "actions": [
    { "action_type": "build_road", "parameters": { ... } },
    { "action_type": "build_road_stop", "parameters": { ... } },
    { "action_type": "buy_vehicle", "parameters": { ... } }
  ],
  "mode": "sequential"  // or "independent"
}
```

**Dry-run/cost estimation** (uses GSTestMode internally):
```json
POST /actions/estimate
{
  "company_id": 0,
  "action_type": "build_rail_station",
  "parameters": { "x": 50, "y": 30, "platforms": 3, "length": 5 }
}
// Response: { "estimated_cost": 25000, "feasible": true }
```

### 6.4 Event Subscription Design

```json
POST /agents/{id}/subscriptions
{
  "channel": "events",
  "event_types": ["vehicle_crashed", "industry_close", "subsidy_offer"],
  "cadence": "immediate"
}
```

Events delivered via WebSocket:
```json
{ "type": "event", "event_type": "subsidy_offer", "data": { "subsidy_id": 3, "cargo": "Coal", ... } }
```

### 6.5 Recommended New Endpoints

| Endpoint | Purpose | Priority |
|----------|---------|----------|
| `POST /actions/batch` | Execute multiple actions atomically | High |
| `POST /actions/estimate` | Cost estimation without execution | High |
| `GET /state/cargo_flows` | Cargo monitoring per town/industry | High |
| `GET /state/tile/{x}/{y}` | Detailed tile info | Medium |
| `GET /state/tile/area?x1&y1&x2&y2` | Bulk tile scan | Medium |
| `POST /session/settings` | Read/write game settings | High |
| `GET /state/coverage/{station_id}` | Station coverage tile list | Medium |

---

## 7. Technical Constraints Summary

| Constraint | Impact | Mitigation |
|-----------|--------|------------|
| GSAdmin.Send() 1450 byte limit | Large responses chunked | Chunk protocol with `_chunk`/`_total` (already implemented) |
| GS single-threaded execution | Commands sequential per tick | Batch commands; minimize round-trips |
| GSCompanyMode sequential | One company at a time | Queue by company |
| GS opcode budget per tick | Long operations may suspend | Sleep after heavy operations |
| No pathfinding in GS | Can't route tracks automatically | External A* pathfinding in agent or nttd |
| No industry creation via GS | Can only control existing industries | Use GSGameSettings for map generation |
| Admin port fire-and-forget | No delivery guarantee | Correlation IDs + timeout/retry |
| Multiplayer global pause | All players affected | Coordinate via runtime modes |
| Full map scan expensive | 1M+ tiles on 1024x1024 | Incremental scanning, cache results |
| Vehicle limits per company | Default 5000 per type | Check limits before buying |
| Station spread limit | Parts must be within N tiles | Check before building |

---

## 8. Summary: Completeness Assessment

### What we CAN do (via GS + nttd):
- **100% of construction** — all transport types
- **100% of vehicle management** — buy, sell, control, group
- **100% of orders** — including conditional, shared, refit
- **100% of financial queries** — balance, income, expenses, value
- **100% of state observation** — every entity type queryable
- **100% of town manipulation** — GS-exclusive powers
- **90% of industry control** — everything except create/destroy
- **100% of game settings** — read/write any setting

### What we CANNOT do:
- Create or destroy industries (game/map generator only)
- Built-in pathfinding (must implement externally)
- Access individual cargo packet routing internally
- Guarantee per-tick observation (GS suspension)
- Control other AI scripts' internal state

### Current nttd coverage: ~83% of available GS API surface
- 93 commands implemented out of ~112 primitives
- Key gaps: conditional orders, game settings, cargo monitoring, terraforming, cost estimation
- Query enrichment needed for stations, industries, engines, and companies
