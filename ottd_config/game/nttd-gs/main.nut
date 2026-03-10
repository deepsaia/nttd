// nttd GameScript — bridge between the nttd API server and OpenTTD.
//
// Receives JSON commands from the admin port, executes them in-game,
// and sends JSON responses back. Large array responses are automatically
// chunked to stay under the ~1400 byte admin port packet limit.
//
// Command format:  { "id": "gs_1", "action": "get_towns", "params": { ... } }
// Response format: { "id": "gs_1", "success": true, "result": { ... } }
// Chunked format:  { "id": "gs_1", "success": true, "result": [...], "_chunk": 0, "_total": 3 }

class NttdGS extends GSController {
  CHUNK_SIZE = 10;

  function Start() {
    GSLog.Info("nttd GameScript started (v1)");

    while (true) {
      this._HandleEvents();
      this.Sleep(1);
    }
  }

  function Save() { return {}; }
  function Load(version, data) {}

  // ---------------------------------------------------------------------------
  // Event loop
  // ---------------------------------------------------------------------------

  function _HandleEvents() {
    while (GSEventController.IsEventWaiting()) {
      local event = GSEventController.GetNextEvent();
      if (event == null) continue;
      if (event.GetEventType() != GSEvent.ET_ADMIN_PORT) continue;

      local admin_event = GSEventAdminPort.Convert(event);
      local data = admin_event.GetObject();

      if (data == null || !("id" in data) || !("action" in data)) {
        GSLog.Warning("Invalid command: missing id or action");
        continue;
      }

      local result = this._Dispatch(data);
      this._SendResponse(data.id, result);
    }
  }

  // ---------------------------------------------------------------------------
  // Response sending with automatic chunking
  // ---------------------------------------------------------------------------

  function _SendResponse(id, result) {
    // Chunk large array results
    if ("success" in result && result.success &&
        "result" in result && result.result != null &&
        typeof result.result == "array" && result.result.len() > this.CHUNK_SIZE) {

      local arr = result.result;
      local total = ((arr.len() - 1) / this.CHUNK_SIZE) + 1;

      for (local ci = 0; ci < total; ci++) {
        local start = ci * this.CHUNK_SIZE;
        local end = start + this.CHUNK_SIZE;
        if (end > arr.len()) end = arr.len();

        local chunk = [];
        for (local i = start; i < end; i++) {
          chunk.append(arr[i]);
        }

        GSAdmin.Send({
          id = id,
          success = true,
          result = chunk,
          _chunk = ci,
          _total = total
        });
      }
      return;
    }

    // Single-packet response
    local resp = { id = id };
    if ("success" in result) resp.rawset("success", result.success);
    if ("error" in result && result.error != null) resp.rawset("error", result.error);
    if ("result" in result && result.result != null) resp.rawset("result", result.result);
    GSAdmin.Send(resp);
  }

  // ---------------------------------------------------------------------------
  // Command dispatch
  // ---------------------------------------------------------------------------

  function _Dispatch(cmd) {
    local action = cmd.action;
    local p = ("params" in cmd) ? cmd.params : {};

    try {
      switch (action) {
        // Queries
        case "ping":              return { success = true, result = { pong = true } };
        case "get_date":          return this.CmdGetDate();
        case "get_map_size":      return this.CmdGetMapSize();
        case "get_tile_info":     return this.CmdGetTileInfo(p);
        case "get_towns":         return this.CmdGetTowns();
        case "get_town_info":     return this.CmdGetTownInfo(p);
        case "get_industries":    return this.CmdGetIndustries();
        case "get_industry_info": return this.CmdGetIndustryInfo(p);
        case "get_companies":     return this.CmdGetCompanies();
        case "get_stations":      return this.CmdGetStations(p);
        case "get_vehicles":      return this.CmdGetVehicles(p);
        case "get_engines":       return this.CmdGetEngines(p);
        case "get_cargo_types":   return this.CmdGetCargoTypes();
        case "get_rail_types":    return this.CmdGetRailTypes();
        case "get_road_types":    return this.CmdGetRoadTypes();

        // Smart queries
        case "scan_town_area":      return this.CmdScanTownArea(p);
        case "find_bus_stop_spots": return this.CmdFindBusStopSpots(p);
        case "find_depot_spots":    return this.CmdFindDepotSpots(p);

        // Building — road
        case "build_road":       return this.CmdBuildRoad(p);
        case "build_road_line":  return this.CmdBuildRoadLine(p);
        case "build_road_depot": return this.CmdBuildRoadDepot(p);
        case "build_road_stop":  return this.CmdBuildRoadStop(p);

        // Building — rail
        case "build_rail":         return this.CmdBuildRail(p);
        case "build_rail_station": return this.CmdBuildRailStation(p);
        case "build_rail_depot":   return this.CmdBuildRailDepot(p);
        case "build_rail_signal":  return this.CmdBuildRailSignal(p);

        // Building — other
        case "build_airport":  return this.CmdBuildAirport(p);
        case "build_dock":     return this.CmdBuildDock(p);
        case "build_bridge":   return this.CmdBuildBridge(p);
        case "build_tunnel":   return this.CmdBuildTunnel(p);
        case "demolish_tile":  return this.CmdDemolishTile(p);

        // Vehicles
        case "buy_vehicle":    return this.CmdBuyVehicle(p);
        case "sell_vehicle":   return this.CmdSellVehicle(p);
        case "start_vehicle":  return this.CmdStartVehicle(p);
        case "stop_vehicle":   return this.CmdStopVehicle(p);
        case "send_to_depot":  return this.CmdSendToDepot(p);
        case "clone_vehicle":  return this.CmdCloneVehicle(p);
        case "refit_vehicle":  return this.CmdRefitVehicle(p);

        // Orders
        case "add_order":  return this.CmdAddOrder(p);
        case "get_orders": return this.CmdGetOrders(p);

        default:
          return { success = false, error = "Unknown action: " + action };
      }
    } catch (e) {
      GSLog.Warning("Error in " + action + ": " + e);
      return { success = false, error = "" + e };
    }
  }

  // ===========================================================================
  // QUERY COMMANDS
  // ===========================================================================

  function CmdGetDate() {
    return { success = true, result = {
      date = GSDate.GetCurrentDate(),
      year = GSDate.GetYear(GSDate.GetCurrentDate()),
      month = GSDate.GetMonth(GSDate.GetCurrentDate()),
      day = GSDate.GetDayOfMonth(GSDate.GetCurrentDate())
    }};
  }

  function CmdGetMapSize() {
    return { success = true, result = {
      size_x = GSMap.GetMapSizeX(),
      size_y = GSMap.GetMapSizeY(),
      max_x = GSMap.GetMapSizeX() - 2,
      max_y = GSMap.GetMapSizeY() - 2
    }};
  }

  function CmdGetTileInfo(p) {
    local tile = GSMap.GetTileIndex(p.x, p.y);
    if (!GSMap.IsValidTile(tile)) {
      return { success = false, error = "Invalid tile" };
    }

    return { success = true, result = {
      x = p.x, y = p.y,
      height = GSTile.GetMaxHeight(tile),
      min_height = GSTile.GetMinHeight(tile),
      slope = GSTile.GetSlope(tile),
      is_buildable = GSTile.IsBuildable(tile),
      is_water = GSTile.IsWaterTile(tile),
      is_coast = GSTile.IsCoastTile(tile),
      has_tree = GSTile.HasTreeOnTile(tile),
      owner = GSTile.GetOwner(tile)
    }};
  }

  function CmdGetTowns() {
    local towns = [];
    local list = GSTownList();
    foreach (id, _ in list) {
      local loc = GSTown.GetLocation(id);
      towns.append({
        id = id,
        name = GSTown.GetName(id),
        population = GSTown.GetPopulation(id),
        x = GSMap.GetTileX(loc),
        y = GSMap.GetTileY(loc)
      });
    }
    return { success = true, result = towns };
  }

  function CmdGetTownInfo(p) {
    if (!GSTown.IsValidTown(p.town_id)) {
      return { success = false, error = "Invalid town ID" };
    }
    local loc = GSTown.GetLocation(p.town_id);
    return { success = true, result = {
      id = p.town_id,
      name = GSTown.GetName(p.town_id),
      population = GSTown.GetPopulation(p.town_id),
      houses = GSTown.GetHouseCount(p.town_id),
      x = GSMap.GetTileX(loc),
      y = GSMap.GetTileY(loc),
      is_city = GSTown.IsCity(p.town_id),
      growth_rate = GSTown.GetGrowthRate(p.town_id)
    }};
  }

  function CmdGetIndustries() {
    local industries = [];
    local list = GSIndustryList();
    foreach (id, _ in list) {
      local loc = GSIndustry.GetLocation(id);
      local itype = GSIndustry.GetIndustryType(id);
      industries.append({
        id = id,
        name = GSIndustry.GetName(id),
        type_id = itype,
        type_name = GSIndustryType.GetName(itype),
        x = GSMap.GetTileX(loc),
        y = GSMap.GetTileY(loc)
      });
    }
    return { success = true, result = industries };
  }

  function CmdGetIndustryInfo(p) {
    if (!GSIndustry.IsValidIndustry(p.industry_id)) {
      return { success = false, error = "Invalid industry ID" };
    }
    local loc = GSIndustry.GetLocation(p.industry_id);
    local itype = GSIndustry.GetIndustryType(p.industry_id);

    local produced = [];
    local cargo_list = GSCargoList();
    foreach (cargo_id, _ in cargo_list) {
      local last = GSIndustry.GetLastMonthProduction(p.industry_id, cargo_id);
      if (last > 0) {
        produced.append({
          cargo_id = cargo_id,
          cargo_label = GSCargo.GetCargoLabel(cargo_id),
          last_month = last,
          transported = GSIndustry.GetLastMonthTransported(p.industry_id, cargo_id)
        });
      }
    }

    return { success = true, result = {
      id = p.industry_id,
      name = GSIndustry.GetName(p.industry_id),
      type_id = itype,
      type_name = GSIndustryType.GetName(itype),
      x = GSMap.GetTileX(loc),
      y = GSMap.GetTileY(loc),
      is_raw = GSIndustryType.IsRawIndustry(itype),
      is_processing = GSIndustryType.IsProcessingIndustry(itype),
      production = produced
    }};
  }

  function CmdGetCompanies() {
    local companies = [];
    for (local cid = GSCompany.COMPANY_FIRST; cid <= GSCompany.COMPANY_LAST; cid++) {
      if (!GSCompany.ResolveCompanyID(cid)) continue;
      local hq = GSCompany.GetCompanyHQ(cid);
      companies.append({
        id = cid,
        name = GSCompany.GetName(cid),
        money = GSCompany.GetBankBalance(cid),
        loan = GSCompany.GetLoanAmount(cid),
        hq_x = GSMap.IsValidTile(hq) ? GSMap.GetTileX(hq) : -1,
        hq_y = GSMap.IsValidTile(hq) ? GSMap.GetTileY(hq) : -1
      });
    }
    return { success = true, result = companies };
  }

  function CmdGetStations(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local stations = [];
    local list = GSStationList(GSStation.STATION_ANY);
    foreach (id, _ in list) {
      local loc = GSBaseStation.GetLocation(id);
      stations.append({
        id = id,
        name = GSBaseStation.GetName(id),
        x = GSMap.GetTileX(loc),
        y = GSMap.GetTileY(loc),
        has_rail = GSStation.HasStationType(id, GSStation.STATION_TRAIN),
        has_truck = GSStation.HasStationType(id, GSStation.STATION_TRUCK_STOP),
        has_bus = GSStation.HasStationType(id, GSStation.STATION_BUS_STOP),
        has_airport = GSStation.HasStationType(id, GSStation.STATION_AIRPORT),
        has_dock = GSStation.HasStationType(id, GSStation.STATION_DOCK)
      });
    }
    return { success = true, result = stations };
  }

  function CmdGetVehicles(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local vehicles = [];
    local list = GSVehicleList();
    local filter_type = ("vehicle_type" in p) ? p.vehicle_type : null;

    foreach (id, _ in list) {
      if (filter_type != null) {
        local vt = GSVehicle.GetVehicleType(id);
        local tn = "";
        switch (vt) {
          case GSVehicle.VT_RAIL:  tn = "train"; break;
          case GSVehicle.VT_ROAD:  tn = "road"; break;
          case GSVehicle.VT_WATER: tn = "ship"; break;
          case GSVehicle.VT_AIR:   tn = "aircraft"; break;
        }
        if (tn != filter_type) continue;
      }

      local loc = GSVehicle.GetLocation(id);
      vehicles.append({
        id = id,
        name = GSVehicle.GetName(id),
        type = GSVehicle.GetVehicleType(id),
        x = GSMap.GetTileX(loc),
        y = GSMap.GetTileY(loc),
        engine_id = GSVehicle.GetEngineType(id),
        age = GSVehicle.GetAge(id),
        profit_this_year = GSVehicle.GetProfitThisYear(id),
        profit_last_year = GSVehicle.GetProfitLastYear(id),
        state = GSVehicle.GetState(id),
        in_depot = GSVehicle.IsStoppedInDepot(id),
        order_count = GSOrder.GetOrderCount(id)
      });
    }
    return { success = true, result = vehicles };
  }

  function CmdGetEngines(p) {
    local type_str = ("vehicle_type" in p) ? p.vehicle_type : "train";
    local vt = GSVehicle.VT_RAIL;
    switch (type_str) {
      case "train":    vt = GSVehicle.VT_RAIL; break;
      case "road":     vt = GSVehicle.VT_ROAD; break;
      case "ship":     vt = GSVehicle.VT_WATER; break;
      case "aircraft": vt = GSVehicle.VT_AIR; break;
    }

    local engines = [];
    local list = GSEngineList(vt);
    foreach (id, _ in list) {
      if (!GSEngine.IsBuildable(id)) continue;
      engines.append({
        id = id,
        name = GSEngine.GetName(id),
        cargo_type = GSEngine.GetCargoType(id),
        capacity = GSEngine.GetCapacity(id),
        max_speed = GSEngine.GetMaxSpeed(id),
        price = GSEngine.GetPrice(id),
        running_cost = GSEngine.GetRunningCost(id),
        power = GSEngine.GetPower(id),
        weight = GSEngine.GetWeight(id),
        reliability = GSEngine.GetReliability(id),
        is_wagon = GSEngine.IsWagon(id)
      });
    }
    return { success = true, result = engines };
  }

  function CmdGetCargoTypes() {
    local cargos = [];
    local list = GSCargoList();
    foreach (id, _ in list) {
      cargos.append({
        id = id,
        label = GSCargo.GetCargoLabel(id),
        name = GSCargo.GetName(id),
        is_freight = GSCargo.IsFreight(id)
      });
    }
    return { success = true, result = cargos };
  }

  function CmdGetRailTypes() {
    local types = [];
    local list = GSRailTypeList();
    foreach (id, _ in list) {
      types.append({ id = id, name = GSRail.GetName(id) });
    }
    return { success = true, result = types };
  }

  function CmdGetRoadTypes() {
    local types = [];
    local road_list = GSRoadTypeList(GSRoad.ROADTRAMTYPES_ROAD);
    foreach (id, _ in road_list) {
      types.append({ id = id, name = GSRoad.GetName(id), is_tram = false });
    }
    local tram_list = GSRoadTypeList(GSRoad.ROADTRAMTYPES_TRAM);
    foreach (id, _ in tram_list) {
      types.append({ id = id, name = GSRoad.GetName(id), is_tram = true });
    }
    return { success = true, result = types };
  }

  // ===========================================================================
  // SMART QUERY COMMANDS
  // ===========================================================================

  function CmdScanTownArea(p) {
    if (!GSTown.IsValidTown(p.town_id)) {
      return { success = false, error = "Invalid town ID" };
    }

    local radius = ("radius" in p) ? p.radius : 15;
    local loc = GSTown.GetLocation(p.town_id);
    local cx = GSMap.GetTileX(loc);
    local cy = GSMap.GetTileY(loc);

    local buildable = [];
    local roads = [];
    local buildings = [];
    local water = [];

    for (local dy = -radius; dy <= radius; dy++) {
      for (local dx = -radius; dx <= radius; dx++) {
        local x = cx + dx;
        local y = cy + dy;
        local tile = GSMap.GetTileIndex(x, y);
        if (!GSMap.IsValidTile(tile)) continue;

        if (GSTile.IsWaterTile(tile) || GSTile.IsCoastTile(tile)) {
          water.append({ x = x, y = y });
        } else if (GSRoad.IsRoadTile(tile)) {
          roads.append({ x = x, y = y });
        } else if (GSTile.IsBuildable(tile)) {
          buildable.append({
            x = x, y = y,
            height = GSTile.GetMaxHeight(tile),
            slope = GSTile.GetSlope(tile)
          });
        } else {
          buildings.append({ x = x, y = y });
        }
      }
    }

    return { success = true, result = {
      town_name = GSTown.GetName(p.town_id),
      center_x = cx, center_y = cy, radius = radius,
      buildable = buildable, roads = roads,
      buildings = buildings, water = water,
      counts = {
        buildable = buildable.len(), roads = roads.len(),
        buildings = buildings.len(), water = water.len()
      }
    }};
  }

  function CmdFindBusStopSpots(p) {
    if (!GSTown.IsValidTown(p.town_id)) {
      return { success = false, error = "Invalid town ID" };
    }

    local radius = ("radius" in p) ? p.radius : 15;
    local max_results = ("max_results" in p) ? p.max_results : 10;
    local loc = GSTown.GetLocation(p.town_id);
    local cx = GSMap.GetTileX(loc);
    local cy = GSMap.GetTileY(loc);
    local spots = [];

    for (local dy = -radius; dy <= radius; dy++) {
      for (local dx = -radius; dx <= radius; dx++) {
        local x = cx + dx;
        local y = cy + dy;
        local tile = GSMap.GetTileIndex(x, y);
        if (!GSMap.IsValidTile(tile)) continue;
        if (!GSTile.IsBuildable(tile)) continue;

        local adj = this._GetAdjacentRoads(x, y);
        if (adj.len() == 0) continue;

        spots.append({
          x = x, y = y,
          distance = abs(dx) + abs(dy),
          adjacent_road_x = adj[0].nx,
          adjacent_road_y = adj[0].ny,
          adjacent_road_count = adj.len()
        });
      }
    }

    this._SortByDistance(spots);
    if (spots.len() > max_results) spots = spots.slice(0, max_results);
    return { success = true, result = spots };
  }

  function CmdFindDepotSpots(p) {
    if (!GSTown.IsValidTown(p.town_id)) {
      return { success = false, error = "Invalid town ID" };
    }

    local radius = ("radius" in p) ? p.radius : 15;
    local max_results = ("max_results" in p) ? p.max_results : 5;
    local loc = GSTown.GetLocation(p.town_id);
    local cx = GSMap.GetTileX(loc);
    local cy = GSMap.GetTileY(loc);
    local spots = [];

    for (local dy = -radius; dy <= radius; dy++) {
      for (local dx = -radius; dx <= radius; dx++) {
        local x = cx + dx;
        local y = cy + dy;
        local tile = GSMap.GetTileIndex(x, y);
        if (!GSMap.IsValidTile(tile)) continue;
        if (!GSTile.IsBuildable(tile)) continue;

        local adj = this._GetAdjacentRoads(x, y);
        if (adj.len() == 0) continue;

        spots.append({
          x = x, y = y,
          distance = abs(dx) + abs(dy),
          adjacent_road_x = adj[0].nx,
          adjacent_road_y = adj[0].ny,
          depot_direction = adj[0].dir
        });
      }
    }

    this._SortByDistance(spots);
    if (spots.len() > max_results) spots = spots.slice(0, max_results);
    return { success = true, result = spots };
  }

  // ===========================================================================
  // BUILDING — ROAD
  // ===========================================================================

  function CmdBuildRoad(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local from_tile = GSMap.GetTileIndex(p.from_x, p.from_y);
    local to_tile = GSMap.GetTileIndex(p.to_x, p.to_y);
    local road_type = ("road_type" in p) ? p.road_type : 0;
    GSRoad.SetCurrentRoadType(road_type);

    if (GSRoad.BuildRoad(from_tile, to_tile)) {
      return { success = true, result = {
        from = [p.from_x, p.from_y], to = [p.to_x, p.to_y]
      }};
    }
    return { success = false, error = GSError.GetLastErrorString() };
  }

  function CmdBuildRoadLine(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local road_type = ("road_type" in p) ? p.road_type : 0;
    GSRoad.SetCurrentRoadType(road_type);

    local x1 = p.from_x, y1 = p.from_y;
    local x2 = p.to_x, y2 = p.to_y;

    if (x1 != x2 && y1 != y2) {
      return { success = false, error = "Only straight lines supported (same x or same y)" };
    }
    if (x1 == x2 && y1 == y2) {
      return { success = false, error = "Start and end are the same tile" };
    }

    local built = 0;
    local failed = [];

    if (x1 == x2) {
      local step = (y2 > y1) ? 1 : -1;
      for (local y = y1; ; y += step) {
        local ft = GSMap.GetTileIndex(x1, y);
        local tt = GSMap.GetTileIndex(x1, y + step);
        if (GSRoad.BuildRoad(ft, tt)) {
          built++;
        } else {
          local err = GSError.GetLastErrorString();
          if (err != "ERR_ALREADY_BUILT") {
            failed.append({ x = x1, y = y, error = err });
          } else {
            built++;
          }
        }
        if (y + step == y2) break;
      }
    } else {
      local step = (x2 > x1) ? 1 : -1;
      for (local x = x1; ; x += step) {
        local ft = GSMap.GetTileIndex(x, y1);
        local tt = GSMap.GetTileIndex(x + step, y1);
        if (GSRoad.BuildRoad(ft, tt)) {
          built++;
        } else {
          local err = GSError.GetLastErrorString();
          if (err != "ERR_ALREADY_BUILT") {
            failed.append({ x = x, y = y1, error = err });
          } else {
            built++;
          }
        }
        if (x + step == x2) break;
      }
    }

    return { success = true, result = {
      built = built, failed = failed, total = built + failed.len()
    }};
  }

  function CmdBuildRoadDepot(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local tile = GSMap.GetTileIndex(p.x, p.y);
    local road_type = ("road_type" in p) ? p.road_type : 0;
    local dir = ("direction" in p) ? p.direction : 0;
    GSRoad.SetCurrentRoadType(road_type);

    local front = this._GetAdjacentTile(tile, dir);
    if (GSRoad.BuildRoadDepot(tile, front)) {
      return { success = true, result = { tile = [p.x, p.y] } };
    }
    return { success = false, error = GSError.GetLastErrorString() };
  }

  function CmdBuildRoadStop(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local tile = GSMap.GetTileIndex(p.x, p.y);
    local road_type = ("road_type" in p) ? p.road_type : 0;
    local is_truck = ("is_truck_stop" in p) ? p.is_truck_stop : false;
    local is_dt = ("is_drive_through" in p) ? p.is_drive_through : false;
    local dir = ("direction" in p) ? p.direction : 0;
    GSRoad.SetCurrentRoadType(road_type);

    local front = this._GetAdjacentTile(tile, dir);
    local stop_type = is_truck ? GSRoad.ROADVEHTYPE_TRUCK : GSRoad.ROADVEHTYPE_BUS;

    local ok = false;
    if (is_dt) {
      ok = GSRoad.BuildDriveThroughRoadStation(tile, front, stop_type, GSStation.STATION_NEW);
    } else {
      ok = GSRoad.BuildRoadStation(tile, front, stop_type, GSStation.STATION_NEW);
    }

    if (ok) {
      return { success = true, result = {
        tile = [p.x, p.y],
        type = is_truck ? "truck" : "bus"
      }};
    }
    return { success = false, error = GSError.GetLastErrorString() };
  }

  // ===========================================================================
  // BUILDING — RAIL
  // ===========================================================================

  function CmdBuildRail(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local rail_type = ("rail_type" in p) ? p.rail_type : 0;
    GSRail.SetCurrentRailType(rail_type);

    // 3-tile mode: prev -> curr -> next
    if ("prev_x" in p && "x" in p && "next_x" in p) {
      local prev = GSMap.GetTileIndex(p.prev_x, p.prev_y);
      local curr = GSMap.GetTileIndex(p.x, p.y);
      local next = GSMap.GetTileIndex(p.next_x, p.next_y);
      if (GSRail.BuildRail(prev, curr, next)) {
        return { success = true, result = { tile = [p.x, p.y] } };
      }
      return { success = false, error = GSError.GetLastErrorString() };
    }

    // 2-tile mode: from -> to
    local from_tile = GSMap.GetTileIndex(p.from_x, p.from_y);
    local to_tile = GSMap.GetTileIndex(p.to_x, p.to_y);
    local dx = p.to_x - p.from_x;
    local dy = p.to_y - p.from_y;
    local before = GSMap.GetTileIndex(p.from_x - dx, p.from_y - dy);
    local after = GSMap.GetTileIndex(p.to_x + dx, p.to_y + dy);
    local ok1 = GSRail.BuildRail(before, from_tile, to_tile);
    local ok2 = GSRail.BuildRail(from_tile, to_tile, after);

    if (ok1 || ok2) {
      return { success = true, result = {
        from = [p.from_x, p.from_y], to = [p.to_x, p.to_y]
      }};
    }
    return { success = false, error = GSError.GetLastErrorString() };
  }

  function CmdBuildRailStation(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local tile = GSMap.GetTileIndex(p.x, p.y);
    local rail_type = ("rail_type" in p) ? p.rail_type : 0;
    local dir = ("direction" in p) ? p.direction : 0;
    local platforms = ("num_platforms" in p) ? p.num_platforms : 2;
    local length = ("platform_length" in p) ? p.platform_length : 5;
    GSRail.SetCurrentRailType(rail_type);

    local track = (dir == 1) ? GSRail.RAILTRACK_NW_SE : GSRail.RAILTRACK_NE_SW;
    if (GSRail.BuildRailStation(tile, track, platforms, length, GSStation.STATION_NEW)) {
      return { success = true, result = {
        tile = [p.x, p.y], platforms = platforms, length = length
      }};
    }
    return { success = false, error = GSError.GetLastErrorString() };
  }

  function CmdBuildRailDepot(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local tile = GSMap.GetTileIndex(p.x, p.y);
    local rail_type = ("rail_type" in p) ? p.rail_type : 0;
    local dir = ("direction" in p) ? p.direction : 0;
    GSRail.SetCurrentRailType(rail_type);

    local front = this._GetAdjacentTile(tile, dir);
    if (GSRail.BuildRailDepot(tile, front)) {
      return { success = true, result = { tile = [p.x, p.y] } };
    }
    return { success = false, error = GSError.GetLastErrorString() };
  }

  function CmdBuildRailSignal(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local tile = GSMap.GetTileIndex(p.x, p.y);
    local signal_type = ("signal_type" in p) ? p.signal_type : 0;

    if (GSRail.BuildSignal(tile, tile, signal_type)) {
      return { success = true, result = { tile = [p.x, p.y] } };
    }
    return { success = false, error = GSError.GetLastErrorString() };
  }

  // ===========================================================================
  // BUILDING — OTHER
  // ===========================================================================

  function CmdBuildAirport(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local tile = GSMap.GetTileIndex(p.x, p.y);
    local airport_type = ("airport_type" in p) ? p.airport_type : 0;

    if (GSAirport.BuildAirport(tile, airport_type, GSStation.STATION_NEW)) {
      return { success = true, result = { tile = [p.x, p.y], type = airport_type } };
    }
    return { success = false, error = GSError.GetLastErrorString() };
  }

  function CmdBuildDock(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local tile = GSMap.GetTileIndex(p.x, p.y);

    if (GSMarine.BuildDock(tile, GSStation.STATION_NEW)) {
      return { success = true, result = { tile = [p.x, p.y] } };
    }
    return { success = false, error = GSError.GetLastErrorString() };
  }

  function CmdBuildBridge(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local start_tile = GSMap.GetTileIndex(p.start_x, p.start_y);
    local end_tile = GSMap.GetTileIndex(p.end_x, p.end_y);
    local bridge_type = ("bridge_type" in p) ? p.bridge_type : 0;
    local transport = ("transport_type" in p) ? p.transport_type : "road";

    local vt = GSVehicle.VT_ROAD;
    if (transport == "rail") vt = GSVehicle.VT_RAIL;
    else if (transport == "water") vt = GSVehicle.VT_WATER;

    if (GSBridge.BuildBridge(vt, bridge_type, start_tile, end_tile)) {
      return { success = true, result = {
        start = [p.start_x, p.start_y], end_pos = [p.end_x, p.end_y]
      }};
    }
    return { success = false, error = GSError.GetLastErrorString() };
  }

  function CmdBuildTunnel(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local tile = GSMap.GetTileIndex(p.x, p.y);
    local transport = ("transport_type" in p) ? p.transport_type : "rail";

    local vt = GSVehicle.VT_RAIL;
    if (transport == "road") vt = GSVehicle.VT_ROAD;

    if (GSTunnel.BuildTunnel(vt, tile)) {
      local exit_tile = GSTunnel.GetOtherTunnelEnd(tile);
      return { success = true, result = {
        entrance = [p.x, p.y],
        exit_pos = [GSMap.GetTileX(exit_tile), GSMap.GetTileY(exit_tile)]
      }};
    }
    return { success = false, error = GSError.GetLastErrorString() };
  }

  function CmdDemolishTile(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local tile = GSMap.GetTileIndex(p.x, p.y);

    if (GSTile.DemolishTile(tile)) {
      return { success = true, result = { tile = [p.x, p.y] } };
    }
    return { success = false, error = GSError.GetLastErrorString() };
  }

  // ===========================================================================
  // VEHICLE COMMANDS
  // ===========================================================================

  function CmdBuyVehicle(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local depot_tile = GSMap.GetTileIndex(p.depot_x, p.depot_y);

    local vid = GSVehicle.BuildVehicle(depot_tile, p.engine_id);
    if (GSVehicle.IsValidVehicle(vid)) {
      return { success = true, result = {
        vehicle_id = vid, name = GSVehicle.GetName(vid)
      }};
    }
    local err = GSError.GetLastErrorString();
    if (err == "ERR_NONE" && GSEngine.IsWagon(p.engine_id)) {
      return { success = true, result = {
        vehicle_id = vid, note = "Wagon auto-attached to train in depot"
      }};
    }
    return { success = false, error = err };
  }

  function CmdSellVehicle(p) {
    local company_mode = GSCompanyMode(p.company_id);
    if (GSVehicle.SellVehicle(p.vehicle_id)) {
      return { success = true, result = {} };
    }
    return { success = false, error = GSError.GetLastErrorString() };
  }

  function CmdStartVehicle(p) {
    local company_mode = GSCompanyMode(p.company_id);
    if (GSVehicle.StartStopVehicle(p.vehicle_id)) {
      return { success = true, result = {
        running = !GSVehicle.IsStoppedInDepot(p.vehicle_id)
      }};
    }
    return { success = false, error = GSError.GetLastErrorString() };
  }

  function CmdStopVehicle(p) {
    local company_mode = GSCompanyMode(p.company_id);
    if (GSVehicle.IsStoppedInDepot(p.vehicle_id)) {
      return { success = true, result = { already_stopped = true } };
    }
    if (GSVehicle.StartStopVehicle(p.vehicle_id)) {
      return { success = true, result = {} };
    }
    return { success = false, error = GSError.GetLastErrorString() };
  }

  function CmdSendToDepot(p) {
    local company_mode = GSCompanyMode(p.company_id);
    if (GSVehicle.SendVehicleToDepot(p.vehicle_id)) {
      return { success = true, result = {} };
    }
    return { success = false, error = GSError.GetLastErrorString() };
  }

  function CmdCloneVehicle(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local depot = GSVehicle.GetLocation(p.vehicle_id);
    local share = ("share_orders" in p) ? p.share_orders : true;

    local cid = GSVehicle.CloneVehicle(depot, p.vehicle_id, share);
    if (GSVehicle.IsValidVehicle(cid)) {
      return { success = true, result = {
        vehicle_id = cid, name = GSVehicle.GetName(cid)
      }};
    }
    return { success = false, error = GSError.GetLastErrorString() };
  }

  function CmdRefitVehicle(p) {
    local company_mode = GSCompanyMode(p.company_id);
    if (GSVehicle.RefitVehicle(p.vehicle_id, p.cargo_id)) {
      return { success = true, result = {} };
    }
    return { success = false, error = GSError.GetLastErrorString() };
  }

  // ===========================================================================
  // ORDER COMMANDS
  // ===========================================================================

  function CmdAddOrder(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local flags = ("order_flags" in p) ? p.order_flags : 0;
    local dest = GSStation.GetLocation(p.station_id);
    if (!GSMap.IsValidTile(dest)) {
      return { success = false, error = "Invalid station_id" };
    }

    if (GSOrder.AppendOrder(p.vehicle_id, dest, flags)) {
      return { success = true, result = {
        order_count = GSOrder.GetOrderCount(p.vehicle_id)
      }};
    }
    return { success = false, error = GSError.GetLastErrorString() };
  }

  function CmdGetOrders(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local vid = p.vehicle_id;
    local count = GSOrder.GetOrderCount(vid);
    local orders = [];

    for (local i = 0; i < count; i++) {
      orders.append({
        index = i,
        destination = GSOrder.GetOrderDestination(vid, i),
        flags = GSOrder.GetOrderFlags(vid, i)
      });
    }

    return { success = true, result = {
      vehicle_id = vid, order_count = count, orders = orders
    }};
  }

  // ===========================================================================
  // UTILITY FUNCTIONS
  // ===========================================================================

  function _GetAdjacentTile(tile, direction) {
    switch (direction) {
      case 0: return tile + GSMap.GetTileIndex(1, 0) - GSMap.GetTileIndex(0, 0);
      case 1: return tile + GSMap.GetTileIndex(0, 1) - GSMap.GetTileIndex(0, 0);
      case 2: return tile - (GSMap.GetTileIndex(1, 0) - GSMap.GetTileIndex(0, 0));
      case 3: return tile - (GSMap.GetTileIndex(0, 1) - GSMap.GetTileIndex(0, 0));
    }
    return tile;
  }

  function _GetAdjacentRoads(x, y) {
    local offsets = [
      { dx = 1,  dy = 0,  dir = 0 },
      { dx = 0,  dy = 1,  dir = 1 },
      { dx = -1, dy = 0,  dir = 2 },
      { dx = 0,  dy = -1, dir = 3 }
    ];
    local results = [];
    foreach (o in offsets) {
      local nx = x + o.dx;
      local ny = y + o.dy;
      local t = GSMap.GetTileIndex(nx, ny);
      if (GSMap.IsValidTile(t) && GSRoad.IsRoadTile(t)) {
        results.append({ nx = nx, ny = ny, dir = o.dir });
      }
    }
    return results;
  }

  function _SortByDistance(arr) {
    for (local i = 1; i < arr.len(); i++) {
      local key = arr[i];
      local j = i - 1;
      while (j >= 0 && arr[j].distance > key.distance) {
        arr[j + 1] = arr[j];
        j--;
      }
      arr[j + 1] = key;
    }
  }
}
