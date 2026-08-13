// nttd GameScript: bridge between the nttd API server and OpenTTD.
//
// Copyright 2026 deepsaia. Licensed under the Apache License, Version 2.0.
// See LICENSE at the repository root. NOTICE records why this file's license
// warrants particular attention: it runs inside OpenTTD's Squirrel VM against
// OpenTTD's GPL-2.0 GS* API.
//
// Receives JSON commands from the admin port, executes them in-game,
// and sends JSON responses back. Large array responses are automatically
// chunked to stay under the ~1400 byte admin port packet limit.
//
// Command:  { "id": "gs_1", "action": "get_towns", "params": { ... } }
// Response: { "id": "gs_1", "success": true, "result": { ... } }
// Chunked:  { "id": "gs_1", "success": true, "result": [...], "_chunk": 0, "_total": 3 }

class NttdGS extends GSController {
  CHUNK_SIZE = 10;

  // Days in transit assumed when a caller does not say. Payment falls off with time, so
  // comparing corridors needs one number held constant across them, and an agent choosing
  // a route does not yet own a vehicle to measure with. Twenty days is roughly a
  // mid-length haul by early road vehicle, which is the pessimistic end and therefore the
  // safer default for a decision about whether a route is worth building.
  _DEFAULT_TRANSIT_DAYS = 20;
  _pathfind_queue = null;
  _event_names = null;

  function Start() {
    GSLog.Info("nttd GameScript v1 started");
    this._pathfind_queue = [];
    this._event_names = {};
    this._event_names[GSEvent.ET_VEHICLE_CRASHED]       <- "vehicle_crashed";
    this._event_names[GSEvent.ET_VEHICLE_LOST]          <- "vehicle_lost";
    this._event_names[GSEvent.ET_VEHICLE_UNPROFITABLE]  <- "vehicle_unprofitable";
    this._event_names[GSEvent.ET_VEHICLE_WAITING_IN_DEPOT] <- "vehicle_waiting_in_depot";
    this._event_names[GSEvent.ET_VEHICLE_AUTOREPLACED]  <- "vehicle_autoreplaced";
    this._event_names[GSEvent.ET_AIRCRAFT_DEST_TOO_FAR] <- "aircraft_dest_too_far";
    this._event_names[GSEvent.ET_SUBSIDY_OFFER]         <- "subsidy_offered";
    this._event_names[GSEvent.ET_SUBSIDY_OFFER_EXPIRED] <- "subsidy_offer_expired";
    this._event_names[GSEvent.ET_SUBSIDY_AWARDED]       <- "subsidy_awarded";
    this._event_names[GSEvent.ET_SUBSIDY_EXPIRED]       <- "subsidy_expired";
    this._event_names[GSEvent.ET_INDUSTRY_OPEN]         <- "industry_open";
    this._event_names[GSEvent.ET_INDUSTRY_CLOSE]        <- "industry_close";
    this._event_names[GSEvent.ET_TOWN_FOUNDED]          <- "town_founded";
    this._event_names[GSEvent.ET_ENGINE_PREVIEW]        <- "engine_preview";
    this._event_names[GSEvent.ET_ENGINE_AVAILABLE]      <- "engine_available";
    this._event_names[GSEvent.ET_COMPANY_NEW]           <- "company_new";
    this._event_names[GSEvent.ET_COMPANY_IN_TROUBLE]    <- "company_in_trouble";
    this._event_names[GSEvent.ET_COMPANY_ASK_MERGER]    <- "company_ask_merger";
    this._event_names[GSEvent.ET_COMPANY_MERGER]        <- "company_merger";
    this._event_names[GSEvent.ET_COMPANY_BANKRUPT]      <- "company_bankrupt";
    this._event_names[GSEvent.ET_STATION_FIRST_VEHICLE] <- "station_first_vehicle";
    this._event_names[GSEvent.ET_EXCLUSIVE_TRANSPORT_RIGHTS] <- "exclusive_transport_rights";
    this._event_names[GSEvent.ET_ROAD_RECONSTRUCTION]   <- "road_reconstruction";
    this._event_names[GSEvent.ET_DISASTER_ZEPPELINER_CRASHED] <- "disaster_zeppeliner_crashed";
    this._event_names[GSEvent.ET_DISASTER_ZEPPELINER_CLEARED] <- "disaster_zeppeliner_cleared";
    this._event_names[GSEvent.ET_COMPANY_RENAMED]      <- "company_renamed";
    this._event_names[GSEvent.ET_PRESIDENT_RENAMED]    <- "president_renamed";
    while (true) {
      this._HandleEvents();
      // Process pathfinding commands that were queued during a prior pathfind yield.
      while (this._pathfind_queue.len() > 0) {
        local cmd = this._pathfind_queue.remove(0);
        local result = null;
        try {
          result = this._Dispatch(cmd);
        } catch (e) {
          GSLog.Error("nttd: command " + cmd.action + " threw: " + e);
          result = { success = false, error = "internal error: " + e };
        }
        this._SendResponse(cmd.id, result);
      }
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

      local et = event.GetEventType();

      // Admin port commands: our primary input channel
      if (et == GSEvent.ET_ADMIN_PORT) {
        local admin_event = GSEventAdminPort.Convert(event);
        local data = admin_event.GetObject();

        if (data == null || !("id" in data) || !("action" in data)) {
          GSLog.Warning("nttd: invalid command (missing id or action)");
          continue;
        }

        local result = null;
        try {
          result = this._Dispatch(data);
        } catch (e) {
          GSLog.Error("nttd: command " + data.action + " threw: " + e);
          result = { success = false, error = "internal error: " + e };
        }
        this._SendResponse(data.id, result);
        continue;
      }

      // Forward all other game events to nttd
      this._ForwardGameEvent(event, et);
    }
  }

  // ---------------------------------------------------------------------------
  // Yield point for pathfinding: process pending events between A* chunks.
  // Called from _FindRoadPath / _FindRailPath every 500 iterations instead of
  // plain Sleep(1). Non-pathfinding commands execute immediately so other agents
  // aren't blocked. New pathfinding commands are queued for sequential execution.
  // ---------------------------------------------------------------------------

  function _YieldAndProcessEvents() {
    this.Sleep(1);
    // GSExecMode overrides the GSTestMode from the calling pathfinder so that
    // dispatched commands (buy_vehicle, add_order, etc.) execute for real.
    local exec_mode = GSExecMode();
    while (GSEventController.IsEventWaiting()) {
      local event = GSEventController.GetNextEvent();
      if (event == null) continue;
      local et = event.GetEventType();

      if (et == GSEvent.ET_ADMIN_PORT) {
        local admin_event = GSEventAdminPort.Convert(event);
        local data = admin_event.GetObject();
        if (data == null || !("id" in data) || !("action" in data)) {
          GSLog.Warning("nttd: invalid command (missing id or action)");
          continue;
        }
        // Queue pathfinding commands: they run after the current pathfind completes.
        if (data.action == "connect_road" || data.action == "connect_rail") {
          this._pathfind_queue.append(data);
          continue;
        }
        // Execute all other commands immediately.
        local result = null;
        try {
          result = this._Dispatch(data);
        } catch (e) {
          GSLog.Error("nttd: command " + data.action + " threw: " + e);
          result = { success = false, error = "internal error: " + e };
        }
        this._SendResponse(data.id, result);
      } else {
        this._ForwardGameEvent(event, et);
      }
    }
  }

  function _ForwardGameEvent(event, et) {
    local name = (et in this._event_names) ? this._event_names[et] : ("event_" + et);
    local payload = { _event = true, event_type = name };
    GSLog.Info("nttd: game event " + name + " (type=" + et + ")");

    try {
      switch (et) {
        case GSEvent.ET_VEHICLE_CRASHED: {
          local e = GSEventVehicleCrash.Convert(event);
          payload.rawset("vehicle_id", e.GetVehicleID());
          payload.rawset("crash_site", e.GetCrashSite());
          break;
        }
        case GSEvent.ET_VEHICLE_LOST: {
          local e = GSEventVehicleLost.Convert(event);
          payload.rawset("vehicle_id", e.GetVehicleID());
          break;
        }
        case GSEvent.ET_VEHICLE_UNPROFITABLE: {
          local e = GSEventVehicleUnprofitable.Convert(event);
          payload.rawset("vehicle_id", e.GetVehicleID());
          break;
        }
        case GSEvent.ET_SUBSIDY_OFFER: {
          local e = GSEventSubsidyOffer.Convert(event);
          payload.rawset("subsidy_id", e.GetSubsidyID());
          break;
        }
        case GSEvent.ET_SUBSIDY_OFFER_EXPIRED: {
          local e = GSEventSubsidyOfferExpired.Convert(event);
          payload.rawset("subsidy_id", e.GetSubsidyID());
          break;
        }
        case GSEvent.ET_SUBSIDY_AWARDED: {
          local e = GSEventSubsidyAwarded.Convert(event);
          payload.rawset("subsidy_id", e.GetSubsidyID());
          break;
        }
        case GSEvent.ET_SUBSIDY_EXPIRED: {
          local e = GSEventSubsidyExpired.Convert(event);
          payload.rawset("subsidy_id", e.GetSubsidyID());
          break;
        }
        case GSEvent.ET_INDUSTRY_OPEN: {
          local e = GSEventIndustryOpen.Convert(event);
          payload.rawset("industry_id", e.GetIndustryID());
          break;
        }
        case GSEvent.ET_INDUSTRY_CLOSE: {
          local e = GSEventIndustryClose.Convert(event);
          payload.rawset("industry_id", e.GetIndustryID());
          break;
        }
        case GSEvent.ET_TOWN_FOUNDED: {
          local e = GSEventTownFounded.Convert(event);
          payload.rawset("town_id", e.GetTownID());
          break;
        }
        case GSEvent.ET_COMPANY_NEW: {
          local e = GSEventCompanyNew.Convert(event);
          payload.rawset("company_id", e.GetCompanyID());
          break;
        }
        case GSEvent.ET_COMPANY_IN_TROUBLE: {
          local e = GSEventCompanyInTrouble.Convert(event);
          payload.rawset("company_id", e.GetCompanyID());
          break;
        }
        case GSEvent.ET_COMPANY_BANKRUPT: {
          local e = GSEventCompanyBankrupt.Convert(event);
          payload.rawset("company_id", e.GetCompanyID());
          break;
        }
        case GSEvent.ET_COMPANY_MERGER: {
          local e = GSEventCompanyMerger.Convert(event);
          payload.rawset("old_company_id", e.GetOldCompanyID());
          payload.rawset("new_company_id", e.GetNewCompanyID());
          break;
        }
        case GSEvent.ET_STATION_FIRST_VEHICLE: {
          local e = GSEventStationFirstVehicle.Convert(event);
          payload.rawset("station_id", e.GetStationID());
          payload.rawset("vehicle_id", e.GetVehicleID());
          break;
        }
        case GSEvent.ET_VEHICLE_WAITING_IN_DEPOT: {
          local e = GSEventVehicleWaitingInDepot.Convert(event);
          payload.rawset("vehicle_id", e.GetVehicleID());
          break;
        }
        case GSEvent.ET_VEHICLE_AUTOREPLACED: {
          local e = GSEventVehicleAutoReplaced.Convert(event);
          payload.rawset("old_vehicle_id", e.GetOldVehicleID());
          payload.rawset("new_vehicle_id", e.GetNewVehicleID());
          break;
        }
        case GSEvent.ET_AIRCRAFT_DEST_TOO_FAR: {
          local e = GSEventAircraftDestTooFar.Convert(event);
          payload.rawset("vehicle_id", e.GetVehicleID());
          break;
        }
        case GSEvent.ET_ENGINE_AVAILABLE: {
          local e = GSEventEngineAvailable.Convert(event);
          payload.rawset("engine_id", e.GetEngineID());
          break;
        }
        case GSEvent.ET_COMPANY_ASK_MERGER: {
          local e = GSEventCompanyAskMerger.Convert(event);
          payload.rawset("company_id", e.GetCompanyID());
          payload.rawset("value", e.GetValue());
          break;
        }
        case GSEvent.ET_ENGINE_PREVIEW: {
          local e = GSEventEnginePreview.Convert(event);
          payload.rawset("engine_name", e.GetName());
          break;
        }
        case GSEvent.ET_EXCLUSIVE_TRANSPORT_RIGHTS: {
          local e = GSEventExclusiveTransportRights.Convert(event);
          payload.rawset("company_id", e.GetCompanyID());
          payload.rawset("town_id", e.GetTownID());
          break;
        }
        case GSEvent.ET_ROAD_RECONSTRUCTION: {
          local e = GSEventRoadReconstruction.Convert(event);
          payload.rawset("company_id", e.GetCompanyID());
          payload.rawset("town_id", e.GetTownID());
          break;
        }
        case GSEvent.ET_DISASTER_ZEPPELINER_CRASHED: {
          local e = GSEventDisasterZeppelinerCrashed.Convert(event);
          payload.rawset("station_id", e.GetStationID());
          break;
        }
        case GSEvent.ET_DISASTER_ZEPPELINER_CLEARED: {
          local e = GSEventDisasterZeppelinerCleared.Convert(event);
          payload.rawset("station_id", e.GetStationID());
          break;
        }
        case GSEvent.ET_COMPANY_RENAMED: {
          local e = GSEventCompanyRenamed.Convert(event);
          payload.rawset("company_id", e.GetCompanyID());
          break;
        }
        case GSEvent.ET_PRESIDENT_RENAMED: {
          local e = GSEventPresidentRenamed.Convert(event);
          payload.rawset("company_id", e.GetCompanyID());
          break;
        }
        default:
          break;
      }
    } catch (e) {
      GSLog.Warning("nttd: could not process event type " + et + ": " + e);
    }

    GSAdmin.Send(payload);
  }

  // ---------------------------------------------------------------------------
  // Response sending: automatic chunking for large arrays
  // ---------------------------------------------------------------------------

  // Roughly how many characters of JSON fit in one admin packet. The real limit is
  // about 1400 bytes; this leaves room for the envelope and for the estimate being an
  // estimate rather than a serialisation.
  BUDGET = 1000;

  // An approximate serialised size, walking the structure. Squirrel has no json encoder,
  // and the whole point is to decide BEFORE encoding, so this counts characters the way
  // an encoder would spend them. Depth is bounded because a cyclic structure would
  // otherwise hang the game.
  function _ApproxSize(value, depth) {
    if (depth > 6) return 8;
    local kind = typeof value;
    if (kind == "array") {
      local total = 2;
      foreach (item in value) total += this._ApproxSize(item, depth + 1) + 1;
      return total;
    }
    if (kind == "table") {
      local total = 2;
      foreach (key, item in value) {
        total += key.len() + 3 + this._ApproxSize(item, depth + 1) + 1;
      }
      return total;
    }
    if (kind == "string") return value.len() + 2;
    if (kind == "bool") return 5;
    if (kind == "null") return 4;
    return 8;   // a number, generously
  }

  // The array a reply is mostly made of, if it has one, and how big it is. A handler may
  // return the array directly as `result`, or a table carrying it under one key alongside
  // some scalars, which is what get_map_terrain does with `rows` and find_station_spot
  // with `spots`.
  //
  // The size comes back with the key so the caller does not walk the same structure
  // twice. This runs on every reply, including the largest one in the system, and
  // measuring it is not free.
  function _Bulk(result) {
    if (typeof result == "array") {
      return { key = null, arr = result, size = this._ApproxSize(result, 0) };
    }
    if (typeof result != "table") return { key = null, arr = null, size = 0 };
    local best = null;
    local best_arr = null;
    local best_size = 0;
    foreach (key, value in result) {
      if (typeof value != "array") continue;
      local size = this._ApproxSize(value, 0);
      if (size > best_size) { best = key; best_arr = value; best_size = size; }
    }
    return { key = best, arr = best_arr, size = best_size };
  }

  function _SendResponse(id, result) {
    // Chunk on SIZE, not on shape.
    //
    // This used to chunk only when `result.result` was an array. Every handler that
    // returns a table instead, with the bulk of the reply nested inside it, therefore
    // sent the whole thing in one packet. get_map_terrain is the worst case: a single
    // row of a 256 wide map is about 2000 characters, so no band size was ever safe. The
    // oversized packet desynced the admin stream, and once that happened every later
    // reply was lost or delivered to the wrong caller, which is what made action results
    // intermittently wrong. Measured at 247,869 unparseable packets in one session.
    // Size, and ONLY size. This used to be gated on success as well, which quietly
    // exempted the largest replies in the system from the rule they most needed.
    // connect_rail and connect_road put the whole route in `result.path` on the failure
    // branch too, so a partial build sent every tile it walked in one packet: a 36 tile
    // partial measures about 1514 by _ApproxSize, already past the 1000 budget, and past
    // the real ~1400 limit from roughly 55 tiles. The consequence is the one recorded
    // above, a desynced stream where every later reply is lost or misdelivered.
    if ("result" in result && result.result != null) {

      local payload = result.result;
      local bulk = this._Bulk(payload);

      if (bulk.arr != null && bulk.size > this.BUDGET) {
        // Everything except the bulk array travels with the first chunk, so a table
        // reply keeps its metadata. get_map_terrain's truncated and next_from_y are the
        // reason: an answer that lost them would look complete when it was not.
        local meta = null;
        if (bulk.key != null) {
          meta = {};
          foreach (key, value in payload) {
            if (key != bulk.key) meta.rawset(key, value);
          }
        }
        this._SendChunked(id, bulk.arr, bulk.key, meta, result);
        return;
      }
    }

    local resp = { id = id };
    if ("success" in result) resp.rawset("success", result.success);
    if ("error" in result && result.error != null) resp.rawset("error", result.error);
    if ("error_code" in result) resp.rawset("error_code", result.error_code);
    if ("error_category" in result) resp.rawset("error_category", result.error_category);
    if ("error_name" in result && result.error_name != null) {
      resp.rawset("error_name", result.error_name);
    }
    // The worked out explanation, when the game's own error was ERR_UNKNOWN. This list
    // is a whitelist, so a field not named here is silently dropped, which is how the
    // first attempt at this shipped a reason nobody ever saw.
    if ("reason" in result && result.reason != null) resp.rawset("reason", result.reason);
    if ("result" in result && result.result != null) resp.rawset("result", result.result);
    GSAdmin.Send(resp);
  }

  // Split one array across as many packets as its size needs.
  //
  // By size rather than by a fixed count, because elements differ by orders of
  // magnitude: a station spot is a few hundred characters and a terrain row is a few
  // thousand. A fixed count of ten was safe for the first and never for the second.
  //
  // An element larger than the budget on its own still goes alone in its packet. That is
  // the best this layer can do; a handler returning such an element has to divide it
  // itself, which is what get_map_terrain's max_tiles is for.
  function _SendChunked(id, arr, bulk_key, meta, source = null) {
    local groups = [];
    local current = [];
    local current_size = 0;
    foreach (item in arr) {
      local size = this._ApproxSize(item, 0) + 1;
      if (current.len() > 0 && current_size + size > this.BUDGET) {
        groups.append(current);
        current = [];
        current_size = 0;
      }
      current.append(item);
      current_size += size;
    }
    if (current.len() > 0) groups.append(current);
    if (groups.len() == 0) groups.append([]);

    for (local ci = 0; ci < groups.len(); ci++) {
      local packet = {
        id = id, success = true, result = groups[ci],
        _chunk = ci, _total = groups.len(),
      };
      // The shape is announced once. The reader rebuilds the table from it, and a reply
      // whose result was a plain array carries neither key, so it merges as before.
      //
      // The verdict rides with it. Now that a FAILED reply can be chunked, hardcoding
      // success = true here would turn every large partial into a reported success, which
      // is the opposite of the point.
      if (ci == 0) {
        if (source != null) {
          if ("success" in source) packet.rawset("success", source.success);
          if ("error" in source && source.error != null) packet.rawset("error", source.error);
          if ("error_code" in source) packet.rawset("error_code", source.error_code);
          if ("error_category" in source) packet.rawset("error_category", source.error_category);
          if ("error_name" in source && source.error_name != null) {
            packet.rawset("error_name", source.error_name);
          }
          if ("reason" in source && source.reason != null) packet.rawset("reason", source.reason);
        }
        if (bulk_key != null) {
          packet.rawset("_key", bulk_key);
          if (meta != null) packet.rawset("_meta", meta);
        }
      }
      GSAdmin.Send(packet);
    }
  }

  // ---------------------------------------------------------------------------
  // Command dispatch
  // ---------------------------------------------------------------------------

  function _Dispatch(cmd) {
    local action = cmd.action;
    local p = ("params" in cmd) ? cmd.params : {};

    // Auto-resolve tile → x,y for all commands.
    // If "tile" is provided but x,y are not, derive them.
    if ("tile" in p && !("x" in p)) {
      local tv = p.tile;
      if (typeof tv == "integer" || typeof tv == "float") {
        local t = tv.tointeger();
        if (GSMap.IsValidTile(t)) {
          p.rawset("x", GSMap.GetTileX(t));
          p.rawset("y", GSMap.GetTileY(t));
        }
      }
    }
    // Same for tile_from → from_x, from_y
    if ("tile_from" in p && !("from_x" in p)) {
      local tv = p.tile_from;
      if (typeof tv == "integer" || typeof tv == "float") {
        local t = tv.tointeger();
        if (GSMap.IsValidTile(t)) {
          p.rawset("from_x", GSMap.GetTileX(t));
          p.rawset("from_y", GSMap.GetTileY(t));
        }
      }
    }
    // Same for tile_to → to_x, to_y
    if ("tile_to" in p && !("to_x" in p)) {
      local tv = p.tile_to;
      if (typeof tv == "integer" || typeof tv == "float") {
        local t = tv.tointeger();
        if (GSMap.IsValidTile(t)) {
          p.rawset("to_x", GSMap.GetTileX(t));
          p.rawset("to_y", GSMap.GetTileY(t));
        }
      }
    }
    // depot_tile → depot_x, depot_y (for buy_vehicle, clone_vehicle)
    if ("depot_tile" in p && !("depot_x" in p)) {
      local tv = p.depot_tile;
      if (typeof tv == "integer" || typeof tv == "float") {
        local t = tv.tointeger();
        if (GSMap.IsValidTile(t)) {
          p.rawset("depot_x", GSMap.GetTileX(t));
          p.rawset("depot_y", GSMap.GetTileY(t));
        }
      }
    }
    // destination (for orders): resolve to tile
    if ("destination" in p) {
      local d = p.destination;
      if (typeof d == "integer" || typeof d == "float") {
        local t = d.tointeger();
        if (GSMap.IsValidTile(t)) {
          p.rawset("dest_tile", t);
        }
      }
    }

    // Reject null or non-numeric tile values before they reach command handlers.
    if ("tile" in p && (p.tile == null || (typeof p.tile != "integer" && typeof p.tile != "float"))) {
      return { success = false, error = "tile parameter is null or not a number -- use find_*_spots tools to get valid tile IDs" };
    }
    // If tile was given but x/y could not be resolved, fail early with a clear error.
    if ("tile" in p && !("x" in p)) {
      return { success = false, error = "Invalid tile ID: " + p.tile + " (not a valid map position)" };
    }

    try {
      switch (action) {

        // ---- QUERIES -------------------------------------------------------
        case "ping":              return { success = true, result = { pong = true } };
        case "get_date":          return this.CmdGetDate();
        case "get_map_size":      return this.CmdGetMapSize();
        case "get_tile_info":     return this.CmdGetTileInfo(p);
        case "get_towns":         return this.CmdGetTowns();
        case "get_town_info":     return this.CmdGetTownInfo(p);
        case "get_industries":    return this.CmdGetIndustries();
        case "get_industry_info": return this.CmdGetIndustryInfo(p);
        case "get_companies":     return this.CmdGetCompanies();
        case "get_company_finance": return this.CmdGetCompanyFinance(p);
        case "get_stations":      return this.CmdGetStations(p);
        case "get_station_info":  return this.CmdGetStationInfo(p);
        case "get_waypoints":     return this.CmdGetWaypoints(p);
        case "get_vehicles":      return this.CmdGetVehicles(p);
        case "get_vehicle_info":  return this.CmdGetVehicleInfo(p);
        case "get_engines":       return this.CmdGetEngines(p);
        case "get_cargo_types":   return this.CmdGetCargoTypes();
        case "get_cargo_income":  return this.CmdGetCargoIncome(p);
        case "get_rail_types":    return this.CmdGetRailTypes();
        case "get_road_types":    return this.CmdGetRoadTypes();
        case "get_groups":        return this.CmdGetGroups(p);
        case "get_signs":         return this.CmdGetSigns();
        case "get_subsidies":     return this.CmdGetSubsidies();
        case "get_airport_types": return this.CmdGetAirportTypes();
        case "get_bridge_types":  return this.CmdGetBridgeTypes();

        // ---- BULK / MAP QUERIES --------------------------------------------
        case "get_map_terrain":     return this.CmdGetMapTerrain(p);

        // ---- SMART QUERIES -------------------------------------------------
        case "scan_town_area":      return this.CmdScanTownArea(p);
        case "find_bus_stop_spots": return this.CmdFindBusStopSpots(p);
        case "find_depot_spots":    return this.CmdFindDepotSpots(p);
        case "find_rail_depot_spot": return this.CmdFindRailDepotSpot(p);
        case "find_airport_spots":  return this.CmdFindAirportSpots(p);
        case "find_dock_spots":     return this.CmdFindDockSpots(p);
        case "find_flat_spots":     return this.CmdFindFlatSpots(p);
        case "find_station_spot": return this.CmdFindStationSpot(p);
        case "get_hangars":         return this.CmdGetHangars(p);
        case "find_water_depot_spots": return this.CmdFindWaterDepotSpots(p);

        // ---- BUILDING: ROAD ------------------------------------------------
        case "build_road_depot":  return this.CmdBuildRoadDepot(p);
        case "build_road_stop":   return this.CmdBuildRoadStop(p);
        case "remove_road":       return this.CmdRemoveRoad(p);
        case "remove_road_depot": return this.CmdRemoveRoadDepot(p);
        case "remove_road_stop":  return this.CmdRemoveRoadStop(p);
        case "connect_road":      return this.CmdConnectRoad(p);

        // ---- BUILDING: RAIL ------------------------------------------------
        case "build_rail_station":  return this.CmdBuildRailStation(p);
        case "build_rail_depot":    return this.CmdBuildRailDepot(p);
        case "build_rail_signal":   return this.CmdBuildRailSignal(p);
        case "build_rail_waypoint": return this.CmdBuildRailWaypoint(p);
        case "build_rail_track":    return this.CmdBuildRailTrack(p);
        case "remove_rail":         return this.CmdRemoveRail(p);
        case "remove_rail_track":   return this.CmdRemoveRailTrack(p);
        case "remove_signal":       return this.CmdRemoveSignal(p);
        case "remove_rail_station": return this.CmdRemoveRailStation(p);
        case "convert_rail":        return this.CmdConvertRail(p);
        case "connect_rail":        return this.CmdConnectRail(p);

        // ---- BUILDING: MARINE ----------------------------------------------
        case "build_canal":        return this.CmdBuildCanal(p);
        case "build_lock":         return this.CmdBuildLock(p);
        case "build_buoy":         return this.CmdBuildBuoy(p);
        case "build_water_depot":  return this.CmdBuildWaterDepot(p);
        case "remove_canal":       return this.CmdRemoveCanal(p);
        case "remove_lock":        return this.CmdRemoveLock(p);
        case "remove_buoy":        return this.CmdRemoveBuoy(p);
        case "remove_water_depot": return this.CmdRemoveWaterDepot(p);

        // ---- BUILDING: OTHER -----------------------------------------------
        case "build_airport":     return this.CmdBuildAirport(p);
        case "remove_airport":    return this.CmdRemoveAirport(p);
        case "open_close_airport":return this.CmdOpenCloseAirport(p);
        case "build_dock":        return this.CmdBuildDock(p);
        case "build_bridge":      return this.CmdBuildBridge(p);
        case "build_tunnel":      return this.CmdBuildTunnel(p);
        case "build_path":        return this.CmdBuildPath(p);
        case "demolish_tile":     return this.CmdDemolishTile(p);

        // ---- COMPANY -------------------------------------------------------
        case "build_company_hq":  return this.CmdBuildCompanyHQ(p);
        case "set_loan":          return this.CmdSetLoan(p);
        case "rename_company":    return this.CmdRenameCompany(p);

        // ---- TOWN (GS-exclusive) -------------------------------------------
        case "found_town":          return this.CmdFoundTown(p);
        case "expand_town":         return this.CmdExpandTown(p);
        case "set_town_growth":     return this.CmdSetTownGrowth(p);
        case "perform_town_action": return this.CmdPerformTownAction(p);
        case "get_town_rating":     return this.CmdGetTownRating(p);
        case "change_town_rating":  return this.CmdChangeTownRating(p);
        case "set_cargo_goal":      return this.CmdSetCargoGoal(p);

        // ---- SUBSIDIES (GS-exclusive) --------------------------------------
        case "create_subsidy": return this.CmdCreateSubsidy(p);

        // ---- SIGNS ---------------------------------------------------------
        case "build_sign":  return this.CmdBuildSign(p);
        case "remove_sign": return this.CmdRemoveSign(p);

        // ---- VEHICLE GROUPS ------------------------------------------------
        case "create_group":     return this.CmdCreateGroup(p);
        case "delete_group":     return this.CmdDeleteGroup(p);
        case "move_to_group":    return this.CmdMoveToGroup(p);
        case "set_auto_replace": return this.CmdSetAutoReplace(p);

        // ---- VEHICLES ------------------------------------------------------
        case "buy_vehicle":          return this.CmdBuyVehicle(p);
        case "build_train":          return this.CmdBuildTrain(p);
        case "sell_vehicle":         return this.CmdSellVehicle(p);
        case "sell_wagon":           return this.CmdSellWagon(p);
        case "move_wagon":           return this.CmdMoveWagon(p);
        case "start_vehicle":        return this.CmdStartVehicle(p);
        case "stop_vehicle":         return this.CmdStopVehicle(p);
        case "send_to_depot":        return this.CmdSendToDepot(p);
        case "send_to_depot_service":return this.CmdSendToDepotService(p);
        case "clone_vehicle":        return this.CmdCloneVehicle(p);
        case "refit_vehicle":        return this.CmdRefitVehicle(p);
        case "reverse_vehicle":      return this.CmdReverseVehicle(p);
        case "rename_vehicle":       return this.CmdRenameVehicle(p);

        // ---- ORDERS --------------------------------------------------------
        case "add_order":       return this.CmdAddOrder(p);
        case "insert_order":    return this.CmdInsertOrder(p);
        case "remove_order":    return this.CmdRemoveOrder(p);
        case "skip_to_order":   return this.CmdSkipToOrder(p);
        case "move_order":      return this.CmdMoveOrder(p);
        case "set_order_flags": return this.CmdSetOrderFlags(p);
        case "share_orders":    return this.CmdShareOrders(p);
        case "copy_orders":     return this.CmdCopyOrders(p);
        case "get_orders":      return this.CmdGetOrders(p);

        // ---- GAME SETTINGS (2.2.1-2.2.2) ----------------------------------
        case "get_game_settings":  return this.CmdGetGameSettings(p);
        case "set_game_setting":   return this.CmdSetGameSetting(p);

        // ---- FINANCIAL QUERIES (2.2.3-2.2.6) ------------------------------
        case "get_expense_breakdown":    return this.CmdGetExpenseBreakdown(p);
        case "get_infrastructure_costs": return this.CmdGetInfrastructureCosts(p);
        case "get_cargo_flows":          return this.CmdGetCargoFlows(p);
        case "estimate_cost":            return this.CmdEstimateCost(p);

        // ---- CLIENTS (2.2.7) ----------------------------------------------
        case "get_clients":     return this.CmdGetClients();

        // ---- DEITY FINANCE (2.2.8-2.2.9) ----------------------------------
        case "change_bank_balance": return this.CmdChangeBankBalance(p);
        case "set_max_loan":        return this.CmdSetMaxLoan(p);

        // ---- TERRAFORM (2.2.11) -------------------------------------------
        case "raise_tile":   return this.CmdRaiseTile(p);
        case "lower_tile":   return this.CmdLowerTile(p);
        case "level_tiles":  return this.CmdLevelTiles(p);

        // ---- TREES (2.2.12) -----------------------------------------------
        case "plant_tree":           return this.CmdPlantTree(p);
        case "plant_tree_rectangle": return this.CmdPlantTreeRectangle(p);

        // ---- ROAD ADVANCED (2.2.13-2.2.14) --------------------------------
        case "build_one_way_road":      return this.CmdBuildOneWayRoad(p);
        case "build_one_way_road_full": return this.CmdBuildOneWayRoadFull(p);
        case "convert_road_type":       return this.CmdConvertRoadType(p);

        // ---- CONDITIONAL ORDERS (2.2.10) ----------------------------------
        case "set_order_condition":        return this.CmdSetOrderCondition(p);
        case "set_order_compare_function": return this.CmdSetOrderCompareFunction(p);
        case "set_order_compare_value":    return this.CmdSetOrderCompareValue(p);
        case "set_stop_location":          return this.CmdSetStopLocation(p);

        // ---- ENGINE DETAILS (2.2.16) --------------------------------------
        case "get_engine_details": return this.CmdGetEngineDetails(p);

        // ---- TILE AREA (2.4.6) -------------------------------------------
        case "get_tile_area": return this.CmdGetTileArea(p);

        // ---- EXISTING CONNECTIVITY -----------------------------------------
        case "trace_route": return this.CmdTraceRoute(p);

        default:
          return { success = false, error = "Unknown action: " + action };
      }
    } catch (e) {
      GSLog.Warning("nttd error in '" + action + "': " + e);
      return this._Uncaught(action, "" + e);
    }
  }

  // A Squirrel exception, turned into something a caller can act on.
  //
  // Nearly all of these are one mistake: a handler read p.<field> for an argument that was
  // not supplied. Squirrel answers "the index 'town_id' does not exist", which names the
  // field but reads like an internal fault, and is identical to the message you get when a
  // handler calls a member that is not on the class. 57 handlers dereference an id that
  // way, so translating it here fixes all of them at once rather than guarding each.
  //
  // A parameter name is lower case with underscores. A member name is CamelCase. That is
  // enough to tell the caller's mistake from ours, and to say which it was.
  function _Uncaught(action, message) {
    local opening = message.find("'");
    if (message.find("the index '") == 0 && opening != null) {
      local closing = message.find("'", opening + 1);
      if (closing != null) {
        local name = message.slice(opening + 1, closing);
        if (name == name.tolower()) {
          return { success = false, error = message,
                   reason = action + " requires the parameter '" + name
                          + "', and it was not supplied" };
        }
        return { success = false, error = message,
                 reason = "nttd called '" + name + "' on a GameScript class that does not "
                        + "provide it, which is a bug in nttd rather than in this request" };
      }
    }
    return { success = false, error = message };
  }

  // ===========================================================================
  // QUERY COMMANDS
  // ===========================================================================

  function CmdGetDate() {
    local d = GSDate.GetCurrentDate();
    return { success = true, result = {
      date = d,
      year = GSDate.GetYear(d),
      month = GSDate.GetMonth(d),
      day = GSDate.GetDayOfMonth(d)
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
    if (!GSMap.IsValidTile(tile)) return { success = false, error = "Invalid tile" };
    return { success = true, result = {
      x = p.x, y = p.y,
      height = GSTile.GetMaxHeight(tile),
      min_height = GSTile.GetMinHeight(tile),
      slope = GSTile.GetSlope(tile),
      is_buildable = GSTile.IsBuildable(tile),
      is_water = GSTile.IsWaterTile(tile),
      is_coast = GSTile.IsCoastTile(tile),
      has_tree = GSTile.HasTreeOnTile(tile),
      is_road = GSRoad.IsRoadTile(tile),
      is_rail = GSRail.IsRailTile(tile),
      is_station = GSStation.GetStationID(tile) != GSStation.STATION_INVALID,
      // A crossing used to read as owned, unbuildable, and nothing else, which is
      // uninterpretable exactly where the interesting structure is. The far end comes with
      // it, because that is what a route needs in order to go over or around one.
      is_bridge = GSBridge.IsBridgeTile(tile),
      is_tunnel = GSTunnel.IsTunnelTile(tile),
      other_end = GSBridge.IsBridgeTile(tile) ? GSBridge.GetOtherBridgeEnd(tile)
                : (GSTunnel.IsTunnelTile(tile) ? GSTunnel.GetOtherTunnelEnd(tile) : null),
      owner = GSTile.GetOwner(tile)
    }};
  }

  function CmdGetMapTerrain(p) {
    // Terrain across a band of the map, row by row.
    // Each result item: { y, tiles: [[height, slope, flags, owner], ...] }
    // flags bitmask: 1=water, 2=coast, 4=buildable, and with occupancy=true also
    //                8=rail, 16=road, 32=station, 64=tree, 128=bridge, 256=tunnel
    //
    // Occupancy and ownership travel in this compact encoding rather than as named
    // fields. Terrain alone says whether ground is flat and dry; it cannot say whether a
    // tile is taken, whose the track on it is, or where a line already runs, which is
    // most of what deciding a route needs. get_tile_area answers all of that but names
    // every field, so one tile costs about 150 characters against this encoding's 12. A
    // full scan read that way swamped the admin protocol and starved the game.
    //
    // BOUNDED, at every map size. It used to default to the whole map, which is not a
    // reasonable thing to ask for or to answer: 256x256 measured 524 KB and 7.2s, which
    // is around 389,000 tokens, and no agent can hold that. At 512x512 the reply
    // exceeded gs_query's timeout and returned a bare failure; 1024x1024 is worse again.
    //
    // The cap is on TILES rather than on map size, so the same rule holds everywhere and
    // no size needs forbidding. An agent that wants more asks again for the next band,
    // which is also the shape that lets it stop once it has found what it needed.
    //
    // Terrain is rarely the right question anyway. Where something fits is answered by
    // the find_* family, which dry-runs the real build inside the game.
    local max_x = GSMap.GetMapSizeX() - 2;
    local max_y = GSMap.GetMapSizeY() - 2;
    // Occupancy costs seven extra API calls per tile, and Squirrel is slow enough that a
    // large band of them blocks the script long enough for other commands to time out.
    // Measured: a 20,000 tile band with occupancy on starved the game so thoroughly that
    // renaming the company timed out at session start.
    //
    // Off by default, which is also what the startup scan wants: nothing is built yet, so
    // every one of those checks would return empty at a cost of a quarter of a million
    // calls. Ask for it when reading a region that has been developed.
    local occupancy = ("occupancy" in p) ? p.occupancy : false;
    local max_tiles = ("max_tiles" in p) ? p.max_tiles : 4000;
    if (max_tiles > 20000) max_tiles = 20000;
    local from_y = ("from_y" in p) ? p.from_y : 1;
    local to_y = ("to_y" in p) ? p.to_y : max_y;
    if (from_y < 1) from_y = 1;
    if (to_y > max_y) to_y = max_y;

    // Rows are full width, so the band is trimmed to whole rows that fit the budget.
    local per_row = max_x;
    local allowed_rows = (per_row > 0) ? (max_tiles / per_row) : 1;
    if (allowed_rows < 1) allowed_rows = 1;
    local truncated = false;
    if (to_y - from_y + 1 > allowed_rows) {
      to_y = from_y + allowed_rows - 1;
      truncated = true;
    }

    local rows = [];
    for (local y = from_y; y <= to_y; y++) {
      local row_tiles = [];
      for (local x = 1; x <= max_x; x++) {
        local tile = GSMap.GetTileIndex(x, y);
        local flags = 0;
        if (GSTile.IsWaterTile(tile)) flags = flags | 1;
        if (GSTile.IsCoastTile(tile)) flags = flags | 2;
        if (GSTile.IsBuildable(tile))  flags = flags | 4;
        local owner = -1;
        if (occupancy) {
          if (GSRail.IsRailTile(tile)) flags = flags | 8;
          if (GSRoad.IsRoadTile(tile)) flags = flags | 16;
          if (GSStation.GetStationID(tile) != GSStation.STATION_INVALID) flags = flags | 32;
          if (GSTile.HasTreeOnTile(tile)) flags = flags | 64;
          if (GSBridge.IsBridgeTile(tile)) flags = flags | 128;
          if (GSTunnel.IsTunnelTile(tile)) flags = flags | 256;
          owner = GSTile.GetOwner(tile);
        }
        row_tiles.append([GSTile.GetMaxHeight(tile), GSTile.GetSlope(tile), flags, owner]);
      }
      rows.append({ y = y, tiles = row_tiles });
    }
    // The caller is told when the band was cut short, and where to resume. Returning a
    // short answer that looks complete is the failure this whole handler was rewritten
    // to avoid.
    return { success = true, result = {
      rows = rows,
      from_y = from_y,
      to_y = to_y,
      truncated = truncated,
      next_from_y = truncated ? to_y + 1 : null,
      tiles_returned = rows.len() * per_row,
    }};
  }

  function CmdGetTowns() {
    local towns = [];
    foreach (id, _ in GSTownList()) {
      local loc = GSTown.GetLocation(id);
      towns.append({
        id = id, name = GSTown.GetName(id),
        population = GSTown.GetPopulation(id),
        x = GSMap.GetTileX(loc), y = GSMap.GetTileY(loc)
      });
    }
    return { success = true, result = towns };
  }

  // Whether a vehicle can travel from one tile to another over track that ALREADY EXISTS.
  //
  // A different question from the build planner behind /state/path, and the one that decides
  // whether a route earns anything. The planner routes AROUND occupied tiles, correctly for
  // its own purpose, so once a line is standing the corridor it would have used is blocked
  // and it reports no path over a route that works. Measured: a corridor answered connected
  // true before the build and connected false afterwards, with the line standing.
  //
  // Answered by walking the game's own AreTilesConnected rather than by testing has_rail on
  // adjacent tiles. Adjacency is not connectivity: track laid without a hint sits beside a
  // platform pointing away from it, and every cheap approximation of this in the project so
  // far has reported a dead route as a working one.
  //
  // Bounded by the size of the rail network rather than the map, because it only ever steps
  // onto tiles that already carry track.
  function CmdTraceRoute(p) {
    local pair = this._ResolveTilePair(p);
    if (pair == null) {
      return { success = false,
               error = "Need from_x,from_y and to_x,to_y, or tile_from and tile_to" };
    }
    local kind = ("transport_type" in p) ? p.transport_type : "rail";
    if (kind != "rail" && kind != "road") {
      return { success = false,
               error = "trace_route answers rail and road. A ship travels over open water, "
                     + "so a track walk does not describe it." };
    }
    local max_iter = ("max_iterations" in p) ? p.max_iterations : 20000;
    local start = pair.from.tile;
    local goal = pair.to.tile;

    local dir_dx = [1, 0, -1, 0];
    local dir_dy = [0, 1, 0, -1];
    local seen = {};
    local queue = [];
    local reached = false;
    local visited_tiles = {};
    local steps = 0;

    // A rail state is a tile plus the direction it was entered from, because
    // AreTilesConnected asks about a triple and a train may not reverse. Road has no such
    // constraint, so its state is the tile alone, entered as direction 0.
    for (local d = 0; d < 4; d++) {
      local key = start * 4 + d;
      seen[key] <- true;
      queue.append({ tile = start, dir = d });
      if (kind == "road") break;
    }
    visited_tiles[start] <- true;

    local head = 0;
    while (head < queue.len() && steps < max_iter) {
      steps++;
      if (steps % 500 == 0) this._YieldAndProcessEvents();
      local node = queue[head];
      head++;
      if (node.tile == goal) { reached = true; break; }

      local cx = GSMap.GetTileX(node.tile), cy = GSMap.GetTileY(node.tile);
      local reverse = (node.dir + 2) % 4;
      for (local exit_dir = 0; exit_dir < 4; exit_dir++) {
        if (kind == "rail" && exit_dir == reverse) continue;
        local nx = cx + dir_dx[exit_dir], ny = cy + dir_dy[exit_dir];
        local next = GSMap.GetTileIndex(nx, ny);
        if (!GSMap.IsValidTile(next)) continue;
        local key = (kind == "road") ? next * 4 : next * 4 + exit_dir;
        if (key in seen) continue;

        local joined = false;
        if (kind == "road") {
          joined = GSRoad.IsRoadTile(next) && GSRoad.AreRoadTilesConnected(node.tile, next);
        } else {
          local prev = GSMap.GetTileIndex(cx - dir_dx[node.dir], cy - dir_dy[node.dir]);
          if (!GSMap.IsValidTile(prev)) prev = node.tile;
          joined = (GSRail.IsRailTile(next) || GSRail.IsRailStationTile(next)
                    || GSRail.IsRailDepotTile(next))
                   && GSRail.AreTilesConnected(prev, node.tile, next);
        }
        if (!joined) continue;
        seen[key] <- true;
        visited_tiles[next] <- true;
        queue.append({ tile = next, dir = exit_dir });
      }
    }

    local reachable = 0;
    foreach (_, __ in visited_tiles) reachable++;
    return { success = true, result = {
      line_exists = reached,
      transport_type = kind,
      from_x = pair.from.x, from_y = pair.from.y,
      to_x = pair.to.x, to_y = pair.to.y,
      // How much of the network the walk could reach from the start. A route that stops
      // short says where the reachable part ends, which is the repair an agent needs.
      tiles_reachable = reachable,
      steps = steps,
      exhausted = (steps >= max_iter),
    }};
  }

  function CmdGetTownInfo(p) {
    if (!GSTown.IsValidTown(p.town_id)) return { success = false, error = "Invalid town ID" };
    local loc = GSTown.GetLocation(p.town_id);

    // What the town actually trades, which is the whole reason to build here.
    //
    // A town produces passengers and mail continuously and accepts them at any station in
    // its catchment, so two stations and a train is a working route with no supply chain to
    // reason about. It is the first thing a human builds and nothing here said so: this
    // reply carried population and road_layout and not one word about cargo, so an agent
    // reasoning from it could not tell a town was worth anything at all.
    //
    // Rates are last month's, per cargo, so a town that has never been served still reports
    // what it produces rather than nothing.
    local produced = [];
    local accepted = [];
    foreach (cargo_id, _ in GSCargoList()) {
      local last = GSTown.GetLastMonthProduction(p.town_id, cargo_id);
      if (last > 0) {
        produced.append({
          cargo_id = cargo_id, cargo_label = GSCargo.GetCargoLabel(cargo_id),
          last_month = last,
          // GSTown names these differently from GSIndustry: supplied, and a percentage.
          // GetLastMonthTransported is the industry call and does not exist here, which is
          // how the first version of this threw on its own first loop.
          supplied = GSTown.GetLastMonthSupplied(p.town_id, cargo_id),
          transported_percent =
            GSTown.GetLastMonthTransportedPercentage(p.town_id, cargo_id),
        });
      }
      if (GSTown.GetCargoGoal(p.town_id, cargo_id) > 0) {
        accepted.append({
          cargo_id = cargo_id, cargo_label = GSCargo.GetCargoLabel(cargo_id),
          goal = GSTown.GetCargoGoal(p.town_id, cargo_id),
        });
      }
    }

    return { success = true, result = {
      produces_cargo = produced,
      accepts_cargo = accepted,
      id = p.town_id,
      name = GSTown.GetName(p.town_id),
      population = GSTown.GetPopulation(p.town_id),
      houses = GSTown.GetHouseCount(p.town_id),
      x = GSMap.GetTileX(loc), y = GSMap.GetTileY(loc),
      is_city = GSTown.IsCity(p.town_id),
      growth_rate = GSTown.GetGrowthRate(p.town_id),
      has_statue = GSTown.HasStatue(p.town_id),
      road_layout = GSTown.GetRoadLayout(p.town_id),
      exclusive_rights_company = GSTown.GetExclusiveRightsCompany(p.town_id),
      exclusive_rights_duration = GSTown.GetExclusiveRightsDuration(p.town_id),
      fund_buildings_duration = GSTown.GetFundBuildingsDuration(p.town_id)
    }};
  }

  function CmdGetTownRating(p) {
    if (!GSTown.IsValidTown(p.town_id)) return { success = false, error = "Invalid town ID" };
    local cid = p.company_id;
    return { success = true, result = {
      town_id = p.town_id,
      company_id = cid,
      rating = GSTown.GetRating(p.town_id, cid),
      detailed_rating = GSTown.GetDetailedRating(p.town_id, cid)
    }};
  }

  function CmdGetIndustries() {
    local industries = [];
    foreach (id, _ in GSIndustryList()) {
      local loc = GSIndustry.GetLocation(id);
      local itype = GSIndustry.GetIndustryType(id);
      // Collect production and accepted cargo for each industry
      local produced = [];
      foreach (cargo_id, _ in GSCargoList()) {
        local last = GSIndustry.GetLastMonthProduction(id, cargo_id);
        if (last > 0) {
          produced.append({
            cargo_id = cargo_id,
            cargo_label = GSCargo.GetCargoLabel(cargo_id),
            last_month = last,
            transported = GSIndustry.GetLastMonthTransported(id, cargo_id)
          });
        }
      }
      local accepted_list = [];
      foreach (cargo_id, _ in GSCargoList()) {
        if (GSIndustry.IsCargoAccepted(id, cargo_id)) {
          accepted_list.append({
            cargo_id = cargo_id,
            cargo_label = GSCargo.GetCargoLabel(cargo_id)
          });
        }
      }
      industries.append({
        id = id, name = GSIndustry.GetName(id),
        type_id = itype, type_name = GSIndustryType.GetName(itype),
        x = GSMap.GetTileX(loc), y = GSMap.GetTileY(loc),
        is_raw = GSIndustryType.IsRawIndustry(itype),
        is_processing = GSIndustryType.IsProcessingIndustry(itype),
        production = produced,
        accepted = accepted_list,
      });
    }
    return { success = true, result = industries };
  }

  function CmdGetIndustryInfo(p) {
    if (!GSIndustry.IsValidIndustry(p.industry_id)) return { success = false, error = "Invalid industry ID" };
    local loc = GSIndustry.GetLocation(p.industry_id);
    local itype = GSIndustry.GetIndustryType(p.industry_id);
    local produced = [];
    foreach (cargo_id, _ in GSCargoList()) {
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
    local accepted = [];
    foreach (cargo_id, _ in GSCargoList()) {
      if (GSIndustry.IsCargoAccepted(p.industry_id, cargo_id)) {
        accepted.append({
          cargo_id = cargo_id,
          cargo_label = GSCargo.GetCargoLabel(cargo_id),
          stockpile = GSIndustry.GetStockpiledCargo(p.industry_id, cargo_id)
        });
      }
    }

    // What this KIND of industry produces, as opposed to what this one shipped last month.
    //
    // `produced` above is built from GetLastMonthProduction, which is 0 before an industry
    // has ever run. So at the start of a game every factory, sawmill and power station
    // reported producing nothing, and an agent could not learn a processing industry's
    // output cargo at the one moment it has to choose what to build. Measured: Tontburg
    // Springs Factory reported accepted STEL, GRAI, LVST and production [], while it makes
    // GOOD, a fact the tile level cargo scan knew all along.
    local produces_types = [];
    foreach (cargo_id, _ in GSIndustryType.GetProducedCargo(itype)) {
      produces_types.append({
        cargo_id = cargo_id, cargo_label = GSCargo.GetCargoLabel(cargo_id),
      });
    }
    local accepts_types = [];
    foreach (cargo_id, _ in GSIndustryType.GetAcceptedCargo(itype)) {
      accepts_types.append({
        cargo_id = cargo_id, cargo_label = GSCargo.GetCargoLabel(cargo_id),
      });
    }
    return { success = true, result = {
      id = p.industry_id, name = GSIndustry.GetName(p.industry_id),
      type_id = itype, type_name = GSIndustryType.GetName(itype),
      x = GSMap.GetTileX(loc), y = GSMap.GetTileY(loc),
      is_raw = GSIndustryType.IsRawIndustry(itype),
      is_processing = GSIndustryType.IsProcessingIndustry(itype),
      // Last month's figures. Empty for an industry that has not run yet.
      production = produced,
      accepted = accepted,
      // What this kind of industry produces and takes, regardless of whether it has yet.
      // This is the pair to reason about a supply chain from on day one.
      produces_cargo = produces_types,
      accepts_cargo = accepts_types
    }};
  }

  function CmdGetCompanies() {
    local companies = [];
    for (local cid = GSCompany.COMPANY_FIRST; cid <= GSCompany.COMPANY_LAST; cid++) {
      if (GSCompany.ResolveCompanyID(cid) == GSCompany.COMPANY_INVALID) continue;
      local cm = GSCompanyMode(cid);
      local hq = GSCompany.GetCompanyHQ(cid);
      companies.append({
        id = cid, name = GSCompany.GetName(cid),
        money = GSCompany.GetBankBalance(cid),
        loan = GSCompany.GetLoanAmount(),
        max_loan = GSCompany.GetMaxLoanAmount(),
        hq_x = GSMap.IsValidTile(hq) ? GSMap.GetTileX(hq) : -1,
        hq_y = GSMap.IsValidTile(hq) ? GSMap.GetTileY(hq) : -1,
        // Quarter 1, the last COMPLETED quarter, not quarter 0.
        //
        // Quarter 0 is the quarter in progress, and OpenTTD does not rate one until it
        // ends, so it answers -1 forever. Measured live: at 1960-04-01, one quarter into
        // a run, q0 gave -1 while q1 gave 30. Every snapshot nttd had ever written
        // recorded -1, and every result row scored 0.
        //
        // company_value stays on quarter 0 deliberately. It is not a rating and the
        // current quarter answers it correctly: the same probe returned 1 for q0.
        performance_rating = GSCompany.GetQuarterlyPerformanceRating(cid, 1),
        company_value = GSCompany.GetQuarterlyCompanyValue(cid, 0),
        q0_income = GSCompany.GetQuarterlyIncome(cid, 0),
        q0_expenses = GSCompany.GetQuarterlyExpenses(cid, 0),
        q0_cargo = GSCompany.GetQuarterlyCargoDelivered(cid, 0),
      });
    }
    return { success = true, result = companies };
  }

  function CmdGetCompanyFinance(p) {
    local cid = p.company_id;
    if (GSCompany.ResolveCompanyID(cid) == GSCompany.COMPANY_INVALID) return { success = false, error = "Invalid company ID" };
    local cm = GSCompanyMode(cid);
    return { success = true, result = {
      company_id = cid,
      balance = GSCompany.GetBankBalance(cid),
      loan = GSCompany.GetLoanAmount(),
      max_loan = GSCompany.GetMaxLoanAmount(),
      q1_income = GSCompany.GetQuarterlyIncome(cid, 1),
      q1_expenses = GSCompany.GetQuarterlyExpenses(cid, 1),
      q1_value = GSCompany.GetQuarterlyCompanyValue(cid, 1),
      q2_income = GSCompany.GetQuarterlyIncome(cid, 2),
      q2_expenses = GSCompany.GetQuarterlyExpenses(cid, 2),
      q2_value = GSCompany.GetQuarterlyCompanyValue(cid, 2)
    }};
  }

  function CmdGetStations(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local stations = [];
    foreach (id, _ in GSStationList(GSStation.STATION_ANY)) {
      local loc = GSBaseStation.GetLocation(id);
      local cw = [];
      local ca = [];
      foreach (cargo_id, _ in GSCargoList()) {
        local w = GSStation.GetCargoWaiting(id, cargo_id);
        if (w > 0) {
          cw.append({
            cargo_id = cargo_id,
            cargo_label = GSCargo.GetCargoLabel(cargo_id),
            waiting = w
          });
        }
        local has_rating = GSStation.HasCargoRating(id, cargo_id);
        local acc = GSTile.GetCargoAcceptance(loc, cargo_id, 1, 1, 4);
        local prod = GSTile.GetCargoProduction(loc, cargo_id, 1, 1, 4);
        if (acc >= 8 || prod > 0 || has_rating) {
          ca.append({
            cargo_id = cargo_id,
            cargo_label = GSCargo.GetCargoLabel(cargo_id),
            accepts = acc >= 8,
            produces = prod > 0,
            supply = prod,
            rated = has_rating
          });
        }
      }
      stations.append({
        id = id, name = GSBaseStation.GetName(id),
        x = GSMap.GetTileX(loc), y = GSMap.GetTileY(loc),
        has_rail = GSStation.HasStationType(id, GSStation.STATION_TRAIN),
        has_truck = GSStation.HasStationType(id, GSStation.STATION_TRUCK_STOP),
        has_bus = GSStation.HasStationType(id, GSStation.STATION_BUS_STOP),
        has_airport = GSStation.HasStationType(id, GSStation.STATION_AIRPORT),
        has_dock = GSStation.HasStationType(id, GSStation.STATION_DOCK),
        cargo_waiting = cw,
        cargo_acceptance = ca
      });
    }
    return { success = true, result = stations };
  }

  function CmdGetStationInfo(p) {
    if (!GSStation.IsValidStation(p.station_id)) return { success = false, error = "Invalid station ID" };
    local loc = GSBaseStation.GetLocation(p.station_id);
    local cargo_waiting = [];
    foreach (cargo_id, _ in GSCargoList()) {
      local waiting = GSStation.GetCargoWaiting(p.station_id, cargo_id);
      if (waiting > 0) {
        cargo_waiting.append({
          cargo_id = cargo_id,
          cargo_label = GSCargo.GetCargoLabel(cargo_id),
          waiting = waiting,
          rating = GSStation.GetCargoRating(p.station_id, cargo_id)
        });
      }
    }
    // Which way the platforms run, and where a train can get in.
    //
    // Without this an agent cannot tell whether track it laid can actually be used. A
    // platform is a line with an axis, and a train enters at either end; track against its
    // side connects to nothing however adjacent it looks. Every route in this project
    // earned nothing for exactly that reason, and nothing in the observation surface would
    // have shown it.
    //
    // A rail station has TWO orientations, not four: the axis its platforms lie along.
    // Things entered from one side, such as road stops and depots, are the four direction
    // case, and they are not this.
    local orientation = null;
    local entry_tiles = [];
    if (GSRail.IsRailStationTile(loc)) {
      local along_x = (GSRail.GetRailStationDirection(loc) == GSRail.RAILTRACK_NE_SW);
      orientation = along_x ? "x" : "y";
      foreach (candidate in this._RailStationEntries(loc)) {
        local entry = candidate.entry;
        entry_tiles.append({
          tile = entry, x = GSMap.GetTileX(entry), y = GSMap.GetTileY(entry),
          has_rail = GSRail.IsRailTile(entry),
          // Whether a train can actually get from here into the platform. has_rail is not
          // that, and the difference is a route that earns nothing: track laid without a
          // hint sits on the entry pointing away from the station.
          enterable = this._CanEnterPlatform(entry, candidate.platform),
          // Whether track could be laid here at all, for an entry that is still empty.
          usable = this._EntryIsUsable(entry),
        });
      }
    }
    return { success = true, result = {
      id = p.station_id, name = GSBaseStation.GetName(p.station_id),
      x = GSMap.GetTileX(loc), y = GSMap.GetTileY(loc),
      // The axis the platforms lie along: "x" or "y". Null for a station with no rail.
      platform_axis = orientation,
      // The tiles just beyond each platform end, which is where track has to reach.
      // has_rail on one of these is the difference between a station a train can use and
      // one it cannot.
      entry_tiles = entry_tiles,
      has_rail = GSStation.HasStationType(p.station_id, GSStation.STATION_TRAIN),
      has_truck = GSStation.HasStationType(p.station_id, GSStation.STATION_TRUCK_STOP),
      has_bus = GSStation.HasStationType(p.station_id, GSStation.STATION_BUS_STOP),
      has_airport = GSStation.HasStationType(p.station_id, GSStation.STATION_AIRPORT),
      has_dock = GSStation.HasStationType(p.station_id, GSStation.STATION_DOCK),
      cargo_waiting = cargo_waiting
    }};
  }

  function CmdGetWaypoints(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local waypoints = [];
    foreach (id, _ in GSWaypointList(GSWaypoint.WAYPOINT_ANY)) {
      local loc = GSBaseStation.GetLocation(id);
      waypoints.append({
        id = id, name = GSBaseStation.GetName(id),
        x = GSMap.GetTileX(loc), y = GSMap.GetTileY(loc),
        is_rail = GSWaypoint.HasWaypointType(id, GSWaypoint.WAYPOINT_RAIL),
        is_buoy = GSWaypoint.HasWaypointType(id, GSWaypoint.WAYPOINT_BUOY)
      });
    }
    return { success = true, result = waypoints };
  }

  function CmdGetVehicles(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local vehicles = [];
    local filter_type = ("vehicle_type" in p) ? p.vehicle_type : null;
    foreach (id, _ in GSVehicleList()) {
      if (filter_type != null) {
        local tn = this._VehicleTypeName(GSVehicle.GetVehicleType(id));
        if (tn != filter_type) continue;
      }
      local loc = GSVehicle.GetLocation(id);
      local eid = GSVehicle.GetEngineType(id);
      local ords = [];
      local oc = GSOrder.GetOrderCount(id);
      for (local oi = 0; oi < oc; oi++) {
        ords.append({
          destination = GSOrder.GetOrderDestination(id, oi),
          flags = GSOrder.GetOrderFlags(id, oi),
          is_goto_station = GSOrder.IsGotoStationOrder(id, oi),
          is_goto_depot = GSOrder.IsGotoDepotOrder(id, oi)
        });
      }
      vehicles.append({
        id = id, name = GSVehicle.GetName(id),
        type = this._VehicleTypeName(GSVehicle.GetVehicleType(id)),
        x = GSMap.GetTileX(loc), y = GSMap.GetTileY(loc),
        engine_id = eid,
        running_cost = GSEngine.IsValidEngine(eid) ? GSEngine.GetRunningCost(eid) : 0,
        capacity = this._GetTotalCapacity(id),
        age = GSVehicle.GetAge(id),
        max_age = GSVehicle.GetMaxAge(id),
        profit_this_year = GSVehicle.GetProfitThisYear(id),
        profit_last_year = GSVehicle.GetProfitLastYear(id),
        current_speed = GSVehicle.GetCurrentSpeed(id),
        state = GSVehicle.GetState(id),
        running = GSVehicle.GetState(id) == GSVehicle.VS_RUNNING,
        in_depot = GSVehicle.IsStoppedInDepot(id),
        order_count = oc,
        orders = ords,
        is_articulated = GSVehicle.IsArticulated(id)
      });
    }
    return { success = true, result = vehicles };
  }

  function CmdGetVehicleInfo(p) {
    if (!GSVehicle.IsValidVehicle(p.vehicle_id)) return { success = false, error = "Invalid vehicle ID" };
    local vid = p.vehicle_id;
    local loc = GSVehicle.GetLocation(vid);
    local orders = [];
    local order_count = GSOrder.GetOrderCount(vid);
    for (local i = 0; i < order_count; i++) {
      orders.append({
        index = i,
        destination = GSOrder.GetOrderDestination(vid, i),
        flags = GSOrder.GetOrderFlags(vid, i),
        is_goto_station = GSOrder.IsGotoStationOrder(vid, i),
        is_goto_depot = GSOrder.IsGotoDepotOrder(vid, i),
        is_goto_waypoint = GSOrder.IsGotoWaypointOrder(vid, i),
        is_conditional = GSOrder.IsConditionalOrder(vid, i)
      });
    }
    local cargo_loads = [];
    foreach (cargo_id, _ in GSCargoList()) {
      local cap = GSVehicle.GetCapacity(vid, cargo_id);
      local load = GSVehicle.GetCargoLoad(vid, cargo_id);
      if (cap > 0) cargo_loads.append({ cargo_id = cargo_id, capacity = cap, loaded = load });
    }
    return { success = true, result = {
      id = vid, name = GSVehicle.GetName(vid),
      type = this._VehicleTypeName(GSVehicle.GetVehicleType(vid)),
      engine_id = GSVehicle.GetEngineType(vid),
      x = GSMap.GetTileX(loc), y = GSMap.GetTileY(loc),
      age = GSVehicle.GetAge(vid),
      max_age = GSVehicle.GetMaxAge(vid),
      age_left = GSVehicle.GetAgeLeft(vid),
      profit_this_year = GSVehicle.GetProfitThisYear(vid),
      profit_last_year = GSVehicle.GetProfitLastYear(vid),
      current_speed = GSVehicle.GetCurrentSpeed(vid),
      state = GSVehicle.GetState(vid),
      in_depot = GSVehicle.IsStoppedInDepot(vid),
      is_articulated = GSVehicle.IsArticulated(vid),
      // Through the shared orders LIST, not GSOrder.HasSharedOrders, which does not
      // exist on GSOrder in OpenTTD 15.3. Calling it raised "the index
      // 'HasSharedOrders' does not exist" and took the WHOLE reply with it, so
      // get_vehicle_info returned nothing for any vehicle at all. That is what made a
      // perfectly valid wagon id look invalid and sent me hunting a bug in buy_vehicle.
      //
      // A vehicle sharing orders appears in its own shared list alongside at least one
      // other, so a count above one is the answer.
      has_shared_orders = GSVehicleList_SharedOrders(vid).Count() > 1,
      length = GSVehicle.GetLength(vid),
      cargo = cargo_loads,
      orders = orders
    }};
  }

  function CmdGetEngines(p) {
    local type_str = ("vehicle_type" in p) ? p.vehicle_type : "train";
    local vt = this._VehicleTypeEnum(type_str);
    local engines = [];
    foreach (id, _ in GSEngineList(vt)) {
      if (!GSEngine.IsBuildable(id)) continue;
      local ct = GSEngine.GetCargoType(id);
      local cl = GSCargo.IsValidCargo(ct) ? GSCargo.GetCargoLabel(ct) : "";
      local rt = -1;
      if (vt == GSVehicle.VT_RAIL && GSEngine.IsValidEngine(id)) {
        rt = GSEngine.GetRailType(id);
      }
      engines.append({
        id = id, name = GSEngine.GetName(id),
        cargo_type = ct,
        cargo_label = cl,
        capacity = GSEngine.GetCapacity(id),
        max_speed = GSEngine.GetMaxSpeed(id),
        price = GSEngine.GetPrice(id),
        running_cost = GSEngine.GetRunningCost(id),
        power = GSEngine.GetPower(id),
        weight = GSEngine.GetWeight(id),
        reliability = GSEngine.GetReliability(id),
        is_wagon = GSEngine.IsWagon(id),
        rail_type = rt
      });
    }
    return { success = true, result = engines };
  }

  function CmdGetCargoTypes() {
    local cargos = [];
    foreach (id, _ in GSCargoList()) {
      cargos.append({
        id = id, label = GSCargo.GetCargoLabel(id),
        name = GSCargo.GetName(id),
        is_freight = GSCargo.IsFreight(id)
      });
    }
    return { success = true, result = cargos };
  }

  function CmdGetCargoIncome(p) {
    // What the game itself pays for carrying cargo.
    //
    // Nothing else in the read-only surface answers this, so route choice, which is the
    // central judgement the benchmark means to measure, could only be made on production
    // volume. That ranks a short high volume low value run above a long lower volume high
    // value one for no good reason, and gives no way to tell an investment from a mistake
    // until several game months later.
    //
    // GSCargo.GetCargoIncome is the game's own function, so this reports what will
    // actually be paid rather than a model of it that could drift.
    if (!("cargo_id" in p) || !("distance" in p))
      return { success = false, error = "params.cargo_id and params.distance required" };
    local cargo_id = p.cargo_id;
    if (!GSCargo.IsValidCargo(cargo_id))
      return { success = false, error = "Invalid cargo ID: " + cargo_id };

    local distance = p.distance;
    if (distance < 1) distance = 1;

    // Payment falls off with time in transit, so the answer needs one. Defaulted rather
    // than required: a caller comparing corridors wants them compared on the same
    // assumption, and an agent has no way to know a transit time before it owns a vehicle.
    local days = ("days_in_transit" in p) ? p.days_in_transit : this._DEFAULT_TRANSIT_DAYS;
    if (days < 1) days = 1;

    local per_unit = GSCargo.GetCargoIncome(cargo_id, distance, days);
    return { success = true, result = {
      cargo_id = cargo_id,
      label = GSCargo.GetCargoLabel(cargo_id),
      distance = distance,
      days_in_transit = days,
      income_per_unit = per_unit,
      // Named so a caller does not have to know that the game charges per unit: an amount
      // it can multiply is the shape the question is actually asked in.
      income_per_100_units = per_unit * 100,
    }};
  }

  function CmdGetRailTypes() {
    // Only the types this game actually has, named, with whether they can be built now.
    //
    // GSRailTypeList walks all 64 slots of the rail type table, and a slot no baseset
    // defines has no name, so this returned 64 entries every one of which was called
    // "(undefined string)". Every build action takes a rail_type and its description says
    // to ask here, so asking taught an agent nothing and picking one was guesswork. Getting
    // it wrong then failed with a bare ERR_UNKNOWN, since nothing said the engine and the
    // track disagreed.
    //
    // available is the field that matters most: what can be built moves with the year, and
    // an engine bought for a type the track is not is the mistake this prevents. The ids
    // are the same numbers get_engines reports as rail_type, so the two can be matched.
    local types = [];
    foreach (id, _ in GSRailTypeList()) {
      local name = GSRail.GetName(id);
      // A slot with no defined name is not a rail type, it is an empty row in the table.
      if (name == null || name == "(undefined string)") continue;
      types.append({
        id = id,
        name = name,
        available = GSRail.IsRailTypeAvailable(id),
        build_cost_per_tile = GSRail.GetBuildCost(id, GSRail.BT_TRACK),
      });
    }
    return { success = true, result = types };
  }

  function CmdGetRoadTypes() {
    local types = [];
    foreach (id, _ in GSRoadTypeList(GSRoad.ROADTRAMTYPES_ROAD)) {
      types.append({ id = id, name = GSRoad.GetName(id), is_tram = false });
    }
    foreach (id, _ in GSRoadTypeList(GSRoad.ROADTRAMTYPES_TRAM)) {
      types.append({ id = id, name = GSRoad.GetName(id), is_tram = true });
    }
    return { success = true, result = types };
  }

  function CmdGetAirportTypes() {
    local types = [];
    for (local t = 0; t < 16; t++) {
      if (!GSAirport.IsValidAirportType(t)) continue;
      types.append({
        id = t,
        width = GSAirport.GetAirportWidth(t),
        height = GSAirport.GetAirportHeight(t),
        coverage = GSAirport.GetAirportCoverageRadius(t)
      });
    }
    return { success = true, result = types };
  }

  function CmdGetBridgeTypes() {
    local types = [];
    foreach (id, _ in GSBridgeList()) {
      types.append({
        id = id,
        name = GSBridge.GetName(id, GSVehicle.VT_ROAD),
        max_length = GSBridge.GetMaxLength(id),
        min_length = GSBridge.GetMinLength(id),
        max_speed = GSBridge.GetMaxSpeed(id),
        price = GSBridge.GetPrice(id, 4)
      });
    }
    return { success = true, result = types };
  }

  function CmdGetGroups(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local groups = [];
    foreach (id, _ in GSGroupList()) {
      local vt = GSGroup.GetVehicleType(id);
      groups.append({
        id = id, name = GSGroup.GetName(id),
        vehicle_type = this._VehicleTypeName(vt),
        parent_id = GSGroup.GetParent(id),
        profit_this_year = GSGroup.GetProfitThisYear(id),
        profit_last_year = GSGroup.GetProfitLastYear(id)
      });
    }
    return { success = true, result = groups };
  }

  function CmdGetSigns() {
    local signs = [];
    foreach (id, _ in GSSignList()) {
      local loc = GSSign.GetLocation(id);
      signs.append({
        id = id, name = GSSign.GetName(id),
        x = GSMap.GetTileX(loc), y = GSMap.GetTileY(loc)
      });
    }
    return { success = true, result = signs };
  }

  function CmdGetSubsidies() {
    local subsidies = [];
    foreach (id, _ in GSSubsidyList()) {
      if (!GSSubsidy.IsValidSubsidy(id)) continue;
      subsidies.append({
        id = id,
        is_awarded = GSSubsidy.IsAwarded(id),
        cargo_type = GSSubsidy.GetCargoType(id),
        source_type = GSSubsidy.GetSourceType(id),
        source_index = GSSubsidy.GetSourceIndex(id),
        destination_type = GSSubsidy.GetDestinationType(id),
        destination_index = GSSubsidy.GetDestinationIndex(id),
        remaining = GSSubsidy.GetExpireDate(id) - GSDate.GetCurrentDate()
      });
    }
    return { success = true, result = subsidies };
  }

  // ===========================================================================
  // SMART QUERY COMMANDS
  // ===========================================================================

  function CmdScanTownArea(p) {
    if (!GSTown.IsValidTown(p.town_id)) return { success = false, error = "Invalid town ID" };
    local radius = ("radius" in p) ? p.radius : 15;
    local loc = GSTown.GetLocation(p.town_id);
    local cx = GSMap.GetTileX(loc), cy = GSMap.GetTileY(loc);
    local buildable = [], roads = [], buildings = [], water = [];
    for (local dy = -radius; dy <= radius; dy++) {
      for (local dx = -radius; dx <= radius; dx++) {
        local x = cx + dx, y = cy + dy;
        local tile = GSMap.GetTileIndex(x, y);
        if (!GSMap.IsValidTile(tile)) continue;
        if (GSTile.IsWaterTile(tile) || GSTile.IsCoastTile(tile)) {
          water.append({ x = x, y = y });
        } else if (GSRoad.IsRoadTile(tile)) {
          roads.append({ x = x, y = y });
        } else if (GSTile.IsBuildable(tile)) {
          buildable.append({ x = x, y = y, height = GSTile.GetMaxHeight(tile), slope = GSTile.GetSlope(tile) });
        } else {
          buildings.append({ x = x, y = y });
        }
      }
    }
    return { success = true, result = {
      town_name = GSTown.GetName(p.town_id),
      center_x = cx, center_y = cy, radius = radius,
      buildable = buildable, roads = roads, buildings = buildings, water = water,
      counts = { buildable = buildable.len(), roads = roads.len(), buildings = buildings.len(), water = water.len() }
    }};
  }

  function CmdFindBusStopSpots(p) {
    if (!GSTown.IsValidTown(p.town_id)) return { success = false, error = "Invalid town ID" };
    local company_id = ("company_id" in p) ? p.company_id : 0;
    local radius = ("radius" in p) ? p.radius : 15;
    local max_results = ("max_results" in p) ? p.max_results : 10;
    local is_truck = ("is_truck_stop" in p) ? p.is_truck_stop : false;
    local road_type = ("road_type" in p) ? p.road_type : 0;
    // The current road type is script-global and unset on a fresh session, so
    // the dry-run below rejects every tile until some command selects one.
    GSRoad.SetCurrentRoadType(road_type);
    local loc = GSTown.GetLocation(p.town_id);
    local cx = GSMap.GetTileX(loc), cy = GSMap.GetTileY(loc);
    local stop_type = is_truck ? GSRoad.ROADVEHTYPE_TRUCK : GSRoad.ROADVEHTYPE_BUS;
    local spots = [];
    // Pass 1: tiles adjacent to existing roads (preferred)
    for (local dy = -radius; dy <= radius; dy++) {
      for (local dx = -radius; dx <= radius; dx++) {
        local x = cx + dx, y = cy + dy;
        local tile = GSMap.GetTileIndex(x, y);
        if (!GSMap.IsValidTile(tile) || !GSTile.IsBuildable(tile)) continue;
        local adj = this._GetAdjacentRoads(x, y);
        if (adj.len() == 0) continue;
        {
          local company_mode = GSCompanyMode(company_id);
          local test_mode = GSTestMode();
          local front = this._GetAdjacentTile(tile, adj[0].dir);
          if (!GSRoad.BuildRoadStation(tile, front, stop_type, GSStation.STATION_NEW)) continue;
        }
        local cargo_info = this._GetTileCargoInfo(tile, 1, 1, 3);
        spots.append({ tile = tile, x = x, y = y, distance = abs(dx) + abs(dy),
          adjacent_road_x = adj[0].nx, adjacent_road_y = adj[0].ny,
          adjacent_road_count = adj.len(),
          direction = adj[0].dir,
          has_adjacent_road = true,
          cargo_acceptance = cargo_info });
      }
    }
    // Pass 2: if no road-adjacent spots, find flat buildable tiles (agent must connect_road)
    if (spots.len() == 0) {
      for (local dy = -radius; dy <= radius; dy++) {
        for (local dx = -radius; dx <= radius; dx++) {
          local x = cx + dx, y = cy + dy;
          local tile = GSMap.GetTileIndex(x, y);
          if (!GSMap.IsValidTile(tile) || !GSTile.IsBuildable(tile)) continue;
          if (GSTile.GetSlope(tile) != 0) continue;
          local dir = this._FindAnyAdjacentBuildable(x, y);
          if (dir < 0) continue;
          {
            local company_mode = GSCompanyMode(company_id);
            local test_mode = GSTestMode();
            local front = this._GetAdjacentTile(tile, dir);
            if (!GSRoad.BuildRoadStation(tile, front, stop_type, GSStation.STATION_NEW)) continue;
          }
          local cargo_info = this._GetTileCargoInfo(tile, 1, 1, 3);
          spots.append({ tile = tile, x = x, y = y, distance = abs(dx) + abs(dy),
            adjacent_road_count = 0,
            direction = dir,
            has_adjacent_road = false,
            cargo_acceptance = cargo_info });
        }
      }
    }
    // Sort by cargo acceptance count (desc), then distance (asc)
    for (local i = 1; i < spots.len(); i++) {
      local key = spots[i];
      local j = i - 1;
      while (j >= 0 && (spots[j].cargo_acceptance.len() < key.cargo_acceptance.len()
        || (spots[j].cargo_acceptance.len() == key.cargo_acceptance.len() && spots[j].distance > key.distance))) {
        spots[j + 1] = spots[j]; j--;
      }
      spots[j + 1] = key;
    }
    if (spots.len() > max_results) spots = spots.slice(0, max_results);
    return { success = true, result = spots };
  }

  function CmdFindDepotSpots(p) {
    if (!GSTown.IsValidTown(p.town_id)) return { success = false, error = "Invalid town ID" };
    local company_id = ("company_id" in p) ? p.company_id : 0;
    local radius = ("radius" in p) ? p.radius : 15;
    local max_results = ("max_results" in p) ? p.max_results : 5;
    local road_type = ("road_type" in p) ? p.road_type : 0;
    // See CmdFindBusStopSpots: the current road type must be selected before
    // any GSRoad dry-run, or every candidate tile is rejected.
    GSRoad.SetCurrentRoadType(road_type);
    local loc = GSTown.GetLocation(p.town_id);
    local cx = GSMap.GetTileX(loc), cy = GSMap.GetTileY(loc);
    local spots = [];
    for (local dy = -radius; dy <= radius; dy++) {
      for (local dx = -radius; dx <= radius; dx++) {
        local x = cx + dx, y = cy + dy;
        local tile = GSMap.GetTileIndex(x, y);
        if (!GSMap.IsValidTile(tile) || !GSTile.IsBuildable(tile)) continue;
        local adj = this._GetAdjacentRoads(x, y);
        if (adj.len() == 0) continue;
        // Dry-run: test if BuildRoadDepot would actually succeed here
        {
          local company_mode = GSCompanyMode(company_id);
          local test_mode = GSTestMode();
          if (!GSRoad.BuildRoadDepot(tile, this._GetAdjacentTile(tile, adj[0].dir))) continue;
        }
        spots.append({ tile = tile, x = x, y = y, distance = abs(dx) + abs(dy),
          adjacent_road_x = adj[0].nx, adjacent_road_y = adj[0].ny,
          depot_direction = adj[0].dir });
      }
    }
    this._SortByDistance(spots);
    if (spots.len() > max_results) spots = spots.slice(0, max_results);
    return { success = true, result = spots };
  }

  function CmdFindRailDepotSpot(p) {
    if (!("tile" in p)) return { success = false, error = "tile parameter required" };
    local company_id = ("company_id" in p) ? p.company_id : 0;
    local radius = ("radius" in p) ? p.radius : 10;
    local max_results = ("max_results" in p) ? p.max_results : 5;
    local rail_type = ("rail_type" in p) ? p.rail_type : 0;
    local cx = GSMap.GetTileX(p.tile), cy = GSMap.GetTileY(p.tile);
    local spots = [];
    for (local dy = -radius; dy <= radius; dy++) {
      for (local dx = -radius; dx <= radius; dx++) {
        local x = cx + dx, y = cy + dy;
        local tile = GSMap.GetTileIndex(x, y);
        if (!GSMap.IsValidTile(tile) || !GSTile.IsBuildable(tile)) continue;
        local adj = this._GetAdjacentRailTrack(x, y);
        if (adj.len() == 0) continue;

        // The front tile is what the depot opens onto, and it has to be track a train can
        // actually run along. A rail station platform is not that. It is a line with an
        // axis, and a depot set against its flank opens onto a tile no train can enter
        // from that side, so the depot builds, reports connected false, and can never
        // release a vehicle.
        //
        // Every adjacent track is now tried rather than only the first, which was merely
        // whichever direction the scan reached first. A tile with one unusable neighbour
        // and one good one was being thrown away on the strength of the wrong one.
        local chosen = null;
        foreach (candidate in adj) {
          local front = this._GetAdjacentTile(tile, candidate.dir);
          if (GSRail.IsRailStationTile(front)) continue;
          local company_mode = GSCompanyMode(company_id);
          local test_mode = GSTestMode();
          GSRail.SetCurrentRailType(rail_type);
          if (!GSRail.BuildRailDepot(tile, front)) continue;
          chosen = candidate;
          break;
        }
        if (chosen == null) continue;
        spots.append({ tile = tile, x = x, y = y, distance = abs(dx) + abs(dy),
          adjacent_track_x = chosen.nx, adjacent_track_y = chosen.ny,
          depot_direction = chosen.dir });
      }
    }
    this._SortByDistance(spots);
    if (spots.len() > max_results) spots = spots.slice(0, max_results);
    return { success = true, result = spots };
  }

  function CmdFindAirportSpots(p) {
    if (!GSTown.IsValidTown(p.town_id)) return { success = false, error = "Invalid town ID" };
    local company_id = ("company_id" in p) ? p.company_id : 0;
    local airport_type = ("airport_type" in p) ? p.airport_type : 0;
    if (!GSAirport.IsValidAirportType(airport_type)) return { success = false, error = "Invalid airport type" };
    local radius = ("radius" in p) ? p.radius : 20;
    local max_results = ("max_results" in p) ? p.max_results : 5;
    local aw = GSAirport.GetAirportWidth(airport_type);
    local ah = GSAirport.GetAirportHeight(airport_type);
    local loc = GSTown.GetLocation(p.town_id);
    local cx = GSMap.GetTileX(loc), cy = GSMap.GetTileY(loc);
    local spots = [];
    for (local dy = -radius; dy <= radius; dy++) {
      for (local dx = -radius; dx <= radius; dx++) {
        local x = cx + dx, y = cy + dy;
        local tile = GSMap.GetTileIndex(x, y);
        if (!GSMap.IsValidTile(tile)) continue;
        // Dry-run: test if BuildAirport would actually succeed here
        {
          local company_mode = GSCompanyMode(company_id);
          local test_mode = GSTestMode();
          if (!GSAirport.BuildAirport(tile, airport_type, GSStation.STATION_NEW)) continue;
        }
        local cargo_info = this._GetTileCargoInfo(tile, aw, ah, 4);
        spots.append({ tile = tile, x = x, y = y, distance = abs(dx) + abs(dy),
          width = aw, height = ah, cargo_acceptance = cargo_info });
      }
    }
    // Sort by cargo acceptance count (desc), then distance (asc)
    for (local i = 1; i < spots.len(); i++) {
      local key = spots[i];
      local j = i - 1;
      while (j >= 0 && (spots[j].cargo_acceptance.len() < key.cargo_acceptance.len()
        || (spots[j].cargo_acceptance.len() == key.cargo_acceptance.len() && spots[j].distance > key.distance))) {
        spots[j + 1] = spots[j]; j--;
      }
      spots[j + 1] = key;
    }
    if (spots.len() > max_results) spots = spots.slice(0, max_results);
    return { success = true, result = spots,
      airport_type = airport_type, airport_width = aw, airport_height = ah };
  }

  function CmdFindDockSpots(p) {
    if (!GSTown.IsValidTown(p.town_id)) return { success = false, error = "Invalid town ID" };
    local company_id = ("company_id" in p) ? p.company_id : 0;
    local radius = ("radius" in p) ? p.radius : 20;
    local max_results = ("max_results" in p) ? p.max_results : 5;
    local loc = GSTown.GetLocation(p.town_id);
    local cx = GSMap.GetTileX(loc), cy = GSMap.GetTileY(loc);
    local spots = [];
    for (local dy = -radius; dy <= radius; dy++) {
      for (local dx = -radius; dx <= radius; dx++) {
        local x = cx + dx, y = cy + dy;
        local tile = GSMap.GetTileIndex(x, y);
        if (!GSMap.IsValidTile(tile)) continue;
        if (!GSTile.IsCoastTile(tile)) continue;
        // Dry-run: test if BuildDock would actually succeed here
        {
          local company_mode = GSCompanyMode(company_id);
          local test_mode = GSTestMode();
          if (!GSMarine.BuildDock(tile, GSStation.STATION_NEW)) continue;
        }
        local cargo_info = this._GetTileCargoInfo(tile, 1, 1, 4);
        spots.append({ tile = tile, x = x, y = y, distance = abs(dx) + abs(dy),
          slope = GSTile.GetSlope(tile), cargo_acceptance = cargo_info });
      }
    }
    // Sort by cargo acceptance count (desc), then distance (asc)
    for (local i = 1; i < spots.len(); i++) {
      local key = spots[i];
      local j = i - 1;
      while (j >= 0 && (spots[j].cargo_acceptance.len() < key.cargo_acceptance.len()
        || (spots[j].cargo_acceptance.len() == key.cargo_acceptance.len() && spots[j].distance > key.distance))) {
        spots[j + 1] = spots[j]; j--;
      }
      spots[j + 1] = key;
    }
    if (spots.len() > max_results) spots = spots.slice(0, max_results);
    return { success = true, result = spots };
  }

  function CmdFindFlatSpots(p) {
    local resolved = this._ResolveTile(p);
    if (resolved == null) return { success = false, error = "Need tile or x,y params" };
    local radius = ("radius" in p) ? p.radius : 10;
    local max_results = ("max_results" in p) ? p.max_results : 10;
    local min_size = ("min_size" in p) ? p.min_size : 1;
    local do_station_test = ("station_test" in p) ? p.station_test : false;
    local station_length = ("platform_length" in p) ? p.platform_length : 3;
    local station_rail_type = ("rail_type" in p) ? p.rail_type : 0;
    local company_id = ("company_id" in p) ? p.company_id : 0;
    local required_cargo = ("required_cargo" in p) ? p.required_cargo : null;
    local cx = resolved.x, cy = resolved.y;
    local spots = [];
    for (local dy = -radius; dy <= radius; dy++) {
      for (local dx = -radius; dx <= radius; dx++) {
        local x = cx + dx, y = cy + dy;
        local tile = GSMap.GetTileIndex(x, y);
        if (!GSMap.IsValidTile(tile) || !GSTile.IsBuildable(tile)) continue;
        if (GSTile.GetSlope(tile) != 0) continue;
        // If min_size > 1, check a square of that size
        if (min_size > 1) {
          local base_h = GSTile.GetMaxHeight(tile);
          local ok = true;
          for (local ry = 0; ry < min_size && ok; ry++) {
            for (local rx = 0; rx < min_size && ok; rx++) {
              if (rx == 0 && ry == 0) continue;
              local ct = GSMap.GetTileIndex(x + rx, y + ry);
              if (!GSMap.IsValidTile(ct) || !GSTile.IsBuildable(ct)) { ok = false; break; }
              if (GSTile.GetMaxHeight(ct) != base_h || GSTile.GetSlope(ct) != 0) { ok = false; break; }
            }
          }
          if (!ok) continue;
        }
        // Dry-run: test if BuildRailStation would succeed here
        if (do_station_test) {
          local company_mode = GSCompanyMode(company_id);
          local test_mode = GSTestMode();
          GSRail.SetCurrentRailType(station_rail_type);
          if (!GSRail.BuildRailStation(tile, GSRail.RAILTRACK_NE_SW, 1, station_length,
                GSStation.STATION_NEW)) continue;
        }
        local cargo_info = this._GetTileCargoInfo(tile, min_size, min_size, 4);
        // Filter by required cargo if specified
        if (required_cargo != null) {
          local found = false;
          foreach (ci in cargo_info) {
            if (ci.cargo_label == required_cargo && ci.production > 0) { found = true; break; }
          }
          if (!found) continue;
        }
        spots.append({ tile = tile, x = x, y = y, distance = abs(dx) + abs(dy),
          max_height = GSTile.GetMaxHeight(tile), cargo_acceptance = cargo_info });
      }
    }
    this._SortByDistance(spots);
    if (spots.len() > max_results) spots = spots.slice(0, max_results);
    return { success = true, result = spots };
  }

  function CmdFindStationSpot(p) {
    local has_industry = ("industry_id" in p) && GSIndustry.IsValidIndustry(p.industry_id);
    local has_town = ("town_id" in p) && GSTown.IsValidTown(p.town_id);
    if (!has_industry && !has_town)
      return { success = false, error = "Provide industry_id or town_id" };

    local company_id = ("company_id" in p) ? p.company_id : 0;
    local platform_length = ("platform_length" in p) ? p.platform_length : 3;
    local rail_type = ("rail_type" in p) ? p.rail_type : 0;
    local radius = ("radius" in p) ? p.radius : 15;
    local max_results = ("max_results" in p) ? p.max_results : 5;

    local cx, cy, target_name;
    local cargo_labels = [];

    if (has_industry) {
      local loc = GSIndustry.GetLocation(p.industry_id);
      cx = GSMap.GetTileX(loc); cy = GSMap.GetTileY(loc);
      target_name = GSIndustry.GetName(p.industry_id);
      local cargo_list = GSCargoList();
      foreach (cargo_id, _ in cargo_list) {
        local last = GSIndustry.GetLastMonthProduction(p.industry_id, cargo_id);
        if (last > 0) cargo_labels.append(GSCargo.GetCargoLabel(cargo_id));
        if (GSIndustry.IsCargoAccepted(p.industry_id, cargo_id))
          cargo_labels.append(GSCargo.GetCargoLabel(cargo_id));
      }
    } else {
      local loc = GSTown.GetLocation(p.town_id);
      cx = GSMap.GetTileX(loc); cy = GSMap.GetTileY(loc);
      target_name = GSTown.GetName(p.town_id);
      cargo_labels = ["PASS", "MAIL"];
    }

    if (cargo_labels.len() == 0)
      return { success = false, error = "No cargo found for this target" };

    local spots = [];
    for (local dy = -radius; dy <= radius; dy++) {
      for (local dx = -radius; dx <= radius; dx++) {
        local x = cx + dx, y = cy + dy;
        local tile = GSMap.GetTileIndex(x, y);
        if (!GSMap.IsValidTile(tile) || !GSTile.IsBuildable(tile)) continue;
        if (GSTile.GetSlope(tile) != 0) continue;
        local base_h = GSTile.GetMaxHeight(tile);
        // Test both orientations: dir 0 = NE-SW (+X), dir 1 = NW-SE (+Y)
        local valid_dirs = [];
        // Direction 0 (NE-SW): platform extends along +X
        {
          local ok_0 = true;
          for (local rx = 1; rx < platform_length && ok_0; rx++) {
            local ct = GSMap.GetTileIndex(x + rx, y);
            if (!GSMap.IsValidTile(ct) || !GSTile.IsBuildable(ct)) { ok_0 = false; break; }
            if (GSTile.GetMaxHeight(ct) != base_h || GSTile.GetSlope(ct) != 0) { ok_0 = false; break; }
          }
          if (ok_0) {
            local company_mode = GSCompanyMode(company_id);
            local test_mode = GSTestMode();
            GSRail.SetCurrentRailType(rail_type);
            if (GSRail.BuildRailStation(tile, GSRail.RAILTRACK_NE_SW, 1, platform_length,
                  GSStation.STATION_NEW)) valid_dirs.append(0);
          }
        }
        // Direction 1 (NW-SE): platform extends along +Y
        {
          local ok_1 = true;
          for (local ry = 1; ry < platform_length && ok_1; ry++) {
            local ct = GSMap.GetTileIndex(x, y + ry);
            if (!GSMap.IsValidTile(ct) || !GSTile.IsBuildable(ct)) { ok_1 = false; break; }
            if (GSTile.GetMaxHeight(ct) != base_h || GSTile.GetSlope(ct) != 0) { ok_1 = false; break; }
          }
          if (ok_1) {
            local company_mode = GSCompanyMode(company_id);
            local test_mode = GSTestMode();
            GSRail.SetCurrentRailType(rail_type);
            if (GSRail.BuildRailStation(tile, GSRail.RAILTRACK_NW_SE, 1, platform_length,
                  GSStation.STATION_NEW)) valid_dirs.append(1);
          }
        }
        if (valid_dirs.len() == 0) continue;

        // Which of those orientations a train could actually reach.
        //
        // valid_dirs says the platform FITS. That is not the same question, and near a town
        // the two disagree often. Measured: a spot offered with both orientations valid had
        // NEITHER entry usable along x, both a town building and a road, and one usable
        // along y. Taking the first built a station no train could ever enter, and the only
        // repair was to demolish it.
        local reachable_dirs = [];
        foreach (dir in valid_dirs) {
          local dx = (dir == 0) ? 1 : 0;
          local dy = (dir == 0) ? 0 : 1;
          local before = GSMap.GetTileIndex(x - dx, y - dy);
          local after = GSMap.GetTileIndex(
            x + dx * platform_length, y + dy * platform_length);
          local ok = (GSMap.IsValidTile(before) && this._EntryIsUsable(before))
                  || (GSMap.IsValidTile(after) && this._EntryIsUsable(after));
          if (ok) reachable_dirs.append(dir);
        }
        // Check cargo using first valid direction's footprint
        local ci_w = (valid_dirs[0] == 0) ? platform_length : 1;
        local ci_h = (valid_dirs[0] == 0) ? 1 : platform_length;
        local cargo_info = this._GetTileCargoInfo(tile, ci_w, ci_h, 4);
        local has_target_cargo = false;
        foreach (ci in cargo_info) {
          foreach (lbl in cargo_labels) {
            if (ci.cargo_label == lbl && (ci.production > 0 || ci.acceptance)) {
              has_target_cargo = true; break;
            }
          }
          if (has_target_cargo) break;
        }
        if (!has_target_cargo) continue;
        spots.append({ tile = tile, x = x, y = y, distance = abs(dx) + abs(dy),
          max_height = base_h, cargo_acceptance = cargo_info,
          // The platform fits in these orientations.
          valid_directions = valid_dirs,
          // And a train could reach it in these. Build in one of THESE. An empty list means
          // the footprint fits and the station would be unusable.
          reachable_directions = reachable_dirs });
      }
    }
    this._SortStationSpots(spots);
    if (spots.len() > max_results) spots = spots.slice(0, max_results);

    local result_info = {
      target_name = target_name, target_x = cx, target_y = cy,
      cargo_labels = cargo_labels, spots = spots
    };
    if (has_industry) result_info.industry_id <- p.industry_id;
    else result_info.town_id <- p.town_id;
    return { success = true, result = result_info };
  }

  function CmdFindWaterDepotSpots(p) {
    // Find water tiles suitable for building a ship depot near a given tile or town.
    local cx, cy;
    if ("town_id" in p) {
      if (!GSTown.IsValidTown(p.town_id)) return { success = false, error = "Invalid town ID" };
      local loc = GSTown.GetLocation(p.town_id);
      cx = GSMap.GetTileX(loc); cy = GSMap.GetTileY(loc);
    } else if ("x" in p && "y" in p) {
      cx = p.x; cy = p.y;
    } else if ("tile" in p) {
      local t = p.tile.tointeger();
      cx = GSMap.GetTileX(t); cy = GSMap.GetTileY(t);
    } else {
      return { success = false, error = "Need town_id, tile, or x,y params" };
    }
    local company_id = ("company_id" in p) ? p.company_id : 0;
    local radius = ("radius" in p) ? p.radius : 20;
    local max_results = ("max_results" in p) ? p.max_results : 5;
    local spots = [];
    for (local dy = -radius; dy <= radius; dy++) {
      for (local dx = -radius; dx <= radius; dx++) {
        local x = cx + dx, y = cy + dy;
        local tile = GSMap.GetTileIndex(x, y);
        if (!GSMap.IsValidTile(tile)) continue;
        if (!GSTile.IsWaterTile(tile)) continue;
        // Dry-run: test if BuildWaterDepot would actually succeed here
        {
          local company_mode = GSCompanyMode(company_id);
          local test_mode = GSTestMode();
          if (!GSMarine.BuildWaterDepot(tile, tile + 1)) continue;
        }
        spots.append({ tile = tile, x = x, y = y, distance = abs(dx) + abs(dy) });
      }
    }
    this._SortByDistance(spots);
    if (spots.len() > max_results) spots = spots.slice(0, max_results);
    return { success = true, result = spots };
  }

  function CmdGetHangars(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local hangars = [];
    foreach (sid, _ in GSStationList(GSStation.STATION_AIRPORT)) {
      local loc = GSBaseStation.GetLocation(sid);
      local airport_tile = loc;
      local airport_type = GSAirport.GetAirportType(airport_tile);
      local num_hangars = GSAirport.GetNumHangars(airport_tile);
      for (local i = 0; i < num_hangars; i++) {
        local hangar_tile = GSAirport.GetHangarOfAirport(airport_tile);
        hangars.append({
          station_id = sid,
          station_name = GSBaseStation.GetName(sid),
          airport_x = GSMap.GetTileX(loc),
          airport_y = GSMap.GetTileY(loc),
          hangar_tile = hangar_tile,
          hangar_x = GSMap.GetTileX(hangar_tile),
          hangar_y = GSMap.GetTileY(hangar_tile),
          airport_type = airport_type
        });
      }
    }
    return { success = true, result = hangars };
  }

  // ===========================================================================
  // BUILDING: ROAD
  // ===========================================================================

  // CmdBuildRoad and CmdBuildRoadLine used to sit here, dispatched by nothing. Both are
  // build_path with a shorter list: a two-tile hop and a straight run. Keeping them meant
  // three ways to lay road, only one of which was reachable, tested, or able to report a
  // partial build honestly.

  function CmdBuildRoadDepot(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local road_type = ("road_type" in p) ? p.road_type : 0;
    local dir = ("direction" in p) ? p.direction : 0;
    GSRoad.SetCurrentRoadType(road_type);
    local r = this._ResolveTile(p);
    if (r == null) return { success = false, error = "Need tile or x,y" };
    if (GSRoad.BuildRoadDepot(r.tile, this._GetAdjacentTile(r.tile, dir))) {
      return { success = true, result = { tile = r.tile, x = r.x, y = r.y } };
    }
    return this._Refused();
  }

  function CmdBuildRoadStop(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local road_type = ("road_type" in p) ? p.road_type : 0;
    local is_truck = ("is_truck_stop" in p) ? p.is_truck_stop : false;
    local is_dt = ("is_drive_through" in p) ? p.is_drive_through : false;
    local dir = ("direction" in p) ? p.direction : 0;
    GSRoad.SetCurrentRoadType(road_type);
    local r = this._ResolveTile(p);
    if (r == null) return { success = false, error = "Need tile or x,y" };
    local front = this._GetAdjacentTile(r.tile, dir);
    local stop_type = is_truck ? GSRoad.ROADVEHTYPE_TRUCK : GSRoad.ROADVEHTYPE_BUS;
    local ok = is_dt
      ? GSRoad.BuildDriveThroughRoadStation(r.tile, front, stop_type, GSStation.STATION_NEW)
      : GSRoad.BuildRoadStation(r.tile, front, stop_type, GSStation.STATION_NEW);
    if (ok) {
      local sid = GSStation.GetStationID(r.tile);
      return { success = true, result = { tile = r.tile, x = r.x, y = r.y, type = is_truck ? "truck" : "bus", station_id = sid } };
    }
    return this._Refused();
  }

  function CmdRemoveRoad(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local road_type = ("road_type" in p) ? p.road_type : 0;
    GSRoad.SetCurrentRoadType(road_type);
    local pair = this._ResolveTilePair(p);
    if (pair == null) return { success = false, error = "Need tile_from+tile_to or from_x,from_y,to_x,to_y" };
    if (GSRoad.RemoveRoad(pair.from.tile, pair.to.tile)) {
      return { success = true, result = { from_tile = pair.from.tile, to_tile = pair.to.tile } };
    }
    return this._Refused();
  }

  function CmdRemoveRoadDepot(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local r = this._ResolveTile(p);
    if (r == null) return { success = false, error = "Need tile or x,y" };
    if (GSRoad.RemoveRoadDepot(r.tile)) return { success = true, result = { tile = r.tile } };
    return this._Refused();
  }

  function CmdRemoveRoadStop(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local r = this._ResolveTile(p);
    if (r == null) return { success = false, error = "Need tile or x,y" };
    if (GSRoad.RemoveRoadStation(r.tile)) return { success = true, result = { tile = r.tile } };
    return this._Refused();
  }

  // ===========================================================================
  // COMPOUND: CONNECT ROAD (A* pathfind + build)
  // Modeled after OpenTTD's built-in pathfinder.road library (same cost model,
  // bridge/tunnel detection, slope handling). Uses GS* API instead of AI*.
  // ===========================================================================

  // Detect whether the road segment start->middle->end is on a slope.
  // Ported from pathfinder.road::_IsSlopedRoad.
  function _IsSlopedRoad(start, middle, end) {
    local map_sx = GSMap.GetMapSizeX();
    local NW = 0;
    local NE = 0;
    local SW = 0;
    local SE = 0;
    if (middle - map_sx == start || middle - map_sx == end) NW = 1;
    if (middle - 1 == start || middle - 1 == end) NE = 1;
    if (middle + map_sx == start || middle + map_sx == end) SE = 1;
    if (middle + 1 == start || middle + 1 == end) SW = 1;
    // Turn in the tile means it cannot be sloped.
    if ((NW || SE) && (NE || SW)) return false;
    local slope = GSTile.GetSlope(middle);
    if (GSTile.IsSteepSlope(slope)) return true;
    if (slope == GSTile.SLOPE_N || slope == GSTile.SLOPE_W) return true;
    if (slope == GSTile.SLOPE_S || slope == GSTile.SLOPE_E) return true;
    if (NW && (slope == GSTile.SLOPE_NW || slope == GSTile.SLOPE_SE)) return true;
    if (NE && (slope == GSTile.SLOPE_NE || slope == GSTile.SLOPE_SW)) return true;
    return false;
  }

  // Count slopes at bridge endpoints for cost calculation.
  // Ported from pathfinder.road::_GetBridgeNumSlopes.
  function _GetBridgeNumSlopes(end_a, end_b) {
    local slopes = 0;
    local dist = GSMap.DistanceManhattan(end_a, end_b);
    if (dist == 0) return 0;
    local direction = (end_b - end_a) / dist;
    local map_sx = GSMap.GetMapSizeX();
    local slope = GSTile.GetSlope(end_a);
    if (!((slope == GSTile.SLOPE_NE && direction == 1) ||
          (slope == GSTile.SLOPE_SE && direction == -map_sx) ||
          (slope == GSTile.SLOPE_SW && direction == -1) ||
          (slope == GSTile.SLOPE_NW && direction == map_sx) ||
          slope == GSTile.SLOPE_N || slope == GSTile.SLOPE_E ||
          slope == GSTile.SLOPE_S || slope == GSTile.SLOPE_W)) {
      slopes++;
    }
    slope = GSTile.GetSlope(end_b);
    direction = -direction;
    if (!((slope == GSTile.SLOPE_NE && direction == 1) ||
          (slope == GSTile.SLOPE_SE && direction == -map_sx) ||
          (slope == GSTile.SLOPE_SW && direction == -1) ||
          (slope == GSTile.SLOPE_NW && direction == map_sx) ||
          slope == GSTile.SLOPE_N || slope == GSTile.SLOPE_E ||
          slope == GSTile.SLOPE_S || slope == GSTile.SLOPE_W)) {
      slopes++;
    }
    return slopes;
  }

  // Check if new_tile is a bridge/tunnel entrance reachable from current_tile.
  // Ported from pathfinder.road::_CheckTunnelBridge.
  function _CheckTunnelBridge(current_tile, new_tile) {
    if (!GSBridge.IsBridgeTile(new_tile) && !GSTunnel.IsTunnelTile(new_tile)) return false;
    local dir = new_tile - current_tile;
    local other_end = GSBridge.IsBridgeTile(new_tile)
      ? GSBridge.GetOtherBridgeEnd(new_tile)
      : GSTunnel.GetOtherTunnelEnd(new_tile);
    local dir2 = other_end - new_tile;
    if ((dir < 0 && dir2 > 0) || (dir > 0 && dir2 < 0)) return false;
    local map_sx = GSMap.GetMapSizeX();
    local a_dir = dir < 0 ? -dir : dir;
    local a_dir2 = dir2 < 0 ? -dir2 : dir2;
    if ((a_dir >= map_sx && a_dir2 < map_sx) ||
        (a_dir < map_sx && a_dir2 >= map_sx)) return false;
    return true;
  }

  // Find buildable bridges and tunnels from cur_node in the direction from last_node.
  // Ported from pathfinder.road::_GetTunnelsBridges.
  function _GetTunnelsBridges(last_node, cur_node, max_bridge_len, max_tunnel_len) {
    local slope = GSTile.GetSlope(cur_node);
    if (slope == GSTile.SLOPE_FLAT) return [];
    local tiles = [];
    local step = cur_node - last_node;
    // Try bridges of increasing length.
    for (local i = 2; i < max_bridge_len; i++) {
      local target = cur_node + i * step;
      if (!GSMap.IsValidTile(target)) break;
      local bridge_list = GSBridgeList_Length(i + 1);
      if (!bridge_list.IsEmpty() &&
          GSBridge.BuildBridge(GSVehicle.VT_ROAD, bridge_list.Begin(), cur_node, target)) {
        tiles.append({ tile = target, is_bridge = true, bridge_start = cur_node });
        break; // Take shortest viable bridge.
      }
    }
    // Try tunnel if slope faces the right way.
    if (slope != GSTile.SLOPE_SW && slope != GSTile.SLOPE_NW &&
        slope != GSTile.SLOPE_SE && slope != GSTile.SLOPE_NE) return tiles;
    local other_end = GSTunnel.GetOtherTunnelEnd(cur_node);
    if (!GSMap.IsValidTile(other_end)) return tiles;
    local tunnel_length = GSMap.DistanceManhattan(cur_node, other_end);
    local prev_tile = cur_node + (cur_node - other_end) / tunnel_length;
    if (GSTunnel.GetOtherTunnelEnd(other_end) == cur_node &&
        tunnel_length >= 2 && prev_tile == last_node &&
        tunnel_length < max_tunnel_len &&
        GSTunnel.BuildTunnel(GSVehicle.VT_ROAD, cur_node)) {
      tiles.append({ tile = other_end, is_tunnel = true, tunnel_start = cur_node });
    }
    return tiles;
  }

  // A* road pathfinder. Returns path array [{tile, x, y, bridge_start?, tunnel_start?}]
  // or null if no path found. Runs inside GSTestMode so BuildRoad checks do not spend money.
  // Cost model matches pathfinder.road defaults.
  function _FindRoadPath(from_tile, to_tile, max_iterations) {
    local test_mode = GSTestMode();
    // Cost parameters: same as pathfinder.road.
    local C_TILE = 100;
    local C_NO_ROAD = 40;
    local C_TURN = 100;
    local C_SLOPE = 200;
    local C_BRIDGE = 150;
    local C_TUNNEL = 120;
    local C_COAST = 20;
    local C_MAX = 10000000;
    local MAX_BRIDGE = 10;
    local MAX_TUNNEL = 20;

    local from_x = GSMap.GetTileX(from_tile);
    local from_y = GSMap.GetTileY(from_tile);
    local to_x = GSMap.GetTileX(to_tile);
    local to_y = GSMap.GetTileY(to_tile);

    // State key: encode tile + entry direction.
    // We use tile ID * 4 + dir for unique keys (cheaper than x/y encoding).
    local open = this._HeapCreate();
    local g_cost = {};
    local came_from = {};      // key -> parent_key (-1 for start)
    local state_tile = {};     // key -> tile
    local state_parent = {};   // key -> parent tile (for turn detection and building)
    local state_meta = {};     // key -> {bridge_start, tunnel_start} or null

    // Seed: enter start tile from all 4 directions.
    local offsets = [1, -1, GSMap.GetMapSizeX(), -GSMap.GetMapSizeX()];
    for (local d = 0; d < 4; d++) {
      local key = from_tile * 4 + d;
      g_cost[key] <- 0;
      came_from[key] <- -1;
      state_tile[key] <- from_tile;
      state_parent[key] <- from_tile - offsets[d]; // Virtual parent behind start.
      state_meta[key] <- null;
      local h = this._Heuristic(from_x, from_y, to_x, to_y) * C_TILE;
      this._HeapPush(open, h, key);
    }

    local iterations = 0;
    local found_key = -1;
    local visited = {};

    while (open.len() > 0 && iterations < max_iterations) {
      iterations++;
      // Yield every 500 iterations and process pending events so other agents
      // aren't blocked by pathfinding. Pathfind commands are queued for later.
      if (iterations % 500 == 0) this._YieldAndProcessEvents();
      local node = this._HeapPop(open);
      local cur_key = node.v;
      if (cur_key in visited) continue;
      visited[cur_key] <- true;

      local cur_tile = state_tile[cur_key];
      local cur_g = g_cost[cur_key];
      local prev_tile = state_parent[cur_key];

      if (cur_g >= C_MAX) continue;

      // Goal check.
      if (cur_tile == to_tile) {
        found_key = cur_key;
        break;
      }

      // --- Enumerate neighbors ---
      local neighbors = []; // [{tile, cost, parent_tile, meta}]

      // Case 1: Current tile is an existing bridge or tunnel with road.
      if ((GSBridge.IsBridgeTile(cur_tile) || GSTunnel.IsTunnelTile(cur_tile)) &&
          GSTile.HasTransportType(cur_tile, GSTile.TRANSPORT_ROAD)) {
        local other_end = GSBridge.IsBridgeTile(cur_tile)
          ? GSBridge.GetOtherBridgeEnd(cur_tile) : GSTunnel.GetOtherTunnelEnd(cur_tile);
        local dist = GSMap.DistanceManhattan(cur_tile, other_end);
        if (dist > 0) {
          local next_after = cur_tile + (cur_tile - other_end) / dist;
          // Can continue past the bridge/tunnel end.
          if (GSMap.IsValidTile(next_after) &&
              (GSRoad.AreRoadTilesConnected(cur_tile, next_after) ||
               GSTile.IsBuildable(next_after) || GSRoad.IsRoadTile(next_after))) {
            neighbors.append({ tile = next_after, extra_cost = 0, parent_tile = cur_tile, meta = null });
          }
          // Traverse the bridge/tunnel itself.
          local traverse_cost = dist * C_TILE;
          if (GSBridge.IsBridgeTile(cur_tile)) {
            traverse_cost += this._GetBridgeNumSlopes(cur_tile, other_end) * C_SLOPE;
          }
          neighbors.append({ tile = other_end, extra_cost = traverse_cost - C_TILE,
                             parent_tile = cur_tile, meta = null });
        }
      }
      // Case 2: We just exited a bridge/tunnel (distance > 1 from parent).
      else if (prev_tile != null && GSMap.DistanceManhattan(cur_tile, prev_tile) > 1) {
        local dist = GSMap.DistanceManhattan(cur_tile, prev_tile);
        if (dist > 0) {
          local next_tile = cur_tile + (cur_tile - prev_tile) / dist;
          if (GSMap.IsValidTile(next_tile) &&
              (GSRoad.AreRoadTilesConnected(cur_tile, next_tile) ||
               GSRoad.BuildRoad(cur_tile, next_tile))) {
            neighbors.append({ tile = next_tile, extra_cost = 0, parent_tile = cur_tile, meta = null });
          }
        }
      }
      // Case 3: Normal tile, check 4 adjacent tiles + bridge/tunnel opportunities.
      else {
        foreach (offset in offsets) {
          local next_tile = cur_tile + offset;
          if (!GSMap.IsValidTile(next_tile)) continue;

          if (GSRoad.AreRoadTilesConnected(cur_tile, next_tile)) {
            // Already connected: free to traverse.
            neighbors.append({ tile = next_tile, extra_cost = 0, parent_tile = cur_tile, meta = null });
          } else if ((GSTile.IsBuildable(next_tile) || GSRoad.IsRoadTile(next_tile)) &&
                     (prev_tile == cur_tile || // Start tile, no parent constraint.
                      GSRoad.CanBuildConnectedRoadPartsHere(cur_tile, prev_tile, next_tile)) &&
                     GSRoad.BuildRoad(cur_tile, next_tile)) {
            // Can build road here (tested in GSTestMode).
            neighbors.append({ tile = next_tile, extra_cost = 0, parent_tile = cur_tile, meta = null });
          } else if (this._CheckTunnelBridge(cur_tile, next_tile)) {
            // Existing bridge/tunnel entrance in the right direction.
            neighbors.append({ tile = next_tile, extra_cost = 0, parent_tile = cur_tile, meta = null });
          }
        }
        // Bridge/tunnel opportunities from current tile (only on slopes).
        if (prev_tile != cur_tile && GSMap.DistanceManhattan(prev_tile, cur_tile) == 1) {
          local bt = this._GetTunnelsBridges(prev_tile, cur_tile, MAX_BRIDGE, MAX_TUNNEL);
          foreach (b in bt) {
            local dist = GSMap.DistanceManhattan(cur_tile, b.tile);
            local extra = 0;
            if ("is_bridge" in b) {
              extra = dist * C_BRIDGE + this._GetBridgeNumSlopes(cur_tile, b.tile) * C_SLOPE;
            } else {
              extra = dist * C_TUNNEL;
            }
            neighbors.append({ tile = b.tile, extra_cost = extra, parent_tile = cur_tile, meta = b });
          }
        }
      }

      // --- Evaluate each neighbor ---
      foreach (nb in neighbors) {
        local next_tile = nb.tile;
        local nb_parent = nb.parent_tile;
        // Compute cost for this edge.
        local edge_cost = C_TILE + nb.extra_cost;
        // No existing road penalty.
        if (!GSRoad.AreRoadTilesConnected(nb_parent, next_tile) &&
            GSMap.DistanceManhattan(nb_parent, next_tile) == 1) {
          edge_cost += C_NO_ROAD;
        }
        // Turn penalty.
        if (prev_tile != cur_tile &&
            GSMap.DistanceManhattan(prev_tile, cur_tile) == 1 &&
            GSMap.DistanceManhattan(cur_tile, next_tile) == 1 &&
            (prev_tile - cur_tile) != (cur_tile - next_tile)) {
          edge_cost += C_TURN;
        }
        // Coast penalty.
        if (GSTile.IsCoastTile(next_tile)) edge_cost += C_COAST;
        // Slope penalty.
        if (prev_tile != cur_tile &&
            GSMap.DistanceManhattan(prev_tile, cur_tile) == 1 &&
            GSMap.DistanceManhattan(cur_tile, next_tile) == 1 &&
            !GSBridge.IsBridgeTile(cur_tile) && !GSTunnel.IsTunnelTile(cur_tile) &&
            this._IsSlopedRoad(prev_tile, cur_tile, next_tile)) {
          edge_cost += C_SLOPE;
        }

        // Direction encoding for state key: based on entry direction.
        local dir_idx;
        if (nb_parent == next_tile) {
          dir_idx = 0; // degenerate
        } else {
          local diff = next_tile - nb_parent;
          if (diff == 1) dir_idx = 0;
          else if (diff == -1) dir_idx = 1;
          else if (diff > 1) dir_idx = 2; // +MapSizeX or bridge
          else dir_idx = 3; // -MapSizeX or bridge
        }
        local next_key = next_tile * 4 + dir_idx;
        local tentative_g = cur_g + edge_cost;

        if (tentative_g < C_MAX &&
            (!(next_key in g_cost) || tentative_g < g_cost[next_key])) {
          g_cost[next_key] <- tentative_g;
          came_from[next_key] <- cur_key;
          state_tile[next_key] <- next_tile;
          state_parent[next_key] <- nb_parent;
          state_meta[next_key] <- nb.meta;
          local nx = GSMap.GetTileX(next_tile);
          local ny = GSMap.GetTileY(next_tile);
          local h = this._Heuristic(nx, ny, to_x, to_y) * C_TILE;
          this._HeapPush(open, tentative_g + h, next_key);
        }
      }
    }

    if (found_key == -1) {
      return { success = false, iterations = iterations };
    }

    // Reconstruct path.
    local path = [];
    local key = found_key;
    while (key != -1) {
      local t = state_tile[key];
      local entry = {
        tile = t,
        x = GSMap.GetTileX(t),
        y = GSMap.GetTileY(t)
      };
      if (state_meta[key] != null) {
        local m = state_meta[key];
        if ("is_bridge" in m) entry.rawset("bridge_start", m.bridge_start);
        if ("is_tunnel" in m) entry.rawset("tunnel_start", m.tunnel_start);
      }
      path.insert(0, entry);
      key = came_from[key];
    }
    return { success = true, path = path, iterations = iterations };
  }

  // Build road along a path returned by _FindRoadPath.
  // Names how much of a route is missing and why, since the failed list can be long
  // and the first reason is usually the reason for all of them.
  // An OpenTTD refusal, with the machine-readable part kept apart from the prose.
  //
  // The error field used to carry everything interchangeably: OpenTTD error names,
  // nttd's own sentences, and Squirrel exception text. A caller could not tell "the game
  // said no" from "nttd would not send it", and RL and ES need a discrete signal rather
  // than a string to pattern-match on.
  //
  // Only OpenTTD refusals carry a code and a category. nttd's own precondition failures
  // deliberately do not, so the absence of a code is what identifies them.
  // Why a build was refused, when the game itself will not say.
  //
  // OpenTTD maps a failure to a ScriptError only when the underlying CommandCost carries
  // a string it knows; anything else arrives as ERR_UNKNOWN, code 1, category none. That
  // is most refusals in practice, and "unknown" is the one answer an agent cannot act on.
  // Measured cost of that: a run spent two of its five actions re-submitting a build onto
  // its own station, because the refusal did not say the tiles were taken.
  //
  // So when the game declines to explain, look at the world and explain it here. The
  // checks are the same calls get_tile_area already makes, and they run only on the
  // failure path, so a successful build pays nothing for them.
  //
  // `hint` is optional and every existing caller passes nothing, which keeps the 94 call
  // sites working while the handlers that know their tile can say so.
  function _Refused(hint = null) {
    local out = { success = false,
                  error = GSError.GetLastErrorString(),
                  error_code = GSError.GetLastError(),
                  error_category = GSError.GetErrorCategory() };
    if (hint != null) {
      local why = this._Diagnose(hint);
      if (why != null) out.rawset("reason", why);
    }
    // ERR_NONE means the command failed WITHOUT the game setting an error, so there is
    // nothing to translate and a caller sees a refusal that says only "none". Measured on
    // buy_vehicle: the third purchase in one depot in one step refused this way on both
    // routes of a session, with no way to tell it from a bug in nttd.
    //
    // Saying that plainly is the least this can do, and it is what #102 asks for: the
    // absence of a reason is itself the information.
    if (!("reason" in out) && out.error == "ERR_NONE") {
      out.rawset("reason",
        "the game refused this without giving a reason, which usually means a limit was "
        + "reached rather than a precondition failed: check the company's vehicle count "
        + "against the max_trains setting, and whether the depot already holds unassembled "
        + "stock from earlier in this step");
    }
    return out;
  }

  // The first precondition that is actually violated, named in words an agent can use.
  // Order matters: the most specific and most commonly hit come first, because only the
  // first is reported.
  function _Diagnose(hint) {
    if ("tile" in hint && GSMap.IsValidTile(hint.tile)) {
      local tile = hint.tile;
      if (GSStation.GetStationID(tile) != GSStation.STATION_INVALID) {
        return "a station already occupies this tile, so there is nothing to build here";
      }
      if (GSBridge.IsBridgeTile(tile)) return "a bridge already crosses this tile";
      if (GSTunnel.IsTunnelTile(tile)) return "a tunnel already runs under this tile";
      if ("wants" in hint && hint.wants == "land" && GSTile.IsWaterTile(tile)) {
        return "this tile is water, and what was asked for needs land";
      }
      if ("wants" in hint && hint.wants == "water" && !GSTile.IsWaterTile(tile)) {
        return "this tile is not water, and what was asked for needs water";
      }
      if (GSRail.IsRailTile(tile)) return "this tile already carries rail";
      if (GSRoad.IsRoadTile(tile)) return "this tile already carries road";
      if (!GSTile.IsBuildable(tile)) {
        local owner = GSTile.GetOwner(tile);
        local me = this._Who(hint);
        if (owner != GSCompany.COMPANY_INVALID && me != GSCompany.COMPANY_INVALID
            && owner != me) {
          return "this tile is not buildable and belongs to someone else";
        }
        return "this tile is not buildable, so it must be cleared or levelled first";
      }
    }

    // Rail type is invisible to an agent otherwise: get_rail_types cannot name the types,
    // so a mismatch between an engine and the track it was bought for is unlearnable from
    // anything except this message.
    if ("engine" in hint && GSEngine.IsValidEngine(hint.engine)) {
      local engine = hint.engine;
      if (!GSEngine.IsBuildable(engine)) {
        return "this engine cannot be bought in the current year";
      }
      // Rail type, without requiring the depot tile to look like plain track: a depot is
      // its own tile kind, so IsRailTile is false there and the check never fired.
      if (GSEngine.GetVehicleType(engine) == GSVehicle.VT_RAIL
          && "depot" in hint && GSMap.IsValidTile(hint.depot)) {
        local want = GSEngine.GetRailType(engine);
        local have = GSRail.GetRailType(hint.depot);
        if (want != have) {
          return "this engine needs rail type " + want + " and that depot is rail type "
               + have + ", so build the depot and its track with rail_type " + want
               + ", or pick an engine for rail type " + have;
        }
      }
      local balance = this._Balance(hint);
      local price = GSEngine.GetPrice(engine);
      if (balance != null && price > balance) {
        return "this costs " + price + " and the balance is only " + balance;
      }
    }

    if ("cost" in hint) {
      local balance = this._Balance(hint);
      if (balance != null && hint.cost > balance) {
        return "this costs " + hint.cost + " and the balance is only " + balance;
      }
    }
    return null;
  }

  // Which company is acting. A GameScript owns no company of its own: handlers act
  // through GSCompanyMode(p.company_id), so the id travels in the hint rather than being
  // guessed from COMPANY_SELF, which resolves only while that mode object is alive.
  function _Who(hint) {
    if ("company" in hint) return GSCompany.ResolveCompanyID(hint.company);
    return GSCompany.ResolveCompanyID(GSCompany.COMPANY_SELF);
  }

  function _Balance(hint) {
    local who = this._Who(hint);
    if (who == GSCompany.COMPANY_INVALID) return null;
    return GSCompany.GetBankBalance(who);
  }

  // Walk the finished route and ask the game whether it actually joins up.
  //
  // Counting successful builds is not the same question. A segment can build and still
  // leave the line unconnected, and ERR_ALREADY_BUILT tells you something is there but
  // not that it links to its neighbour. This is the only check that answers "can a
  // vehicle get from one end to the other", which is the thing the caller wanted.
  //
  // Reported rather than enforced: a break here is worth knowing about even when every
  // build succeeded, and refusing on it would discard work that is already paid for.
  // Whether a tile already lets a train pass from prev to next.
  //
  // Two ways it can. The track joining those neighbours is already laid, which is what
  // AreTilesConnected answers. Or the tile is part of a station, which trains run through
  // by definition and on which no track can be laid at all.
  function _AlreadyCarriesRail(prev_tile, cur_tile, next_tile) {
    if (GSStation.GetStationID(cur_tile) != GSStation.STATION_INVALID) return true;
    return GSRail.AreTilesConnected(prev_tile, cur_tile, next_tile);
  }

  // Where a train can get into or out of a rail station.
  //
  // A platform is a LINE, not a doorway. It has an axis, given by
  // GetRailStationDirection as a RAILTRACK value, and a train enters along that axis at
  // either end. Track laid against the side of a platform connects to nothing, however
  // adjacent it looks.
  //
  // This is the geometry that made every route in this project earn nothing. A station
  // whose platform ran along x at (76,184) to (78,184) was joined by track at (78,183),
  // perpendicular, and both real entry tiles were empty. connect_rail reported it built,
  // a route was registered, and the train ran 105 days and delivered nothing.
  //
  // Returns the tiles just beyond each end, walking the platform to find them, so it works
  // from ANY tile of the station rather than only its corner.
  function _RailStationEntries(tile) {
    if (!GSRail.IsRailStationTile(tile)) return [];
    local sid = GSStation.GetStationID(tile);
    local along_x = (GSRail.GetRailStationDirection(tile) == GSRail.RAILTRACK_NE_SW);
    local dx = along_x ? 1 : 0;
    local dy = along_x ? 0 : 1;
    local x = GSMap.GetTileX(tile), y = GSMap.GetTileY(tile);

    // Walk to each end of this platform.
    local lo_x = x, lo_y = y;
    while (true) {
      local next = GSMap.GetTileIndex(lo_x - dx, lo_y - dy);
      if (!GSMap.IsValidTile(next) || !GSRail.IsRailStationTile(next)) break;
      if (GSStation.GetStationID(next) != sid) break;
      lo_x -= dx; lo_y -= dy;
    }
    local hi_x = x, hi_y = y;
    while (true) {
      local next = GSMap.GetTileIndex(hi_x + dx, hi_y + dy);
      if (!GSMap.IsValidTile(next) || !GSRail.IsRailStationTile(next)) break;
      if (GSStation.GetStationID(next) != sid) break;
      hi_x += dx; hi_y += dy;
    }

    // Each entry carries the platform tile it adjoins. The last piece of track is built
    // with the platform as its `next`, and BuildRail needs that to be ADJACENT. Handing it
    // the station's origin instead left the line one tile short of the entry: measured at
    // (77,155), with the entry (76,155) empty, because the origin (73,155) was three tiles
    // away and the final segment could not be built.
    local entries = [];
    local before = GSMap.GetTileIndex(lo_x - dx, lo_y - dy);
    local after = GSMap.GetTileIndex(hi_x + dx, hi_y + dy);
    if (GSMap.IsValidTile(before)) {
      entries.append({ entry = before, platform = GSMap.GetTileIndex(lo_x, lo_y) });
    }
    if (GSMap.IsValidTile(after)) {
      entries.append({ entry = after, platform = GSMap.GetTileIndex(hi_x, hi_y) });
    }
    return entries;
  }

  // Whether track could ever be laid on an entry tile.
  //
  // Buildable, or already carrying rail. A town building, a body of water or another
  // company's property is none of those, and near a town that is the common case rather
  // than the exception.
  // What is left of a station after part of it was removed.
  //
  // `station_gone` is the field that matters: a caller that asked for one tile of a longer
  // platform gets success and a station that is still standing, and nothing else in the
  // reply distinguishes that from a demolition.
  function _StationRemains(tile, tiles_asked) {
    local sid = GSStation.GetStationID(tile);
    local gone = (sid == GSStation.STATION_INVALID) || !GSStation.IsValidStation(sid);
    local out = { tiles_requested = tiles_asked, station_gone = gone };
    if (!gone) {
      out.rawset("station_id", sid);
      out.rawset("name", GSBaseStation.GetName(sid));
    }
    return out;
  }

  function _EntryIsUsable(entry) {
    return GSTile.IsBuildable(entry) || GSRail.IsRailTile(entry);
  }

  // Whether a train can actually pass from an entry tile into the platform it adjoins.
  //
  // This is the question, and has_rail is not it. Track on an entry tile can lead
  // anywhere: laid without a hint, the last piece of a connection points away from the
  // platform, so the entry carries rail that joins nothing. Measured on a passenger route
  // whose entry reported has_rail true while the train reached the tile beyond it, turned
  // around, and carried nobody for eleven steps.
  //
  // A train may arrive at the entry from any side, including around a corner, so every
  // neighbour is offered to AreTilesConnected rather than only the one along the axis.
  function _CanEnterPlatform(entry, platform) {
    if (!GSRail.IsRailTile(entry)) return false;
    local x = GSMap.GetTileX(entry), y = GSMap.GetTileY(entry);
    local around = [
      GSMap.GetTileIndex(x + 1, y), GSMap.GetTileIndex(x - 1, y),
      GSMap.GetTileIndex(x, y + 1), GSMap.GetTileIndex(x, y - 1),
    ];
    foreach (side in around) {
      if (side == platform || !GSMap.IsValidTile(side)) continue;
      if (GSRail.AreTilesConnected(side, entry, platform)) return true;
    }
    return false;
  }

  // The entry a line coming from `towards` should aim at.
  //
  // Nearest USABLE end, not simply nearest. Distance alone sent two routes in one session
  // at an entry that was a town building: at Mennbury the blocked entry was four tiles
  // nearer than the clear one, so it was chosen twice, and each attempt failed on the same
  // tile with ERR_AREA_NOT_CLEAR. A route that cannot be built is not closer to anything.
  function _NearestRailEntry(station_tile, towards) {
    local entries = this._RailStationEntries(station_tile);
    if (entries.len() == 0) return null;
    local best = null;
    local best_d = 0;
    // Two passes over the same list: usable ends first, and only if none is usable does
    // the nearest blocked one come back, so the caller still gets a refusal that names a
    // tile rather than nothing at all.
    for (local pass = 0; pass < 2; pass++) {
      foreach (candidate in entries) {
        if (pass == 0 && !this._EntryIsUsable(candidate.entry)) continue;
        local d = GSMap.DistanceManhattan(candidate.entry, towards);
        if (best == null || d < best_d) { best = candidate; best_d = d; }
      }
      if (best != null) return best;
    }
    return best;
  }

  function _RouteGaps(path, is_rail) {
    local gaps = [];
    for (local i = 1; i < path.len(); i++) {
      local a = path[i - 1].tile;
      local b = path[i].tile;
      // Bridges and tunnels span more than one tile, so adjacency does not apply.
      if (GSMap.DistanceManhattan(a, b) != 1) continue;
      // A station tile gets NO special treatment here, deliberately. Treating one as
      // automatically joined was tried and is wrong: a platform is enterable along its own
      // axis and not across it, AreTilesConnected answers that correctly, and overriding it
      // hid the most expensive failure in the game.
      //
      // AreTilesConnected asks about the MIDDLE tile of a triple: can a train reach `to`
      // from `from` by way of `tile`. So it needs a tile on each side, and the first
      // segment has nothing before it.
      //
      // Passing `a` as its own predecessor, which is what this did, asks whether a train
      // can enter a tile from itself. That is always false, so every route ever built
      // reported a gap on its first segment, every connect_rail came back "partial", and
      // a line with nothing wrong with it was indistinguishable from a broken one.
      //
      // The interior triples are what this can honestly answer. Whether the two ends
      // reach their stations is a different question, answered by the entry tiles in
      // get_station_info, and guessing at it here produced the false alarm.
      if (is_rail && i < 2) continue;
      local joined = is_rail
        ? GSRail.AreTilesConnected(path[i - 2].tile, a, b)
        : GSRoad.AreRoadTilesConnected(a, b);
      if (!joined) gaps.append({ x = path[i].x, y = path[i].y });
    }
    return gaps;
  }

  // Why a connection came back partial, in one line, from whichever of the two things
  // went wrong.
  //
  // This used to read failed[0] unconditionally. A route whose segments all built but
  // whose gap check complained has an EMPTY failed list, so the index threw, the whole
  // command died inside the dispatcher's catch, and connect_rail answered every caller
  // with "the index '0' does not exist" and built nothing it could report. Combined with
  // the spurious first-segment gap above, that broke connect_rail outright.
  function _PartialError(failed, total, gaps = null) {
    if (failed.len() > 0) {
      local first = failed[0];
      return failed.len() + " of " + total + " segments failed, first at ("
             + first.x + "," + first.y + "): " + first.error;
    }
    if (gaps != null && gaps.len() > 0) {
      local first = gaps[0];
      return "every segment built, but the line is not continuous: " + gaps.len()
             + " of " + total + " have no through connection, first at ("
             + first.x + "," + first.y + ")";
    }
    return "connection incomplete";
  }

  // The kind of failure, as a stable token, alongside the sentence that describes it.
  //
  // A compound build sends no error_code, so error_name is empty on every connect ever
  // recorded, and the analysis reports fall back to grouping on the whole message. That
  // message names counts and a tile, so "1 of 37 ... at (19,40)" and "2 of 37 ... at
  // (21,44)" are different groups, each counted once, and the top-errors cap then evicts
  // the refusals that genuinely repeat. Grouping wants a label, not prose.
  function _PartialName(failed, gaps) {
    if (failed.len() > 0) return "SEGMENTS_FAILED";
    if (gaps != null && gaps.len() > 0) return "ROUTE_DISCONTINUOUS";
    return "CONNECTION_INCOMPLETE";
  }

  function _BuildRoadPath(path) {
    local built = 0;
    local existing = 0;
    local failed = [];
    for (local i = 1; i < path.len(); i++) {
      if (i % 50 == 0) this.Sleep(1); // Yield on long paths to avoid blocking
      local prev = path[i - 1];
      local cur = path[i];
      local prev_tile = prev.tile;
      local cur_tile = cur.tile;
      local dist = GSMap.DistanceManhattan(prev_tile, cur_tile);
      // Bridge segment.
      if ("bridge_start" in cur) {
        local bridge_list = GSBridgeList_Length(dist + 1);
        if (!bridge_list.IsEmpty() &&
            GSBridge.BuildBridge(GSVehicle.VT_ROAD, bridge_list.Begin(), cur.bridge_start, cur_tile)) {
          built++;
        } else {
          local err = GSError.GetLastErrorString();
          if (err == "ERR_ALREADY_BUILT") { existing++; }
          else { failed.append({ x = cur.x, y = cur.y, action = "bridge", error = err, error_code = GSError.GetLastError(), error_category = GSError.GetErrorCategory() }); }
        }
        continue;
      }
      // Tunnel segment.
      if ("tunnel_start" in cur) {
        if (GSTunnel.BuildTunnel(GSVehicle.VT_ROAD, cur.tunnel_start)) {
          built++;
        } else {
          local err = GSError.GetLastErrorString();
          if (err == "ERR_ALREADY_BUILT") { existing++; }
          else { failed.append({ x = cur.x, y = cur.y, action = "tunnel", error = err, error_code = GSError.GetLastError(), error_category = GSError.GetErrorCategory() }); }
        }
        continue;
      }
      // Normal road segment (adjacent tiles).
      if (dist == 1) {
        if (GSRoad.AreRoadTilesConnected(prev_tile, cur_tile)) {
          existing++; // Already connected: nothing built, nothing paid.
        } else if (GSRoad.BuildRoad(prev_tile, cur_tile)) {
          built++;
        } else {
          local err = GSError.GetLastErrorString();
          if (err == "ERR_ALREADY_BUILT") { existing++; }
          else { failed.append({ x = cur.x, y = cur.y, action = "road", error = err, error_code = GSError.GetLastError(), error_category = GSError.GetErrorCategory() }); }
        }
      }
      // Traversal over existing bridge/tunnel (dist > 1, no build needed).
      else {
        existing++;
      }
    }
    return { built = built, existing = existing, failed = failed };
  }

  function CmdConnectRoad(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local road_type = ("road_type" in p) ? p.road_type : 0;
    GSRoad.SetCurrentRoadType(road_type);
    local pair = this._ResolveTilePair(p);
    if (pair == null) return { success = false, error = "Need tile_from+tile_to or from_x,from_y,to_x,to_y" };
    local max_iter = ("max_iterations" in p) ? p.max_iterations : 50000;

    // Phase 1: Pathfind (runs in GSTestMode internally).
    local pf = this._FindRoadPath(pair.from.tile, pair.to.tile, max_iter);
    if (!pf.success) {
      return { success = false, error = "No road path found after " + pf.iterations + " iterations",
               result = { iterations = pf.iterations } };
    }

    // Phase 2: Build the road.
    local build = this._BuildRoadPath(pf.path);

    // Compact path for response (just coordinates, skip meta).
    local path_coords = [];
    foreach (pt in pf.path) {
      path_coords.append({ x = pt.x, y = pt.y });
    }

    // A segment that would not build leaves a gap, and a gap means no route. Saying
    // success here made a broken line indistinguishable from a working one to the
    // caller, the action log, and the route report.
    local gaps = this._RouteGaps(pf.path, false);
    local complete = (build.failed.len() == 0 && gaps.len() == 0);
    return { success = complete,
      error = complete ? null : this._PartialError(build.failed, pf.path.len(), gaps),
      error_name = complete ? null : this._PartialName(build.failed, gaps),
      result = {
      status = complete ? "complete" : "partial",
      path_length = pf.path.len(),
      built = build.built,
      existing = build.existing,
      failed = build.failed,
      gaps = gaps,
      iterations = pf.iterations,
      path = path_coords
    }};
  }

  // ===========================================================================
  // BUILDING: RAIL
  // ===========================================================================

  // CmdBuildRail used to sit here, dispatched by nothing. It asked the caller for the
  // prev/curr/next triple that GSRail.BuildRail needs, which is exactly the arithmetic
  // build_path already does from a plain list of tiles. Its second branch guessed the
  // missing context by extrapolating, and reported success if either guess took, so a
  // caller could not tell which piece it had actually laid.
  //
  // CmdBuildRailTrack stays, because it is the one thing build_path cannot say: a single
  // piece with a chosen orientation, which is what a siding or a junction stub is. It is
  // also the inverse of remove_rail_track, and a remove with no build is not a surface.
  function CmdBuildRailTrack(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local rail_type = ("rail_type" in p) ? p.rail_type : 0;
    local track = ("track" in p) ? p.track : GSRail.RAILTRACK_NE_SW;
    GSRail.SetCurrentRailType(rail_type);
    local tile = GSMap.GetTileIndex(p.x, p.y);
    if (GSRail.BuildRailTrack(tile, track)) return { success = true, result = { tile = [p.x, p.y] } };
    return this._Refused();
  }

  function CmdBuildRailStation(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local rail_type = ("rail_type" in p) ? p.rail_type : 0;
    local dir = ("direction" in p) ? p.direction : 0;
    local platforms = ("num_platforms" in p) ? p.num_platforms : 2;
    local length = ("platform_length" in p) ? p.platform_length : 5;
    GSRail.SetCurrentRailType(rail_type);
    // Resolved rather than read straight off p, so a caller who passes `tile` is served
    // as the manifest promises, and one who passes nothing is told what is missing
    // instead of getting the Squirrel message "the index 'x' does not exist".
    local r = this._ResolveTile(p);
    if (r == null) return { success = false, error = "Need tile or x,y" };
    local tile = r.tile;
    local track = (dir == 1) ? GSRail.RAILTRACK_NW_SE : GSRail.RAILTRACK_NE_SW;
    if (GSRail.BuildRailStation(tile, track, platforms, length, GSStation.STATION_NEW)) {
      local sid = GSStation.GetStationID(tile);
      return { success = true, result = { tile = [r.x, r.y], platforms = platforms, length = length, station_id = sid } };
    }
    return this._Refused({ tile = tile, wants = "land", company = p.company_id });
  }

  function CmdBuildRailDepot(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local rail_type = ("rail_type" in p) ? p.rail_type : 0;
    local dir = ("direction" in p) ? p.direction : 0;
    GSRail.SetCurrentRailType(rail_type);
    local r = this._ResolveTile(p);
    if (r == null) return { success = false, error = "Need tile or x,y" };
    local tile = r.tile;
    local front = this._GetAdjacentTile(tile, dir);
    if (!GSRail.BuildRailDepot(tile, front)) {
      return this._Refused({ tile = tile, wants = "land", company = p.company_id });
    }
    // Auto-connect: build rail on the front tile linking existing track to depot.
    // Find an adjacent rail tile next to the front tile (excluding the depot tile)
    // and build a rail piece: adj_rail -> front -> depot.
    local connected = false;
    local adj = this._GetAdjacentRailTrack(GSMap.GetTileX(front), GSMap.GetTileY(front));
    foreach (a in adj) {
      local adj_tile = GSMap.GetTileIndex(a.nx, a.ny);
      if (adj_tile == tile) continue;
      if (GSRail.BuildRail(adj_tile, front, tile)) {
        connected = true;
        break;
      }
    }
    return { success = true, result = { tile = [r.x, r.y], connected = connected } };
  }

  function CmdBuildRailSignal(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local signal_type = ("signal_type" in p) ? p.signal_type : 0;
    local tile = GSMap.GetTileIndex(p.x, p.y);
    if (GSRail.BuildSignal(tile, tile, signal_type)) return { success = true, result = { tile = [p.x, p.y] } };
    return this._Refused();
  }

  function CmdBuildRailWaypoint(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local tile = GSMap.GetTileIndex(p.x, p.y);
    if (GSRail.BuildRailWaypoint(tile)) return { success = true, result = { tile = [p.x, p.y] } };
    return this._Refused();
  }

  function CmdRemoveRail(p) {
    local company_mode = GSCompanyMode(p.company_id);
    // Three tiles, not two. GSRail.RemoveRail takes the same prev/curr/next triple that
    // BuildRail does: it removes the piece AT the middle tile that joins the other two.
    // The manifest described it as "along a line between two tiles" and listed from_x and
    // x as if they were alternatives, so the documented call was missing an argument and
    // failed with the Squirrel message for whichever field was absent.
    local from_r = this._ResolveTile(p, "from_");
    local mid_r = this._ResolveTile(p);
    local to_r = this._ResolveTile(p, "to_");
    if (from_r == null || mid_r == null || to_r == null) {
      return { success = false,
               error = "remove_rail needs three tiles: from_x,from_y then x,y then "
                       + "to_x,to_y. It removes the piece at x,y joining from to to." };
    }
    if (GSRail.RemoveRail(from_r.tile, mid_r.tile, to_r.tile)) return { success = true, result = {} };
    return this._Refused();
  }

  function CmdRemoveRailTrack(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local track = ("track" in p) ? p.track : GSRail.RAILTRACK_NE_SW;
    local r = this._ResolveTile(p);
    if (r == null) return { success = false, error = "Need tile or x,y" };
    if (GSRail.RemoveRailTrack(r.tile, track)) return { success = true, result = { tile = r.tile } };
    return this._Refused();
  }

  function CmdRemoveSignal(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local r = this._ResolveTile(p);
    if (r == null) return { success = false, error = "Need tile or x,y" };
    // If front_tile or front_x,front_y given, use directly
    if ("front_tile" in p) {
      local ft = p.front_tile.tointeger();
      if (GSRail.RemoveSignal(r.tile, ft)) return { success = true, result = {} };
      return this._Refused();
    }
    if (("front_x" in p) && ("front_y" in p)) {
      local ft = GSMap.GetTileIndex(p.front_x, p.front_y);
      if (GSRail.RemoveSignal(r.tile, ft)) return { success = true, result = {} };
      return this._Refused();
    }
    // Auto-detect: try all 4 adjacent tiles as front
    local offsets = [
      GSMap.GetTileIndex(1, 0) - GSMap.GetTileIndex(0, 0),
      GSMap.GetTileIndex(0, 1) - GSMap.GetTileIndex(0, 0),
      -(GSMap.GetTileIndex(1, 0) - GSMap.GetTileIndex(0, 0)),
      -(GSMap.GetTileIndex(0, 1) - GSMap.GetTileIndex(0, 0))
    ];
    foreach (off in offsets) {
      local ft = r.tile + off;
      if (GSMap.IsValidTile(ft) && GSRail.RemoveSignal(r.tile, ft)) {
        return { success = true, result = {} };
      }
    }
    return { success = false, error = "No signal found at tile or " + GSError.GetLastErrorString() };
  }

  function CmdRemoveRailStation(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local keep_rail = ("keep_rail" in p) ? p.keep_rail : false;
    // Accept single tile (removes that platform tile) or x1,y1,x2,y2 rectangle
    // Say what survived. This returned an empty table, so removing ONE tile of a three tile
    // platform was indistinguishable from removing the station: the caller saw success and
    // a station that was still there, still serving, still named in every later report.
    // A single tile is a one tile rectangle, which is correct and is exactly why the reply
    // has to state the consequence rather than the fact that a command was accepted.
    local r = this._ResolveTile(p);
    if (r != null) {
      if (GSRail.RemoveRailStationTileRectangle(r.tile, r.tile, keep_rail)) {
        return { success = true, result = this._StationRemains(r.tile, 1) };
      }
      return this._Refused();
    }
    if (("x1" in p) && ("y1" in p) && ("x2" in p) && ("y2" in p)) {
      local tile1 = GSMap.GetTileIndex(p.x1, p.y1);
      local tile2 = GSMap.GetTileIndex(p.x2, p.y2);
      local wide = abs(p.x2 - p.x1) + 1;
      local tall = abs(p.y2 - p.y1) + 1;
      if (GSRail.RemoveRailStationTileRectangle(tile1, tile2, keep_rail)) {
        return { success = true, result = this._StationRemains(tile1, wide * tall) };
      }
      return this._Refused();
    }
    return { success = false, error = "Need tile or x,y or x1,y1,x2,y2" };
  }

  function CmdConvertRail(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local rail_type = ("rail_type" in p) ? p.rail_type : 0;
    // Accept single tile or x1,y1,x2,y2 rectangle
    local r = this._ResolveTile(p);
    if (r != null) {
      if (GSRail.ConvertRailType(r.tile, r.tile, rail_type)) return { success = true, result = {} };
      return this._Refused();
    }
    if (("x1" in p) && ("y1" in p) && ("x2" in p) && ("y2" in p)) {
      local tile1 = GSMap.GetTileIndex(p.x1, p.y1);
      local tile2 = GSMap.GetTileIndex(p.x2, p.y2);
      if (GSRail.ConvertRailType(tile1, tile2, rail_type)) return { success = true, result = {} };
      return this._Refused();
    }
    return { success = false, error = "Need tile or x,y or x1,y1,x2,y2" };
  }

  // ===========================================================================
  // COMPOUND: CONNECT RAIL (direction-aware A* pathfind + build)
  // Rail requires 3-tile context (prev, cur, next) for track direction.
  // Cost model matches nttd's Python rail pathfinder: flat=100, slope=+200,
  // curve_45=+100, curve_90=+600, bridge/tunnel per tile, no U-turns.
  // ===========================================================================

  // A* rail pathfinder. Direction-aware: state = (tile, entry_direction).
  // No U-turns allowed. Bridge/tunnel only in straight direction.
  // Runs inside GSTestMode. Returns path or null.
  function _FindRailPath(from_tile, to_tile, max_iterations) {
    local test_mode = GSTestMode();
    // Cost parameters: matching nttd Python rail pathfinder (rail.py).
    local C_FLAT = 100;
    local C_SLOPE = 200;
    local C_CURVE_45 = 100;
    local C_CURVE_90 = 600;
    // A corner on sloped ground: often refused by the game, so worth a long detour to
    // avoid, but never worth failing to find a route over.
    local C_SLOPED_CURVE = 2000;
    local C_CROSSING = 300;
    local C_BRIDGE = 150;
    local C_TUNNEL = 120;
    local C_MAX = 10000000;
    local MAX_BRIDGE = 6;
    local MAX_TUNNEL = 6;

    local from_x = GSMap.GetTileX(from_tile);
    local from_y = GSMap.GetTileY(from_tile);
    local to_x = GSMap.GetTileX(to_tile);
    local to_y = GSMap.GetTileY(to_tile);
    local map_sx = GSMap.GetMapSizeX();

    // Direction offsets: 0=NE(+x), 1=SE(+y), 2=SW(-x), 3=NW(-y)
    local dir_dx = [1, 0, -1, 0];
    local dir_dy = [0, 1, 0, -1];

    local open = this._HeapCreate();
    local g_cost = {};
    local came_from = {};
    local state_tile = {};
    local state_dir = {};
    local state_meta = {};  // bridge/tunnel metadata

    // Seed: enter start from all 4 directions.
    for (local d = 0; d < 4; d++) {
      local key = from_tile * 4 + d;
      g_cost[key] <- 0;
      came_from[key] <- -1;
      state_tile[key] <- from_tile;
      state_dir[key] <- d;
      state_meta[key] <- null;
      local h = this._Heuristic(from_x, from_y, to_x, to_y) * C_FLAT;
      this._HeapPush(open, h, key);
    }

    local iterations = 0;
    local found_key = -1;
    local visited = {};

    while (open.len() > 0 && iterations < max_iterations) {
      iterations++;
      // Yield every 500 iterations and process pending events so other agents
      // aren't blocked by pathfinding. Pathfind commands are queued for later.
      if (iterations % 500 == 0) this._YieldAndProcessEvents();
      local node = this._HeapPop(open);
      local cur_key = node.v;
      if (cur_key in visited) continue;
      visited[cur_key] <- true;

      local cur_tile = state_tile[cur_key];
      local cur_g = g_cost[cur_key];
      local entry_dir = state_dir[cur_key];

      if (cur_g >= C_MAX) continue;

      // Goal check.
      if (cur_tile == to_tile) {
        found_key = cur_key;
        break;
      }

      // Try all 4 exit directions except reverse (no U-turn).
      local reverse_dir = (entry_dir + 2) % 4;
      for (local exit_dir = 0; exit_dir < 4; exit_dir++) {
        if (exit_dir == reverse_dir) continue;

        local nx = GSMap.GetTileX(cur_tile) + dir_dx[exit_dir];
        local ny = GSMap.GetTileY(cur_tile) + dir_dy[exit_dir];
        local next_tile = GSMap.GetTileIndex(nx, ny);
        if (!GSMap.IsValidTile(next_tile)) continue;

        // Determine turn cost.
        local turn = (exit_dir - entry_dir + 4) % 4;
        local turn_cost = 0;
        if (turn == 1 || turn == 3) turn_cost = C_CURVE_45;

        // Turning on a slope is expensive, NOT forbidden.
        //
        // The game refuses SOME curves on SOME slopes with ERR_LAND_SLOPED_WRONG, and
        // which ones depends on the particular slope and the particular track piece.
        // Rejecting every turn on every non flat tile, which is what this did first, is
        // both wrong and ruinous: it prunes so much of the search that A* exhausts its
        // 50000 iterations on hilly ground and reports no path at all, on corridors that
        // had always connected.
        //
        // So it is priced instead. A flat corner is preferred wherever one exists, which
        // is what the case that prompted this needed: a 37 tile corridor failed on one
        // segment at (19,40), slope 2, entered from (19,39) and left to (20,40), while
        // both neighbours were flat and turning a tile earlier cost nothing. Where no flat
        // corner exists the path is still found, and a segment the game then refuses is
        // reported honestly as a failed segment, which is the outcome an agent can act on.
        //
        // Not applied at the seed: the start is pushed with all four directions, so
        // entry_dir there is an artificial approach rather than a real one, and the real
        // one comes from the station platform via the hint.
        if (turn != 0 && came_from[cur_key] != -1 &&
            GSTile.GetSlope(cur_tile) != GSTile.SLOPE_FLAT) {
          turn_cost += C_SLOPED_CURVE;
        }
        // turn == 2 is U-turn, already blocked

        // Check if tile is passable.
        local is_buildable = GSTile.IsBuildable(next_tile);
        local has_rail = GSRail.IsRailTile(next_tile);
        local has_road = GSRoad.IsRoadTile(next_tile);
        local is_water = GSTile.IsWaterTile(next_tile);

        if (is_buildable || has_rail || has_road) {
          local edge_cost = C_FLAT + turn_cost;
          // Slope penalty.
          if (GSTile.GetSlope(next_tile) != GSTile.SLOPE_FLAT) edge_cost += C_SLOPE;
          // Existing rail is cheaper to traverse.
          if (has_rail) edge_cost = edge_cost / 2;
          // Road crossing penalty.
          else if (has_road) edge_cost += C_CROSSING;

          local next_key = next_tile * 4 + exit_dir;
          local tentative_g = cur_g + edge_cost;
          if (tentative_g < C_MAX &&
              (!(next_key in g_cost) || tentative_g < g_cost[next_key])) {
            g_cost[next_key] <- tentative_g;
            came_from[next_key] <- cur_key;
            state_tile[next_key] <- next_tile;
            state_dir[next_key] <- exit_dir;
            state_meta[next_key] <- null;
            local h = this._Heuristic(nx, ny, to_x, to_y) * C_FLAT;
            this._HeapPush(open, tentative_g + h, next_key);
          }
        }

        // Try bridge/tunnel when going straight AND tile is impassable, water,
        // or has steep slope (height diff > 1).
        local try_bridge_tunnel = (!is_buildable && !has_rail) || is_water ||
          (GSMap.IsValidTile(next_tile) &&
           abs(GSTile.GetMaxHeight(next_tile) - GSTile.GetMaxHeight(cur_tile)) > 1);
        if (try_bridge_tunnel && exit_dir == entry_dir) {
          // Try bridge.
          for (local blen = 2; blen <= MAX_BRIDGE; blen++) {
            local bx = GSMap.GetTileX(cur_tile) + dir_dx[exit_dir] * blen;
            local by = GSMap.GetTileY(cur_tile) + dir_dy[exit_dir] * blen;
            local b_tile = GSMap.GetTileIndex(bx, by);
            if (!GSMap.IsValidTile(b_tile)) break;
            local bridge_list = GSBridgeList_Length(blen + 1);
            if (!bridge_list.IsEmpty() &&
                GSBridge.BuildBridge(GSVehicle.VT_RAIL, bridge_list.Begin(), cur_tile, b_tile)) {
              local edge_cost = blen * C_BRIDGE;
              local next_key = b_tile * 4 + exit_dir;
              local tentative_g = cur_g + edge_cost;
              if (tentative_g < C_MAX &&
                  (!(next_key in g_cost) || tentative_g < g_cost[next_key])) {
                g_cost[next_key] <- tentative_g;
                came_from[next_key] <- cur_key;
                state_tile[next_key] <- b_tile;
                state_dir[next_key] <- exit_dir;
                state_meta[next_key] <- { is_bridge = true, bridge_start = cur_tile };
                local h = this._Heuristic(bx, by, to_x, to_y) * C_FLAT;
                this._HeapPush(open, tentative_g + h, next_key);
              }
              break; // Take shortest viable bridge.
            }
          }
          // Try tunnel.
          local slope = GSTile.GetSlope(cur_tile);
          if (slope != GSTile.SLOPE_FLAT) {
            local other_end = GSTunnel.GetOtherTunnelEnd(cur_tile);
            if (GSMap.IsValidTile(other_end)) {
              local tunnel_len = GSMap.DistanceManhattan(cur_tile, other_end);
              if (tunnel_len >= 2 && tunnel_len <= MAX_TUNNEL &&
                  GSTunnel.BuildTunnel(GSVehicle.VT_RAIL, cur_tile)) {
                local edge_cost = tunnel_len * C_TUNNEL;
                local next_key = other_end * 4 + exit_dir;
                local tentative_g = cur_g + edge_cost;
                if (tentative_g < C_MAX &&
                    (!(next_key in g_cost) || tentative_g < g_cost[next_key])) {
                  g_cost[next_key] <- tentative_g;
                  came_from[next_key] <- cur_key;
                  state_tile[next_key] <- other_end;
                  state_dir[next_key] <- exit_dir;
                  state_meta[next_key] <- { is_tunnel = true, tunnel_start = cur_tile };
                  local ox = GSMap.GetTileX(other_end);
                  local oy = GSMap.GetTileY(other_end);
                  local h = this._Heuristic(ox, oy, to_x, to_y) * C_FLAT;
                  this._HeapPush(open, tentative_g + h, next_key);
                }
              }
            }
          }
        }
      }
    }

    if (found_key == -1) {
      return { success = false, iterations = iterations };
    }

    // Reconstruct path with direction info (needed for 3-tile building).
    local path = [];
    local key = found_key;
    while (key != -1) {
      local t = state_tile[key];
      local entry = {
        tile = t,
        x = GSMap.GetTileX(t),
        y = GSMap.GetTileY(t),
        dir = state_dir[key]
      };
      if (state_meta[key] != null) {
        local m = state_meta[key];
        if ("is_bridge" in m) entry.rawset("bridge_start", m.bridge_start);
        if ("is_tunnel" in m) entry.rawset("tunnel_start", m.tunnel_start);
      }
      path.insert(0, entry);
      key = came_from[key];
    }
    return { success = true, path = path, iterations = iterations };
  }

  // Build rail along a path from _FindRailPath.
  // Rail needs 3-tile context: GSRail.BuildRail(prev, cur, next).
  function _BuildRailPath(path, from_hint = null, to_hint = null) {
    local built = 0;
    local existing = 0;
    local failed = [];

    for (local i = 0; i < path.len(); i++) {
      if (i > 0 && i % 50 == 0) this.Sleep(1); // Yield on long paths to avoid blocking
      local cur = path[i];
      local cur_tile = cur.tile;

      // Bridge segment.
      if ("bridge_start" in cur) {
        local dist = GSMap.DistanceManhattan(cur.bridge_start, cur_tile);
        local bridge_list = GSBridgeList_Length(dist + 1);
        if (!bridge_list.IsEmpty() &&
            GSBridge.BuildBridge(GSVehicle.VT_RAIL, bridge_list.Begin(), cur.bridge_start, cur_tile)) {
          built++;
        } else {
          local err = GSError.GetLastErrorString();
          if (err == "ERR_ALREADY_BUILT") { existing++; }
          else { failed.append({ x = cur.x, y = cur.y, action = "bridge", error = err, error_code = GSError.GetLastError(), error_category = GSError.GetErrorCategory() }); }
        }
        continue;
      }
      // Tunnel segment.
      if ("tunnel_start" in cur) {
        if (GSTunnel.BuildTunnel(GSVehicle.VT_RAIL, cur.tunnel_start)) {
          built++;
        } else {
          local err = GSError.GetLastErrorString();
          if (err == "ERR_ALREADY_BUILT") { existing++; }
          else { failed.append({ x = cur.x, y = cur.y, action = "tunnel", error = err, error_code = GSError.GetLastError(), error_category = GSError.GetErrorCategory() }); }
        }
        continue;
      }

      // Normal rail: needs prev_tile, cur_tile, next_tile.
      local prev_tile, next_tile;
      if (i == 0 && path.len() > 1) {
        // First tile: use from_hint (station platform tile) if provided,
        // otherwise fall back to opposite-of-travel extrapolation.
        if (from_hint != null) {
          prev_tile = from_hint;
        } else {
          local opp = (cur.dir + 2) % 4;
          prev_tile = GSMap.GetTileIndex(cur.x + this._GetDirDx(opp), cur.y + this._GetDirDy(opp));
        }
        next_tile = path[1].tile;
      } else if (i == path.len() - 1 && path.len() > 1) {
        // Last tile: use to_hint (station platform tile) if provided,
        // otherwise fall back to continuing-travel extrapolation.
        prev_tile = path[i - 1].tile;
        if (to_hint != null) {
          next_tile = to_hint;
        } else {
          next_tile = GSMap.GetTileIndex(cur.x + this._GetDirDx(cur.dir), cur.y + this._GetDirDy(cur.dir));
        }
      } else if (path.len() == 1) {
        continue; // Single tile, nothing to build.
      } else {
        prev_tile = path[i - 1].tile;
        next_tile = path[i + 1].tile;
      }

      // Skip if prev or next is a bridge/tunnel landing (already built).
      if (i > 0 && ("bridge_start" in path[i - 1] || "tunnel_start" in path[i - 1])) {
        // Previous was bridge/tunnel end; prev context is the landing tile.
      }

      if (GSRail.BuildRail(prev_tile, cur_tile, next_tile)) {
        built++;
      } else {
        local err = GSError.GetLastErrorString();
        // A tile that already carries what this segment wanted is not a failure.
        //
        // Only an exact repeat of the same piece answers ERR_ALREADY_BUILT. A station
        // platform refuses with ERR_AREA_NOT_CLEAR, and a tile whose track already joins
        // its neighbours refuses with ERR_PRECONDITION_FAILED, so both were counted as
        // failed segments. The line was reported as partial when it was finished, and the
        // status is the only signal an agent has about whether it owns a working route.
        // Measured on one corridor: 7 of 36 segments reported failed, and every one of
        // them already carried usable track, four being the station platforms the call was
        // aimed at.
        if (err == "ERR_ALREADY_BUILT" || this._AlreadyCarriesRail(prev_tile, cur_tile, next_tile)) {
          existing++;
        } else {
          failed.append({ x = cur.x, y = cur.y, action = "rail", error = err, error_code = GSError.GetLastError(), error_category = GSError.GetErrorCategory() });
        }
      }
    }
    return { built = built, existing = existing, failed = failed };
  }

  function CmdConnectRail(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local rail_type = ("rail_type" in p) ? p.rail_type : 0;
    GSRail.SetCurrentRailType(rail_type);
    local pair = this._ResolveTilePair(p);
    if (pair == null) return { success = false, error = "Need tile_from+tile_to or from_x,from_y,to_x,to_y" };
    local max_iter = ("max_iterations" in p) ? p.max_iterations : 50000;

    // Optional hint tiles: the station platform tiles that the path endpoints
    // should connect back to. Used as prev_tile for first path tile and
    // next_tile for last path tile in _BuildRailPath.
    local from_hint = null;
    if ("from_hint_x" in p && "from_hint_y" in p) {
      from_hint = GSMap.GetTileIndex(p.from_hint_x, p.from_hint_y);
    }
    local to_hint = null;
    if ("to_hint_x" in p && "to_hint_y" in p) {
      to_hint = GSMap.GetTileIndex(p.to_hint_x, p.to_hint_y);
    }

    // Aim at the station ENTRY, not at any tile of the station.
    //
    // A platform is a line with an axis, and a train gets in only at its ends. Pathfinding
    // to a station tile lets the search arrive from whichever side is cheapest, which is
    // usually the side, and side-adjacent track connects to nothing. That is what made
    // every route in this project earn nothing: one line arrived at (78,183) against a
    // platform running along x, both real entries left empty, and the train ran 105 days
    // and delivered nothing while every layer reported a route.
    //
    // The endpoints move to the entry tiles; the hints stay pointing at the platform, so
    // the last piece still joins to the station itself. A station with no valid entry, at
    // the map edge, is left alone rather than guessed at.
    local from_tile = pair.from.tile;
    local to_tile = pair.to.tile;
    // The hint is taken from the entry rather than from the caller, because it has to be
    // the platform tile ADJOINING that entry. A caller naming any other tile of the
    // station leaves the final segment unbuildable, and the station's origin is the wrong
    // one whenever the line arrives at the far end.
    // An explicit hint from the caller means "I know which end I want", and is left alone.
    // Without this there was no way to override the choice at all: the hint parameters set
    // the hint and not the endpoint, so a caller who had worked out which entry was usable
    // could not say so, and watched the same blocked tile refuse twice.
    local caller_chose_from = (from_hint != null);
    local caller_chose_to = (to_hint != null);
    if (!caller_chose_from) {
      local from_entry = this._NearestRailEntry(from_tile, to_tile);
      if (from_entry != null) {
        from_hint = from_entry.platform;
        from_tile = from_entry.entry;
      }
    }
    if (!caller_chose_to) {
      local to_entry = this._NearestRailEntry(to_tile, from_tile);
      if (to_entry != null) {
        to_hint = to_entry.platform;
        to_tile = to_entry.entry;
      }
    }

    // Phase 1: Pathfind (runs in GSTestMode internally).
    local pf = this._FindRailPath(from_tile, to_tile, max_iter);
    if (!pf.success) {
      return { success = false, error = "No rail path found after " + pf.iterations + " iterations",
               result = { iterations = pf.iterations } };
    }

    // Phase 2: Build the rail.
    local build = this._BuildRailPath(pf.path, from_hint, to_hint);

    // Compact path for response.
    local path_coords = [];
    foreach (pt in pf.path) {
      path_coords.append({ x = pt.x, y = pt.y, dir = pt.dir });
    }

    // A segment that would not build leaves a gap, and a gap means no route. Saying
    // success here made a broken line indistinguishable from a working one to the
    // caller, the action log, and the route report.
    local gaps = this._RouteGaps(pf.path, true);
    local complete = (build.failed.len() == 0 && gaps.len() == 0);
    return { success = complete,
      error = complete ? null : this._PartialError(build.failed, pf.path.len(), gaps),
      error_name = complete ? null : this._PartialName(build.failed, gaps),
      result = {
      status = complete ? "complete" : "partial",
      path_length = pf.path.len(),
      built = build.built,
      existing = build.existing,
      failed = build.failed,
      gaps = gaps,
      iterations = pf.iterations,
      path = path_coords
    }};
  }

  // ===========================================================================
  // BUILDING: MARINE
  // ===========================================================================

  function CmdBuildCanal(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local tile = GSMap.GetTileIndex(p.x, p.y);
    if (GSMarine.BuildCanal(tile)) return { success = true, result = { tile = [p.x, p.y] } };
    return this._Refused();
  }

  function CmdBuildLock(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local tile = GSMap.GetTileIndex(p.x, p.y);
    if (GSMarine.BuildLock(tile)) return { success = true, result = { tile = [p.x, p.y] } };
    return this._Refused();
  }

  function CmdBuildBuoy(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local tile = GSMap.GetTileIndex(p.x, p.y);
    if (GSMarine.BuildBuoy(tile)) return { success = true, result = { tile = [p.x, p.y] } };
    return this._Refused();
  }

  function CmdBuildWaterDepot(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local tile = GSMap.GetTileIndex(p.x, p.y);
    local dir = ("direction" in p) ? p.direction : 0;
    if (GSMarine.BuildWaterDepot(tile, this._GetAdjacentTile(tile, dir))) {
      return { success = true, result = { tile = [p.x, p.y] } };
    }
    return this._Refused();
  }

  function CmdRemoveCanal(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local tile = GSMap.GetTileIndex(p.x, p.y);
    if (GSMarine.RemoveCanal(tile)) return { success = true, result = {} };
    return this._Refused();
  }

  function CmdRemoveLock(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local tile = GSMap.GetTileIndex(p.x, p.y);
    if (GSMarine.RemoveLock(tile)) return { success = true, result = {} };
    return this._Refused();
  }

  function CmdRemoveBuoy(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local tile = GSMap.GetTileIndex(p.x, p.y);
    if (GSMarine.RemoveBuoy(tile)) return { success = true, result = {} };
    return this._Refused();
  }

  function CmdRemoveWaterDepot(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local tile = GSMap.GetTileIndex(p.x, p.y);
    if (GSMarine.RemoveWaterDepot(tile)) return { success = true, result = {} };
    return this._Refused();
  }

  // ===========================================================================
  // BUILDING: OTHER
  // ===========================================================================

  function CmdBuildAirport(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local airport_type = ("airport_type" in p) ? p.airport_type : 0;
    local tile = GSMap.GetTileIndex(p.x, p.y);
    if (GSAirport.BuildAirport(tile, airport_type, GSStation.STATION_NEW)) {
      local sid = GSStation.GetStationID(tile);
      return { success = true, result = { tile = [p.x, p.y], type = airport_type, station_id = sid } };
    }
    return this._Refused();
  }

  function CmdRemoveAirport(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local tile = GSMap.GetTileIndex(p.x, p.y);
    if (GSAirport.RemoveAirport(tile)) return { success = true, result = { tile = [p.x, p.y] } };
    return this._Refused();
  }

  function CmdOpenCloseAirport(p) {
    local company_mode = GSCompanyMode(p.company_id);
    if (GSAirport.OpenCloseAirport(p.station_id)) {
      return { success = true, result = { station_id = p.station_id } };
    }
    return this._Refused();
  }

  function CmdBuildDock(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local tile = GSMap.GetTileIndex(p.x, p.y);
    if (GSMarine.BuildDock(tile, GSStation.STATION_NEW)) {
      local sid = GSStation.GetStationID(tile);
      return { success = true, result = { tile = [p.x, p.y], station_id = sid } };
    }
    return this._Refused({ tile = tile, company = p.company_id });
  }

  function CmdBuildBridge(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local start_tile = GSMap.GetTileIndex(p.start_x, p.start_y);
    local end_tile = GSMap.GetTileIndex(p.end_x, p.end_y);
    local bridge_type = ("bridge_type" in p) ? p.bridge_type : 0;
    local transport = ("transport_type" in p) ? p.transport_type : "road";
    local vt = (transport == "rail") ? GSVehicle.VT_RAIL : (transport == "water") ? GSVehicle.VT_WATER : GSVehicle.VT_ROAD;
    if (GSBridge.BuildBridge(vt, bridge_type, start_tile, end_tile)) {
      return { success = true, result = { start = [p.start_x, p.start_y], end_pos = [p.end_x, p.end_y] } };
    }
    return this._Refused();
  }

  function CmdBuildTunnel(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local tile = GSMap.GetTileIndex(p.x, p.y);
    local transport = ("transport_type" in p) ? p.transport_type : "rail";
    local vt = (transport == "road") ? GSVehicle.VT_ROAD : GSVehicle.VT_RAIL;
    if (GSTunnel.BuildTunnel(vt, tile)) {
      local exit_tile = GSTunnel.GetOtherTunnelEnd(tile);
      return { success = true, result = {
        entrance = [p.x, p.y],
        exit_pos = [GSMap.GetTileX(exit_tile), GSMap.GetTileY(exit_tile)]
      }};
    }
    return this._Refused();
  }

  function CmdBuildPath(p) {
    // Executes a pre-calculated path from the Python A* pathfinder.
    // p.steps = [{x, y, action, ...}, ...] from pathfind() result.
    // p.transport_type = "road" or "rail"
    local company_mode = GSCompanyMode(p.company_id);
    if (!("steps" in p) || p.steps.len() < 2)
      return { success = false, error = "Need steps array with at least 2 entries" };

    local transport = ("transport_type" in p) ? p.transport_type : "road";
    // Named rather than "anything that is not rail is road". That default silently
    // reinterpreted transport_type="water" as a road build, and since a water path
    // carries canal steps this handler had no case for, every one was skipped: the
    // reply was success = true with built = 0. A caller had no way to tell a laid
    // route from nothing at all.
    if (transport != "rail" && transport != "road" && transport != "water") {
      return { success = false, error = "transport_type must be rail, road or water, not '" + transport + "'" };
    }
    local is_rail = (transport == "rail");
    local is_water = (transport == "water");
    local rail_type = ("rail_type" in p) ? p.rail_type : 0;
    local road_type = ("road_type" in p) ? p.road_type : 0;

    if (is_rail) GSRail.SetCurrentRailType(rail_type);
    else if (!is_water) GSRoad.SetCurrentRoadType(road_type);

    local steps = p.steps;
    local built = 0;
    local existing = 0;
    local skipped = 0;
    local failed = [];

    for (local i = 0; i < steps.len(); i++) {
      local step = steps[i];
      local action = ("action" in step) ? step.action : "move";
      local sx = step.x, sy = step.y;

      // Skip start/end markers and plain movement on existing infra
      if (action == "start" || action == "end" || action == "move") {
        skipped++;
        continue;
      }

      // Water is laid per tile: a canal where there is no water, a lock where the
      // ground steps. Most useful ship routes need neither, because open water between
      // two coastal towns is already navigable, and those arrive as "move" steps above.
      if (action == "build_canal" || action == "build_lock") {
        local wt = GSMap.GetTileIndex(sx, sy);
        local ok = (action == "build_canal") ? GSMarine.BuildCanal(wt) : GSMarine.BuildLock(wt);
        if (ok) { built++; }
        else {
          local werr = GSError.GetLastErrorString();
          if (werr == "ERR_ALREADY_BUILT") { existing++; }
          else { failed.append({ x = sx, y = sy, action = action, error = werr, error_code = GSError.GetLastError(), error_category = GSError.GetErrorCategory() }); }
        }
        continue;
      }

      if (action == "build_bridge") {
        local bfx = step.bridge_from_x, bfy = step.bridge_from_y;
        local start_tile = GSMap.GetTileIndex(bfx, bfy);
        local end_tile = GSMap.GetTileIndex(sx, sy);
        local vt = is_rail ? GSVehicle.VT_RAIL : GSVehicle.VT_ROAD;
        // Pick cheapest available bridge type
        local bt = 0;
        if (GSBridge.BuildBridge(vt, bt, start_tile, end_tile)) {
          built++;
        } else {
          local err = GSError.GetLastErrorString();
          if (err != "ERR_ALREADY_BUILT") failed.append({ x = sx, y = sy, action = action, error = err, error_code = GSError.GetLastError(), error_category = GSError.GetErrorCategory() });
          else existing++;
        }
        continue;
      }

      if (action == "build_tunnel") {
        local tfx = step.tunnel_from_x, tfy = step.tunnel_from_y;
        local entrance = GSMap.GetTileIndex(tfx, tfy);
        local vt = is_rail ? GSVehicle.VT_RAIL : GSVehicle.VT_ROAD;
        if (GSTunnel.BuildTunnel(vt, entrance)) {
          built++;
        } else {
          local err = GSError.GetLastErrorString();
          if (err != "ERR_ALREADY_BUILT") failed.append({ x = sx, y = sy, action = action, error = err, error_code = GSError.GetLastError(), error_category = GSError.GetErrorCategory() });
          else existing++;
        }
        continue;
      }

      // build_road or build_rail: connect to previous step
      if (action == "build_road" || action == "build_rail") {
        if (i == 0) { skipped++; continue; }
        local prev_step = steps[i - 1];
        local prev_tile = GSMap.GetTileIndex(prev_step.x, prev_step.y);
        local curr_tile = GSMap.GetTileIndex(sx, sy);

        if (is_rail) {
          // Rail needs 3-tile context: prev, curr, next
          local next_step = (i + 1 < steps.len()) ? steps[i + 1] : null;
          if (next_step == null) { skipped++; continue; }
          local next_tile = GSMap.GetTileIndex(next_step.x, next_step.y);
          if (GSRail.BuildRail(prev_tile, curr_tile, next_tile)) {
            built++;
          } else {
            local err = GSError.GetLastErrorString();
            if (err != "ERR_ALREADY_BUILT") failed.append({ x = sx, y = sy, action = action, error = err, error_code = GSError.GetLastError(), error_category = GSError.GetErrorCategory() });
            else existing++;
          }
        } else {
          // Road: connect prev to curr
          if (GSRoad.BuildRoad(prev_tile, curr_tile)) {
            built++;
          } else {
            local err = GSError.GetLastErrorString();
            if (err != "ERR_ALREADY_BUILT") failed.append({ x = sx, y = sy, action = action, error = err, error_code = GSError.GetLastError(), error_category = GSError.GetErrorCategory() });
            else existing++;
          }
        }
        continue;
      }

      // An action this handler does not know is a FAILURE, not something to pass over.
      // Skipping it quietly is how transport_type="water" came to report success while
      // building nothing: the steps were all canals, none matched a case, and every one
      // fell through to here.
      failed.append({
        x = sx, y = sy, action = action,
        error = "build_path does not know the step action '" + action + "'",
        error_code = null, error_category = "",
      });
    }

    local complete = (failed.len() == 0);
    return { success = complete,
      error = complete ? null : this._PartialError(failed, steps.len()),
      result = {
      status = complete ? "complete" : "partial",
      built = built, existing = existing, failed = failed, skipped = skipped,
      total_steps = steps.len(), errors = failed.len()
    }};
  }

  function CmdDemolishTile(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local tile = GSMap.GetTileIndex(p.x, p.y);
    if (GSTile.DemolishTile(tile)) return { success = true, result = { tile = [p.x, p.y] } };
    return this._Refused();
  }

  // ===========================================================================
  // COMPANY MANAGEMENT
  // ===========================================================================

  function CmdBuildCompanyHQ(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local tile = GSMap.GetTileIndex(p.x, p.y);
    if (GSCompany.BuildCompanyHQ(tile)) return { success = true, result = { tile = [p.x, p.y] } };
    return this._Refused();
  }

  function CmdSetLoan(p) {
    local company_mode = GSCompanyMode(p.company_id);
    if (GSCompany.SetLoanAmount(p.amount)) {
      return { success = true, result = {
        loan = GSCompany.GetLoanAmount(),
        balance = GSCompany.GetBankBalance(p.company_id)
      }};
    }
    return this._Refused();
  }

  function CmdRenameCompany(p) {
    local company_mode = GSCompanyMode(p.company_id);
    if (GSCompany.SetName(p.name)) return { success = true, result = { name = p.name } };
    return this._Refused();
  }

  // ===========================================================================
  // TOWN COMMANDS (GS-exclusive)
  // ===========================================================================

  function CmdFoundTown(p) {
    local tile = GSMap.GetTileIndex(p.x, p.y);
    local size = ("size" in p) ? p.size : GSTown.TOWN_SIZE_SMALL;
    local is_city = ("is_city" in p) ? p.is_city : false;
    local layout = ("road_layout" in p) ? p.road_layout : GSTown.ROAD_LAYOUT_ORIGINAL;
    local name = ("name" in p) ? p.name : null;
    local tid = GSTown.FoundTown(tile, size, is_city, layout, name);
    if (GSTown.IsValidTown(tid)) {
      local loc = GSTown.GetLocation(tid);
      return { success = true, result = {
        town_id = tid, name = GSTown.GetName(tid),
        x = GSMap.GetTileX(loc), y = GSMap.GetTileY(loc)
      }};
    }
    return this._Refused();
  }

  function CmdExpandTown(p) {
    if (!GSTown.IsValidTown(p.town_id)) return { success = false, error = "Invalid town ID" };
    local houses = ("houses" in p) ? p.houses : 5;
    if (GSTown.ExpandTown(p.town_id, houses)) {
      return { success = true, result = {
        town_id = p.town_id,
        population = GSTown.GetPopulation(p.town_id)
      }};
    }
    return this._Refused();
  }

  function CmdSetTownGrowth(p) {
    if (!GSTown.IsValidTown(p.town_id)) return { success = false, error = "Invalid town ID" };
    if (GSTown.SetGrowthRate(p.town_id, p.days)) {
      return { success = true, result = { town_id = p.town_id, growth_rate = p.days } };
    }
    return this._Refused();
  }

  function CmdPerformTownAction(p) {
    if (!GSTown.IsValidTown(p.town_id)) return { success = false, error = "Invalid town ID" };
    if (!GSTown.IsActionAvailable(p.town_id, p.action)) {
      return { success = false, error = "Action not available for this town" };
    }
    if (GSTown.PerformTownAction(p.town_id, p.action)) {
      return { success = true, result = { town_id = p.town_id, action = p.action } };
    }
    return this._Refused();
  }

  function CmdChangeTownRating(p) {
    if (!GSTown.IsValidTown(p.town_id)) return { success = false, error = "Invalid town ID" };
    if (GSTown.ChangeRating(p.town_id, p.company_id, p.delta)) {
      return { success = true, result = {
        town_id = p.town_id, company_id = p.company_id,
        new_rating = GSTown.GetRating(p.town_id, p.company_id)
      }};
    }
    return this._Refused();
  }

  function CmdSetCargoGoal(p) {
    if (!GSTown.IsValidTown(p.town_id)) return { success = false, error = "Invalid town ID" };
    if (GSTown.SetCargoGoal(p.town_id, p.town_effect, p.goal)) {
      return { success = true, result = { town_id = p.town_id, town_effect = p.town_effect, goal = p.goal } };
    }
    return this._Refused();
  }

  // ===========================================================================
  // SUBSIDIES (GS-exclusive)
  // ===========================================================================

  function CmdCreateSubsidy(p) {
    local cargo = p.cargo_type;
    local from_type = p.from_type;
    local from_id = p.from_id;
    local to_type = p.to_type;
    local to_id = p.to_id;
    if (GSSubsidy.Create(cargo, from_type, from_id, to_type, to_id)) {
      return { success = true, result = {} };
    }
    return this._Refused();
  }

  // ===========================================================================
  // SIGNS
  // ===========================================================================

  function CmdBuildSign(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local tile = GSMap.GetTileIndex(p.x, p.y);
    local sid = GSSign.BuildSign(tile, p.name);
    if (GSSign.IsValidSign(sid)) {
      return { success = true, result = { sign_id = sid, name = p.name } };
    }
    return this._Refused();
  }

  function CmdRemoveSign(p) {
    local company_mode = GSCompanyMode(p.company_id);
    if (GSSign.RemoveSign(p.sign_id)) return { success = true, result = {} };
    return this._Refused();
  }

  // ===========================================================================
  // VEHICLE GROUPS
  // ===========================================================================

  function CmdCreateGroup(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local vt = this._VehicleTypeEnum(("vehicle_type" in p) ? p.vehicle_type : "train");
    local parent_gid = ("parent_group_id" in p) ? p.parent_group_id : GSGroup.GROUP_INVALID;
    local gid = GSGroup.CreateGroup(vt, parent_gid);
    if (GSGroup.IsValidGroup(gid)) return { success = true, result = { group_id = gid } };
    return this._Refused();
  }

  function CmdDeleteGroup(p) {
    local company_mode = GSCompanyMode(p.company_id);
    if (GSGroup.DeleteGroup(p.group_id)) return { success = true, result = {} };
    return this._Refused();
  }

  function CmdMoveToGroup(p) {
    local company_mode = GSCompanyMode(p.company_id);
    if (GSGroup.MoveVehicle(p.group_id, p.vehicle_id)) return { success = true, result = {} };
    return this._Refused();
  }

  function CmdSetAutoReplace(p) {
    local company_mode = GSCompanyMode(p.company_id);
    if (GSGroup.SetAutoReplace(p.group_id, p.engine_id_old, p.engine_id_new)) {
      return { success = true, result = {} };
    }
    return this._Refused();
  }

  // ===========================================================================
  // VEHICLE COMMANDS
  // ===========================================================================

  function CmdBuyVehicle(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local depot_tile = ("depot_tile" in p && p.depot_tile != null)
      ? p.depot_tile
      : GSMap.GetTileIndex(p.depot_x, p.depot_y);
    local vid = GSVehicle.BuildVehicle(depot_tile, p.engine_id);
    if (GSVehicle.IsValidVehicle(vid)) {
      return { success = true, result = { vehicle_id = vid, name = GSVehicle.GetName(vid) } };
    }
    return this._Refused({ engine = p.engine_id, depot = depot_tile, company = p.company_id });
  }

  function CmdBuildTrain(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local depot_tile = ("depot_tile" in p && p.depot_tile != null)
      ? p.depot_tile
      : GSMap.GetTileIndex(p.depot_x, p.depot_y);
    local vid = GSVehicle.BuildVehicle(depot_tile, p.engine_id);
    if (!GSVehicle.IsValidVehicle(vid))
      return this._Refused();
    local wagons_attached = 0;
    local wagons_failed = 0;
    if ("wagon_id" in p && p.wagon_id != null) {
      local num = ("num_wagons" in p) ? p.num_wagons : 1;
      for (local i = 0; i < num; i++) {
        local wid = GSVehicle.BuildVehicle(depot_tile, p.wagon_id);
        if (GSVehicle.IsValidVehicle(wid)) {
          if (GSVehicle.MoveWagonChain(wid, 0, vid, -1)) {
            wagons_attached++;
          } else {
            GSVehicle.SellVehicle(wid);
            wagons_failed++;
          }
        } else {
          wagons_failed++;
        }
      }
    }
    local refitted = false;
    if ("cargo_id" in p && p.cargo_id != null) {
      refitted = GSVehicle.RefitVehicle(vid, p.cargo_id) ? true : false;
    }
    return { success = true, result = {
      vehicle_id = vid, name = GSVehicle.GetName(vid),
      wagons_attached = wagons_attached, wagons_failed = wagons_failed,
      refitted = refitted
    }};
  }

  function CmdSellVehicle(p) {
    local company_mode = GSCompanyMode(p.company_id);
    if (GSVehicle.SellVehicle(p.vehicle_id)) return { success = true, result = {} };
    return this._Refused();
  }

  function CmdSellWagon(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local sell_chain = ("sell_chain" in p) ? p.sell_chain : false;
    local ok = sell_chain
      ? GSVehicle.SellWagonChain(p.vehicle_id, p.wagon)
      : GSVehicle.SellWagon(p.vehicle_id, p.wagon);
    if (ok) return { success = true, result = {} };
    return this._Refused();
  }

  function CmdMoveWagon(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local move_chain = ("move_chain" in p) ? p.move_chain : false;
    local ok = move_chain
      ? GSVehicle.MoveWagonChain(p.source_vehicle_id, p.source_wagon, p.dest_vehicle_id, p.dest_wagon)
      : GSVehicle.MoveWagon(p.source_vehicle_id, p.source_wagon, p.dest_vehicle_id, p.dest_wagon);
    if (ok) return { success = true, result = {} };
    return this._Refused();
  }

  function CmdStartVehicle(p) {
    local company_mode = GSCompanyMode(p.company_id);
    if (GSVehicle.StartStopVehicle(p.vehicle_id)) {
      return { success = true, result = { running = !GSVehicle.IsStoppedInDepot(p.vehicle_id) } };
    }
    return this._Refused();
  }

  function CmdStopVehicle(p) {
    local company_mode = GSCompanyMode(p.company_id);
    if (GSVehicle.IsStoppedInDepot(p.vehicle_id)) return { success = true, result = { already_stopped = true } };
    if (GSVehicle.StartStopVehicle(p.vehicle_id)) return { success = true, result = {} };
    return this._Refused();
  }

  function CmdSendToDepot(p) {
    local company_mode = GSCompanyMode(p.company_id);
    if (GSVehicle.SendVehicleToDepot(p.vehicle_id)) return { success = true, result = {} };
    return this._Refused();
  }

  function CmdSendToDepotService(p) {
    local company_mode = GSCompanyMode(p.company_id);
    if (GSVehicle.SendVehicleToDepotForServicing(p.vehicle_id)) return { success = true, result = {} };
    return this._Refused();
  }

  function CmdCloneVehicle(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local depot = GSVehicle.GetLocation(p.vehicle_id);
    local share = ("share_orders" in p) ? p.share_orders : true;
    local cid = GSVehicle.CloneVehicle(depot, p.vehicle_id, share);
    if (GSVehicle.IsValidVehicle(cid)) {
      return { success = true, result = { vehicle_id = cid, name = GSVehicle.GetName(cid) } };
    }
    return this._Refused();
  }

  function CmdRefitVehicle(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local cid = ("cargo_id" in p) ? p.cargo_id : ("cargo_type" in p) ? p.cargo_type : null;
    if (cid == null) return { success = false, error = "Need cargo_id or cargo_type" };
    if (GSVehicle.RefitVehicle(p.vehicle_id, cid)) return { success = true, result = {} };
    return this._Refused();
  }

  function CmdReverseVehicle(p) {
    local company_mode = GSCompanyMode(p.company_id);
    if (GSVehicle.ReverseVehicle(p.vehicle_id)) return { success = true, result = {} };
    return this._Refused();
  }

  function CmdRenameVehicle(p) {
    local company_mode = GSCompanyMode(p.company_id);
    if (GSVehicle.SetName(p.vehicle_id, p.name)) {
      return { success = true, result = { vehicle_id = p.vehicle_id, name = p.name } };
    }
    return this._Refused();
  }

  // ===========================================================================
  // ORDER COMMANDS
  // ===========================================================================

  // Validate that a vehicle type can use a station type.
  // Returns null if OK, or an error string if mismatched.
  function _ValidateVehicleStation(vehicle_id, sid) {
    if (!GSVehicle.IsValidVehicle(vehicle_id)) return null;
    if (!GSStation.IsValidStation(sid)) return null;
    local vt = GSVehicle.GetVehicleType(vehicle_id);
    local ok = false;
    switch (vt) {
      case GSVehicle.VT_ROAD:
        ok = GSStation.HasStationType(sid, GSStation.STATION_BUS_STOP) ||
             GSStation.HasStationType(sid, GSStation.STATION_TRUCK_STOP);
        break;
      case GSVehicle.VT_RAIL:
        ok = GSStation.HasStationType(sid, GSStation.STATION_TRAIN);
        break;
      case GSVehicle.VT_AIR:
        ok = GSStation.HasStationType(sid, GSStation.STATION_AIRPORT);
        break;
      case GSVehicle.VT_WATER:
        ok = GSStation.HasStationType(sid, GSStation.STATION_DOCK);
        break;
    }
    if (!ok) {
      return "ERR_VEHICLE_STATION_MISMATCH: " + this._VehicleTypeName(vt) + " cannot use station " + sid;
    }
    return null;
  }

  // Resolve a station_id to the correct order destination tile.
  // GSOrder.AppendOrder expects the station's reference tile from GetLocation().
  // This works for all station types (bus, train, airport, dock).
  function _ResolveOrderDest(sid) {
    if (!GSStation.IsValidStation(sid)) return null;
    return GSStation.GetLocation(sid);
  }

  // Sanitize order flags for vehicle type compatibility.
  // Non-stop flags (bits 0-1) only affect road/rail behavior but are technically
  // valid in AreOrderFlagsValid for all vehicle types. Clear them for air/water
  // to avoid any potential issues.
  function _SanitizeOrderFlags(vehicle_id, flags) {
    if (typeof flags != "integer") flags = flags.tointeger();
    local vt = GSVehicle.GetVehicleType(vehicle_id);
    if (vt == GSVehicle.VT_AIR || vt == GSVehicle.VT_WATER) {
      flags = flags & ~3;  // Clear non-stop bits for air/water
    }
    return flags;
  }

  function CmdAddOrder(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local flags = ("order_flags" in p) ? p.order_flags : 0;
    flags = _SanitizeOrderFlags(p.vehicle_id, flags);
    // Accept station_id OR destination (tile ID of the station)
    local dest = null;
    if ("station_id" in p) {
      local sid = p.station_id;
      if (GSStation.IsValidStation(sid)) {
        dest = _ResolveOrderDest(sid);
      } else if (GSMap.IsValidTile(sid)) {
        // Agent likely passed a tile instead of station ID -- accept it
        dest = sid;
      }
    } else if ("dest_tile" in p) {
      dest = p.dest_tile;
    } else if ("destination" in p) {
      local d = p.destination.tointeger();
      if (GSMap.IsValidTile(d)) {
        dest = d;
      } else if (GSStation.IsValidStation(d)) {
        // Fallback: treat small numbers as station IDs
        dest = _ResolveOrderDest(d);
      }
    }
    if (dest == null || !GSMap.IsValidTile(dest)) {
      local got = ("station_id" in p) ? "station_id=" + p.station_id :
                  ("dest_tile" in p) ? "dest_tile=" + p.dest_tile :
                  ("destination" in p) ? "destination=" + p.destination : "none";
      return { success = false, error = "Need valid station_id or destination tile (" + got + ")" };
    }
    // Validate vehicle-station type compatibility
    if ("station_id" in p && GSStation.IsValidStation(p.station_id)) {
      local mismatch = _ValidateVehicleStation(p.vehicle_id, p.station_id);
      if (mismatch != null) return { success = false, error = mismatch };
    }
    // Ensure integer types for AppendOrder parameters
    local vid = p.vehicle_id.tointeger();
    local dest_int = dest.tointeger();
    local flags_int = flags.tointeger();
    if (GSOrder.AppendOrder(vid, dest_int, flags_int)) {
      return { success = true, result = { order_count = GSOrder.GetOrderCount(vid) } };
    }
    local err = GSError.GetLastErrorString();
    // Diagnostic info for debugging order failures
    local vt = GSVehicle.IsValidVehicle(vid) ? GSVehicle.GetVehicleType(vid) : -1;
    local vtn = this._VehicleTypeName(vt);
    local diag = err + " (v=" + vid + " dest=" + dest_int + " flags=" + flags_int
      + " vtype=" + vtn
      + " tv=" + typeof p.vehicle_id + "/" + typeof dest + "/" + typeof flags
      + " primary=" + GSVehicle.IsPrimaryVehicle(vid)
      + ")";
    return { success = false, error = diag };
  }

  function CmdInsertOrder(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local flags = ("order_flags" in p) ? p.order_flags : 0;
    flags = _SanitizeOrderFlags(p.vehicle_id, flags);
    local dest = null;
    if ("station_id" in p) {
      local sid = p.station_id;
      if (GSStation.IsValidStation(sid)) {
        dest = _ResolveOrderDest(sid);
      } else if (GSMap.IsValidTile(sid)) {
        dest = sid;
      }
    } else if ("dest_tile" in p) {
      dest = p.dest_tile;
    } else if ("destination" in p) {
      dest = p.destination.tointeger();
    }
    if (dest == null || !GSMap.IsValidTile(dest)) return { success = false, error = "Need valid station_id or destination tile" };
    // Validate vehicle-station type compatibility
    if ("station_id" in p && GSStation.IsValidStation(p.station_id)) {
      local mismatch = _ValidateVehicleStation(p.vehicle_id, p.station_id);
      if (mismatch != null) return { success = false, error = mismatch };
    }
    local idx = ("order_index" in p) ? p.order_index :
                ("order_position" in p) ? p.order_position : 0;
    local vid = p.vehicle_id.tointeger();
    local dest_int = dest.tointeger();
    local flags_int = flags.tointeger();
    if (GSOrder.InsertOrder(vid, idx, dest_int, flags_int)) {
      return { success = true, result = { order_count = GSOrder.GetOrderCount(vid) } };
    }
    local err = GSError.GetLastErrorString();
    local vt = GSVehicle.IsValidVehicle(vid) ? GSVehicle.GetVehicleType(vid) : -1;
    return { success = false, error = err + " (v=" + vid + " dest=" + dest_int + " flags=" + flags_int + " vtype=" + this._VehicleTypeName(vt) + ")" };
  }

  function CmdRemoveOrder(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local idx = ("order_index" in p) ? p.order_index :
                ("order_position" in p) ? p.order_position : null;
    if (idx == null) return { success = false, error = "Need order_index or order_position" };
    if (GSOrder.RemoveOrder(p.vehicle_id, idx)) {
      return { success = true, result = { order_count = GSOrder.GetOrderCount(p.vehicle_id) } };
    }
    return this._Refused();
  }

  function CmdSkipToOrder(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local idx = ("order_index" in p) ? p.order_index :
                ("order_position" in p) ? p.order_position : null;
    if (idx == null) return { success = false, error = "Need order_index or order_position" };
    if (GSOrder.SkipToOrder(p.vehicle_id, idx)) return { success = true, result = {} };
    return this._Refused();
  }

  function CmdMoveOrder(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local from_idx = ("from_index" in p) ? p.from_index :
                     ("from_position" in p) ? p.from_position : null;
    local to_idx = ("to_index" in p) ? p.to_index :
                   ("to_position" in p) ? p.to_position : null;
    if (from_idx == null || to_idx == null) return { success = false, error = "Need from_index/to_index" };
    if (GSOrder.MoveOrder(p.vehicle_id, from_idx, to_idx)) return { success = true, result = {} };
    return this._Refused();
  }

  function CmdSetOrderFlags(p) {
    local company_mode = GSCompanyMode(p.company_id);
    local idx = ("order_index" in p) ? p.order_index :
                ("order_position" in p) ? p.order_position : null;
    if (idx == null) return { success = false, error = "Need order_index or order_position" };
    if (GSOrder.SetOrderFlags(p.vehicle_id, idx, p.order_flags)) return { success = true, result = {} };
    return this._Refused();
  }

  function CmdShareOrders(p) {
    local company_mode = GSCompanyMode(p.company_id);
    if (GSOrder.ShareOrders(p.vehicle_id, p.main_vehicle_id)) return { success = true, result = {} };
    return this._Refused();
  }

  function CmdCopyOrders(p) {
    local company_mode = GSCompanyMode(p.company_id);
    if (GSOrder.CopyOrders(p.vehicle_id, p.main_vehicle_id)) {
      return { success = true, result = { order_count = GSOrder.GetOrderCount(p.vehicle_id) } };
    }
    return this._Refused();
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
        flags = GSOrder.GetOrderFlags(vid, i),
        is_goto_station = GSOrder.IsGotoStationOrder(vid, i),
        is_goto_depot = GSOrder.IsGotoDepotOrder(vid, i),
        is_goto_waypoint = GSOrder.IsGotoWaypointOrder(vid, i),
        is_conditional = GSOrder.IsConditionalOrder(vid, i)
      });
    }
    return { success = true, result = { vehicle_id = vid, order_count = count, orders = orders } };
  }

  // ===========================================================================
  // UTILITY FUNCTIONS
  // ===========================================================================

  // Resolve tile from params: accepts {tile: int} OR {x: int, y: int}.
  // If "tile" is provided, derives x/y. If x/y provided, derives tile.
  // Returns {tile, x, y} or null if invalid.
  function _ResolveTile(p, prefix = "") {
    local tk = prefix + "tile";
    local xk = prefix + "x";
    local yk = prefix + "y";
    if (tk in p && p[tk] != null) {
      local tv = p[tk];
      if (typeof tv != "integer" && typeof tv != "float") return null;
      local t = tv.tointeger();
      if (!GSMap.IsValidTile(t)) return null;
      return { tile = t, x = GSMap.GetTileX(t), y = GSMap.GetTileY(t) };
    }
    if ((xk in p) && (yk in p)) {
      local xv = p[xk];
      local yv = p[yk];
      if (typeof xv != "integer" && typeof xv != "float") return null;
      if (typeof yv != "integer" && typeof yv != "float") return null;
      local t = GSMap.GetTileIndex(xv.tointeger(), yv.tointeger());
      if (!GSMap.IsValidTile(t)) return null;
      return { tile = t, x = xv.tointeger(), y = yv.tointeger() };
    }
    return null;
  }

  // Resolve a pair of tiles for from/to style commands.
  // Accepts {tile_from, tile_to} OR {from_x, from_y, to_x, to_y}.
  function _ResolveTilePair(p) {
    local from_r = this._ResolveTile(p, "from_");
    if (from_r == null) {
      if ("tile_from" in p && p.tile_from != null) {
        local tv = p.tile_from;
        if (typeof tv == "integer" || typeof tv == "float") {
          local t = tv.tointeger();
          if (GSMap.IsValidTile(t)) from_r = { tile = t, x = GSMap.GetTileX(t), y = GSMap.GetTileY(t) };
        }
      }
    }
    local to_r = this._ResolveTile(p, "to_");
    if (to_r == null) {
      if ("tile_to" in p && p.tile_to != null) {
        local tv = p.tile_to;
        if (typeof tv == "integer" || typeof tv == "float") {
          local t = tv.tointeger();
          if (GSMap.IsValidTile(t)) to_r = { tile = t, x = GSMap.GetTileX(t), y = GSMap.GetTileY(t) };
        }
      }
    }
    if (from_r == null || to_r == null) return null;
    return { from = from_r, to = to_r };
  }

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
      local nx = x + o.dx, ny = y + o.dy;
      local t = GSMap.GetTileIndex(nx, ny);
      if (GSMap.IsValidTile(t) && GSRoad.IsRoadTile(t)) results.append({ nx = nx, ny = ny, dir = o.dir });
    }
    return results;
  }

  function _FindAnyAdjacentBuildable(x, y) {
    local offsets = [
      { dx = 1,  dy = 0,  dir = 0 },
      { dx = 0,  dy = 1,  dir = 1 },
      { dx = -1, dy = 0,  dir = 2 },
      { dx = 0,  dy = -1, dir = 3 }
    ];
    foreach (o in offsets) {
      local t = GSMap.GetTileIndex(x + o.dx, y + o.dy);
      if (GSMap.IsValidTile(t) && (GSTile.IsBuildable(t) || GSRoad.IsRoadTile(t))) return o.dir;
    }
    return -1;
  }

  function _GetAdjacentRailTrack(x, y) {
    local offsets = [
      { dx = 1,  dy = 0,  dir = 0 },
      { dx = 0,  dy = 1,  dir = 1 },
      { dx = -1, dy = 0,  dir = 2 },
      { dx = 0,  dy = -1, dir = 3 }
    ];
    local results = [];
    foreach (o in offsets) {
      local nx = x + o.dx, ny = y + o.dy;
      local t = GSMap.GetTileIndex(nx, ny);
      if (GSMap.IsValidTile(t) && GSRail.IsRailTile(t)) results.append({ nx = nx, ny = ny, dir = o.dir });
    }
    return results;
  }

  // ===========================================================================
  // A* PATHFINDING UTILITIES
  // ===========================================================================

  function _HeapCreate() { return []; }

  function _HeapPush(heap, priority, value) {
    heap.append({ p = priority, v = value });
    local i = heap.len() - 1;
    while (i > 0) {
      local pi = (i - 1) / 2;
      if (heap[pi].p <= heap[i].p) break;
      local tmp = heap[i];
      heap[i] = heap[pi];
      heap[pi] = tmp;
      i = pi;
    }
  }

  function _HeapPop(heap) {
    if (heap.len() == 0) return null;
    local result = heap[0];
    local last = heap.pop();
    if (heap.len() == 0) return result;
    heap[0] = last;
    local i = 0;
    while (true) {
      local left = 2 * i + 1;
      local right = 2 * i + 2;
      local smallest = i;
      if (left < heap.len() && heap[left].p < heap[smallest].p) smallest = left;
      if (right < heap.len() && heap[right].p < heap[smallest].p) smallest = right;
      if (smallest == i) break;
      local tmp = heap[i];
      heap[i] = heap[smallest];
      heap[smallest] = tmp;
      i = smallest;
    }
    return result;
  }

  // Encode (x, y, dir) into a single integer key. Supports maps up to 4096x4096.
  function _EncodeState(x, y, dir) {
    return (x << 14) | (y << 2) | dir;
  }

  // Direction offsets: 0=NE(+x), 1=SE(+y), 2=SW(-x), 3=NW(-y)
  function _GetDirDx(dir) {
    if (dir == 0) return 1;
    if (dir == 2) return -1;
    return 0;
  }

  function _GetDirDy(dir) {
    if (dir == 1) return 1;
    if (dir == 3) return -1;
    return 0;
  }

  // Manhattan distance heuristic.
  function _Heuristic(x, y, gx, gy) {
    local dx = x - gx;
    local dy = y - gy;
    if (dx < 0) dx = -dx;
    if (dy < 0) dy = -dy;
    return dx + dy;
  }

  // ===========================================================================
  // GAME SETTINGS (2.2.1-2.2.2)
  // ===========================================================================

  function CmdGetGameSettings(p) {
    // p.keys = ["max_trains", "map_x", ...]: list of setting key names
    if (!("keys" in p) || typeof p.keys != "array")
      return { success = false, error = "params.keys must be an array of setting names" };

    local result = {};
    foreach (key in p.keys) {
      if (GSGameSettings.IsValid(key)) {
        result.rawset(key, GSGameSettings.GetValue(key));
      } else {
        result.rawset(key, null);
      }
    }
    return { success = true, result = result };
  }

  function CmdSetGameSetting(p) {
    // p.key, p.value: deity-only setting change
    if (!("key" in p) || !("value" in p))
      return { success = false, error = "params.key and params.value required" };

    if (!GSGameSettings.IsValid(p.key))
      return { success = false, error = "Invalid setting: " + p.key };

    local ok = GSGameSettings.SetValue(p.key, p.value);
    if (!ok) return this._Refused();
    return { success = true, result = { key = p.key, value = p.value } };
  }

  // ===========================================================================
  // FINANCIAL QUERIES (2.2.3-2.2.6)
  // ===========================================================================

  function CmdGetExpenseBreakdown(p) {
    if (!("company_id" in p)) return { success = false, error = "params.company_id required" };
    if (GSCompany.ResolveCompanyID(p.company_id) == GSCompany.COMPANY_INVALID)
      return { success = false, error = "Invalid company ID" };

    local cid = p.company_id;

    // GS API only exposes aggregate quarterly totals, not per-category breakdowns.
    // Per-transport finances can be derived from vehicle profits (get_vehicles)
    // and infrastructure maintenance costs (get_infrastructure_costs).
    local quarterly = [];
    for (local q = 0; q < 4; q++) {
      quarterly.append({
        quarter = q,
        income = GSCompany.GetQuarterlyIncome(cid, q),
        expenses = GSCompany.GetQuarterlyExpenses(cid, q),
        cargo_delivered = GSCompany.GetQuarterlyCargoDelivered(cid, q),
        performance_rating = GSCompany.GetQuarterlyPerformanceRating(cid, q),
        company_value = GSCompany.GetQuarterlyCompanyValue(cid, q),
      });
    }

    return { success = true, result = {
      company_id = cid,
      balance = GSCompany.GetBankBalance(cid),
      quarterly = quarterly,
    }};
  }

  function CmdGetInfrastructureCosts(p) {
    if (!("company_id" in p)) return { success = false, error = "params.company_id required" };
    if (GSCompany.ResolveCompanyID(p.company_id) == GSCompany.COMPANY_INVALID)
      return { success = false, error = "Invalid company ID" };

    local cid = p.company_id;
    // Use generic GetInfrastructurePieceCount / GetMonthlyInfrastructureCosts
    // with enum constants. These return totals across all rail/road subtypes.
    return { success = true, result = {
      company_id     = cid,
      rail_pieces    = GSInfrastructure.GetInfrastructurePieceCount(cid, GSInfrastructure.INFRASTRUCTURE_RAIL),
      road_pieces    = GSInfrastructure.GetInfrastructurePieceCount(cid, GSInfrastructure.INFRASTRUCTURE_ROAD),
      water_pieces   = GSInfrastructure.GetInfrastructurePieceCount(cid, GSInfrastructure.INFRASTRUCTURE_CANAL),
      station_pieces = GSInfrastructure.GetInfrastructurePieceCount(cid, GSInfrastructure.INFRASTRUCTURE_STATION),
      airport_pieces = GSInfrastructure.GetInfrastructurePieceCount(cid, GSInfrastructure.INFRASTRUCTURE_AIRPORT),
      rail_cost      = GSInfrastructure.GetMonthlyInfrastructureCosts(cid, GSInfrastructure.INFRASTRUCTURE_RAIL),
      road_cost      = GSInfrastructure.GetMonthlyInfrastructureCosts(cid, GSInfrastructure.INFRASTRUCTURE_ROAD),
      water_cost     = GSInfrastructure.GetMonthlyInfrastructureCosts(cid, GSInfrastructure.INFRASTRUCTURE_CANAL),
      station_cost   = GSInfrastructure.GetMonthlyInfrastructureCosts(cid, GSInfrastructure.INFRASTRUCTURE_STATION),
      airport_cost   = GSInfrastructure.GetMonthlyInfrastructureCosts(cid, GSInfrastructure.INFRASTRUCTURE_AIRPORT),
    }};
  }

  function CmdGetCargoFlows(p) {
    if (!("company_id" in p)) return { success = false, error = "params.company_id required" };
    local cid = p.company_id;
    local keep = ("keep_monitoring" in p) ? p.keep_monitoring : true;
    local flows = [];

    // Iterate over all cargo types
    foreach (cargo_id, _ in GSCargoList()) {
      local lbl = GSCargo.GetCargoLabel(cargo_id);
      // Town deliveries and pickups
      foreach (town_id, _ in GSTownList()) {
        local del_amt = GSCargoMonitor.GetTownDeliveryAmount(cid, cargo_id, town_id, keep);
        if (del_amt > 0) {
          flows.append({
            cargo_id = cargo_id, cargo_label = lbl,
            entity_type = "town", entity_id = town_id,
            entity_name = GSTown.GetName(town_id),
            direction = "delivery", amount = del_amt
          });
        }
        local pick_amt = GSCargoMonitor.GetTownPickupAmount(cid, cargo_id, town_id, keep);
        if (pick_amt > 0) {
          flows.append({
            cargo_id = cargo_id, cargo_label = lbl,
            entity_type = "town", entity_id = town_id,
            entity_name = GSTown.GetName(town_id),
            direction = "pickup", amount = pick_amt
          });
        }
      }
      // Industry deliveries and pickups
      foreach (ind_id, _ in GSIndustryList()) {
        local del_amt = GSCargoMonitor.GetIndustryDeliveryAmount(cid, cargo_id, ind_id, keep);
        if (del_amt > 0) {
          flows.append({
            cargo_id = cargo_id, cargo_label = lbl,
            entity_type = "industry", entity_id = ind_id,
            entity_name = GSIndustry.GetName(ind_id),
            direction = "delivery", amount = del_amt
          });
        }
        local pick_amt = GSCargoMonitor.GetIndustryPickupAmount(cid, cargo_id, ind_id, keep);
        if (pick_amt > 0) {
          flows.append({
            cargo_id = cargo_id, cargo_label = lbl,
            entity_type = "industry", entity_id = ind_id,
            entity_name = GSIndustry.GetName(ind_id),
            direction = "pickup", amount = pick_amt
          });
        }
      }
    }

    return { success = true, result = flows };
  }

  function CmdEstimateCost(p) {
    // Dry-run cost estimation using GSTestMode + GSAccounting
    // p.action = the action to estimate, p.params = action params
    if (!("action" in p) || !("params" in p))
      return { success = false, error = "params.action and params.params required" };

    if ("company_id" in p.params) {
      local cid = p.params.company_id;
      if (GSCompany.ResolveCompanyID(cid) == GSCompany.COMPANY_INVALID)
        return { success = false, error = "Invalid company ID" };

      local cost = 0;
      {
        local mode = GSCompanyMode(cid);
        local accounting = GSAccounting();
        {
          local test = GSTestMode();
          // Dispatch the action in test mode
          local result = this._Dispatch({ action = p.action, params = p.params });
          if (!result.success)
            return { success = false, error = "Test-mode execution failed: " + (("error" in result) ? result.error : "unknown") };
        }
        cost = accounting.GetCosts();
      }
      return { success = true, result = { action = p.action, estimated_cost = cost } };
    }

    return { success = false, error = "params.params.company_id required for cost estimation" };
  }

  // ===========================================================================
  // CLIENTS (2.2.7)
  // ===========================================================================

  function CmdGetClients() {
    local clients = [];
    foreach (client_id, _ in GSClientList()) {
      clients.append({
        client_id = client_id,
        name = GSClient.GetName(client_id),
        company_id = GSClient.GetCompany(client_id),
      });
    }
    return { success = true, result = clients };
  }

  // ===========================================================================
  // DEITY FINANCE (2.2.8-2.2.9)
  // ===========================================================================

  function CmdChangeBankBalance(p) {
    if (!("company_id" in p) || !("delta" in p))
      return { success = false, error = "params.company_id and params.delta required" };
    if (GSCompany.ResolveCompanyID(p.company_id) == GSCompany.COMPANY_INVALID)
      return { success = false, error = "Invalid company ID" };

    local expense_type = ("expense_type" in p) ? p.expense_type : GSCompany.EXPENSES_OTHER;
    local ok = GSCompany.ChangeBankBalance(p.company_id, p.delta, expense_type);
    if (!ok) return this._Refused();
    return { success = true, result = {
      company_id = p.company_id,
      new_balance = GSCompany.GetBankBalance(p.company_id),
    }};
  }

  function CmdSetMaxLoan(p) {
    if (!("company_id" in p) || !("amount" in p))
      return { success = false, error = "params.company_id and params.amount required" };
    if (GSCompany.ResolveCompanyID(p.company_id) == GSCompany.COMPANY_INVALID)
      return { success = false, error = "Invalid company ID" };

    local ok = GSCompany.SetMaxLoanAmountForCompany(p.company_id, p.amount);
    if (!ok) return this._Refused();
    return { success = true, result = { company_id = p.company_id, max_loan = p.amount } };
  }

  // ===========================================================================
  // TERRAFORM (2.2.11)
  // ===========================================================================

  function CmdRaiseTile(p) {
    if (!("x" in p) || !("y" in p) || !("slope" in p))
      return { success = false, error = "params.x, params.y, params.slope required" };
    local tile = GSMap.GetTileIndex(p.x, p.y);
    if (!GSMap.IsValidTile(tile)) return { success = false, error = "Invalid tile" };

    if ("company_id" in p) {
      local ok = false;
      { local mode = GSCompanyMode(p.company_id); ok = GSTile.RaiseTile(tile, p.slope); }
      if (!ok) return this._Refused();
    } else {
      if (!GSTile.RaiseTile(tile, p.slope))
        return this._Refused();
    }
    return { success = true, result = { x = p.x, y = p.y } };
  }

  function CmdLowerTile(p) {
    if (!("x" in p) || !("y" in p) || !("slope" in p))
      return { success = false, error = "params.x, params.y, params.slope required" };
    local tile = GSMap.GetTileIndex(p.x, p.y);
    if (!GSMap.IsValidTile(tile)) return { success = false, error = "Invalid tile" };

    if ("company_id" in p) {
      local ok = false;
      { local mode = GSCompanyMode(p.company_id); ok = GSTile.LowerTile(tile, p.slope); }
      if (!ok) return this._Refused();
    } else {
      if (!GSTile.LowerTile(tile, p.slope))
        return this._Refused();
    }
    return { success = true, result = { x = p.x, y = p.y } };
  }

  function CmdLevelTiles(p) {
    if (!("x1" in p) || !("y1" in p) || !("x2" in p) || !("y2" in p))
      return { success = false, error = "params.x1, y1, x2, y2 required" };
    local tile_from = GSMap.GetTileIndex(p.x1, p.y1);
    local tile_to = GSMap.GetTileIndex(p.x2, p.y2);
    if (!GSMap.IsValidTile(tile_from) || !GSMap.IsValidTile(tile_to))
      return { success = false, error = "Invalid tile range" };

    if ("company_id" in p) {
      local ok = false;
      { local mode = GSCompanyMode(p.company_id); ok = GSTile.LevelTiles(tile_from, tile_to); }
      if (!ok) return this._Refused();
    } else {
      if (!GSTile.LevelTiles(tile_from, tile_to))
        return this._Refused();
    }
    return { success = true, result = { x1 = p.x1, y1 = p.y1, x2 = p.x2, y2 = p.y2 } };
  }

  // ===========================================================================
  // TREES (2.2.12)
  // ===========================================================================

  function CmdPlantTree(p) {
    if (!("x" in p) || !("y" in p))
      return { success = false, error = "params.x and params.y required" };
    local tile = GSMap.GetTileIndex(p.x, p.y);
    if (!GSMap.IsValidTile(tile)) return { success = false, error = "Invalid tile" };

    if (!GSTile.PlantTree(tile))
      return this._Refused();
    return { success = true, result = { x = p.x, y = p.y } };
  }

  function CmdPlantTreeRectangle(p) {
    if (!("x" in p) || !("y" in p) || !("width" in p) || !("height" in p))
      return { success = false, error = "params.x, y, width, height required" };
    local tile = GSMap.GetTileIndex(p.x, p.y);
    if (!GSMap.IsValidTile(tile)) return { success = false, error = "Invalid tile" };

    if (!GSTile.PlantTreeRectangle(tile, p.width, p.height))
      return this._Refused();
    return { success = true, result = { x = p.x, y = p.y, width = p.width, height = p.height } };
  }

  // ===========================================================================
  // ROAD ADVANCED (2.2.13-2.2.14)
  // ===========================================================================

  function CmdBuildOneWayRoad(p) {
    if (!("x1" in p) || !("y1" in p) || !("x2" in p) || !("y2" in p))
      return { success = false, error = "params.x1, y1, x2, y2 required" };
    local from = GSMap.GetTileIndex(p.x1, p.y1);
    local to = GSMap.GetTileIndex(p.x2, p.y2);

    if ("company_id" in p) {
      local ok = false;
      { local mode = GSCompanyMode(p.company_id); ok = GSRoad.BuildOneWayRoad(from, to); }
      if (!ok) return this._Refused();
    } else {
      if (!GSRoad.BuildOneWayRoad(from, to))
        return this._Refused();
    }
    return { success = true, result = { from = { x = p.x1, y = p.y1 }, to = { x = p.x2, y = p.y2 } } };
  }

  function CmdBuildOneWayRoadFull(p) {
    if (!("x1" in p) || !("y1" in p) || !("x2" in p) || !("y2" in p))
      return { success = false, error = "params.x1, y1, x2, y2 required" };
    local from = GSMap.GetTileIndex(p.x1, p.y1);
    local to = GSMap.GetTileIndex(p.x2, p.y2);

    if ("company_id" in p) {
      local ok = false;
      { local mode = GSCompanyMode(p.company_id); ok = GSRoad.BuildOneWayRoadFull(from, to); }
      if (!ok) return this._Refused();
    } else {
      if (!GSRoad.BuildOneWayRoadFull(from, to))
        return this._Refused();
    }
    return { success = true, result = { from = { x = p.x1, y = p.y1 }, to = { x = p.x2, y = p.y2 } } };
  }

  function CmdConvertRoadType(p) {
    if (!("x1" in p) || !("y1" in p) || !("x2" in p) || !("y2" in p) || !("road_type" in p))
      return { success = false, error = "params.x1, y1, x2, y2, road_type required" };
    local from = GSMap.GetTileIndex(p.x1, p.y1);
    local to = GSMap.GetTileIndex(p.x2, p.y2);

    if ("company_id" in p) {
      local ok = false;
      { local mode = GSCompanyMode(p.company_id); ok = GSRoad.ConvertRoadType(from, to, p.road_type); }
      if (!ok) return this._Refused();
    } else {
      if (!GSRoad.ConvertRoadType(from, to, p.road_type))
        return this._Refused();
    }
    return { success = true, result = { road_type = p.road_type } };
  }

  // ===========================================================================
  // CONDITIONAL ORDERS (2.2.10) & STOP LOCATION (2.2.15)
  // ===========================================================================

  function CmdSetOrderCondition(p) {
    if (!("vehicle_id" in p) || !("order_pos" in p) || !("condition" in p))
      return { success = false, error = "params.vehicle_id, order_pos, condition required" };

    if ("company_id" in p) {
      local ok = false;
      { local mode = GSCompanyMode(p.company_id);
        ok = GSOrder.SetOrderCondition(p.vehicle_id, p.order_pos, p.condition); }
      if (!ok) return this._Refused();
    } else {
      if (!GSOrder.SetOrderCondition(p.vehicle_id, p.order_pos, p.condition))
        return this._Refused();
    }
    return { success = true, result = { vehicle_id = p.vehicle_id, order_pos = p.order_pos } };
  }

  function CmdSetOrderCompareFunction(p) {
    if (!("vehicle_id" in p) || !("order_pos" in p) || !("compare_function" in p))
      return { success = false, error = "params.vehicle_id, order_pos, compare_function required" };

    if ("company_id" in p) {
      local ok = false;
      { local mode = GSCompanyMode(p.company_id);
        ok = GSOrder.SetOrderCompareFunction(p.vehicle_id, p.order_pos, p.compare_function); }
      if (!ok) return this._Refused();
    } else {
      if (!GSOrder.SetOrderCompareFunction(p.vehicle_id, p.order_pos, p.compare_function))
        return this._Refused();
    }
    return { success = true, result = { vehicle_id = p.vehicle_id, order_pos = p.order_pos } };
  }

  function CmdSetOrderCompareValue(p) {
    if (!("vehicle_id" in p) || !("order_pos" in p) || !("value" in p))
      return { success = false, error = "params.vehicle_id, order_pos, value required" };

    if ("company_id" in p) {
      local ok = false;
      { local mode = GSCompanyMode(p.company_id);
        ok = GSOrder.SetOrderCompareValue(p.vehicle_id, p.order_pos, p.value); }
      if (!ok) return this._Refused();
    } else {
      if (!GSOrder.SetOrderCompareValue(p.vehicle_id, p.order_pos, p.value))
        return this._Refused();
    }
    return { success = true, result = { vehicle_id = p.vehicle_id, order_pos = p.order_pos } };
  }

  function CmdSetStopLocation(p) {
    if (!("vehicle_id" in p) || !("order_pos" in p) || !("stop_location" in p))
      return { success = false, error = "params.vehicle_id, order_pos, stop_location required" };

    if ("company_id" in p) {
      local ok = false;
      { local mode = GSCompanyMode(p.company_id);
        ok = GSOrder.SetStopLocation(p.vehicle_id, p.order_pos, p.stop_location); }
      if (!ok) return this._Refused();
    } else {
      if (!GSOrder.SetStopLocation(p.vehicle_id, p.order_pos, p.stop_location))
        return this._Refused();
    }
    return { success = true, result = { vehicle_id = p.vehicle_id, order_pos = p.order_pos } };
  }

  // ===========================================================================
  // ENGINE DETAILS (2.2.16)
  // ===========================================================================

  function CmdGetEngineDetails(p) {
    if (!("engine_id" in p))
      return { success = false, error = "params.engine_id required" };
    local eid = p.engine_id;
    if (!GSEngine.IsValidEngine(eid))
      return { success = false, error = "Invalid engine ID" };

    return { success = true, result = {
      engine_id = eid,
      name = GSEngine.GetName(eid),
      vehicle_type = this._VehicleTypeName(GSEngine.GetVehicleType(eid)),
      cargo_type = GSEngine.GetCargoType(eid),
      capacity = GSEngine.GetCapacity(eid),
      max_speed = GSEngine.GetMaxSpeed(eid),
      running_cost = GSEngine.GetRunningCost(eid),
      price = GSEngine.GetPrice(eid),
      max_age = GSEngine.GetMaxAge(eid),
      reliability = GSEngine.GetReliability(eid),
      power = GSEngine.GetPower(eid),
      weight = GSEngine.GetWeight(eid),
      max_tractive_effort = GSEngine.GetMaxTractiveEffort(eid),
      rail_type = GSEngine.GetRailType(eid),
      road_type = GSEngine.GetRoadType(eid),
      can_refit = GSEngine.CanRefitCargo(eid, GSEngine.GetCargoType(eid)),
    }};
  }

  // ===========================================================================
  // TILE AREA (2.4.6): batch tile scan for pathfinding cache
  // ===========================================================================

  function CmdGetTileArea(p) {
    if (!("x1" in p) || !("y1" in p) || !("x2" in p) || !("y2" in p))
      return { success = false, error = "params.x1, y1, x2, y2 required" };

    // INCLUSIVE bounds. They were exclusive, while the parameters are described as two
    // corners, so a request for a single tile returned an empty list and a three by three
    // area returned four tiles. Every caller reading a rectangle silently missed its last
    // row and column, and an empty answer looks like a tile that does not exist rather
    // than like a bounds convention.
    local x1 = p.x1, y1 = p.y1, x2 = p.x2, y2 = p.y2;
    if (x2 < x1) { local t = x1; x1 = x2; x2 = t; }
    if (y2 < y1) { local t = y1; y1 = y2; y2 = t; }
    local max_tiles = ("max_tiles" in p) ? p.max_tiles : 400;

    if ((x2 - x1 + 1) * (y2 - y1 + 1) > max_tiles)
      return { success = false, error = "Area too large (max " + max_tiles + " tiles)" };

    local tiles = [];
    for (local x = x1; x <= x2; x++) {
      for (local y = y1; y <= y2; y++) {
        local tile = GSMap.GetTileIndex(x, y);
        if (!GSMap.IsValidTile(tile)) continue;

        tiles.append({
          x = x, y = y,
          height = GSTile.GetMaxHeight(tile),
          slope = GSTile.GetSlope(tile),
          buildable = GSTile.IsBuildable(tile),
          water = GSTile.IsWaterTile(tile),
          coast = GSTile.IsCoastTile(tile),
          has_road = GSRoad.IsRoadTile(tile),
          has_rail = GSRail.IsRailTile(tile),
          owner = GSTile.GetOwner(tile),
          is_station = GSStation.GetStationID(tile) != GSStation.STATION_INVALID,
          has_tree = GSTile.HasTreeOnTile(tile),
          is_bridge = GSBridge.IsBridgeTile(tile),
          is_tunnel = GSTunnel.IsTunnelTile(tile),
        });
      }
    }
    return { success = true, result = tiles };
  }

  // ===========================================================================
  // INTERNAL HELPERS
  // ===========================================================================

  // Station spots, reachable ones first and nearest within that.
  //
  // Sorting on distance alone put an unusable spot at the head of the list, and the head of
  // the list is what a caller takes. A station a train cannot enter is worse at any
  // distance than one it can, so reachability outranks it rather than tie breaking it.
  function _SortStationSpots(arr) {
    for (local i = 1; i < arr.len(); i++) {
      local key = arr[i];
      local key_blocked = (key.reachable_directions.len() == 0) ? 1 : 0;
      local j = i - 1;
      while (j >= 0) {
        local other_blocked = (arr[j].reachable_directions.len() == 0) ? 1 : 0;
        local worse = (other_blocked > key_blocked)
          || (other_blocked == key_blocked && arr[j].distance > key.distance);
        if (!worse) break;
        arr[j + 1] = arr[j];
        j--;
      }
      arr[j + 1] = key;
    }
  }

  function _SortByDistance(arr) {
    for (local i = 1; i < arr.len(); i++) {
      local key = arr[i];
      local j = i - 1;
      while (j >= 0 && arr[j].distance > key.distance) { arr[j + 1] = arr[j]; j--; }
      arr[j + 1] = key;
    }
  }

  // Check cargo acceptance and production around a tile area.
  // Returns array of {cargo_id, cargo_label, acceptance, production} for cargos with acceptance >= 8 or production > 0.
  // width/height/radius define the area to check (1,1,3 = single tile with 3-tile radius).
  function _GetTileCargoInfo(tile, width, height, radius) {
    local result = [];
    foreach (cargo_id, _ in GSCargoList()) {
      local acc = GSTile.GetCargoAcceptance(tile, cargo_id, width, height, radius);
      local prod = GSTile.GetCargoProduction(tile, cargo_id, width, height, radius);
      if (acc >= 8 || prod > 0) {
        result.append({
          cargo_id = cargo_id,
          cargo_label = GSCargo.GetCargoLabel(cargo_id),
          acceptance = acc,
          production = prod
        });
      }
    }
    return result;
  }

  function _GetTotalCapacity(vid) {
    local total = 0;
    foreach (cargo_id, _ in GSCargoList()) {
      total += GSVehicle.GetCapacity(vid, cargo_id);
    }
    return total;
  }

  function _VehicleTypeName(vt) {
    switch (vt) {
      case GSVehicle.VT_RAIL:  return "train";
      case GSVehicle.VT_ROAD:  return "road";
      case GSVehicle.VT_WATER: return "ship";
      case GSVehicle.VT_AIR:   return "aircraft";
    }
    return "unknown";
  }

  function _VehicleTypeEnum(type_str) {
    // Accept both string names and integer IDs
    switch (type_str) {
      case "train":    case 0: return GSVehicle.VT_RAIL;
      case "road":     case 1: return GSVehicle.VT_ROAD;
      case "ship":     case 2: return GSVehicle.VT_WATER;
      case "aircraft": case 3: return GSVehicle.VT_AIR;
    }
    return GSVehicle.VT_RAIL;
  }
}
