# OpenTTD Comprehensive Study - Part 2: GameScript API Reference

> This is Part 2 of 3. See also:
> - [Part 1: Game Mechanics](./openttd_study_part1_game_mechanics.md)
> - [Part 3: nttd Implementation Analysis & API Design](./openttd_study_part3_nttd_analysis.md)

---

## 1. GameScript Architecture

### 1.1 Language: Squirrel

OpenTTD scripts use **Squirrel**, a C++-like language with:
- Dynamic typing
- Classes and inheritance
- Tables (dictionaries), arrays
- First-class functions
- No built-in async/threading

### 1.2 Script Structure

```
info.nut   — Metadata (name, author, version)
main.nut   — Main class extending GSController
```

The main class must implement:
- `Start()` — Entry point; runs in a loop; exiting kills the script
- `Save()` — Return table of data to persist (called during saves)
- `Load(version, data)` — Restore saved data (called before Start)

### 1.3 Execution Model

- **Single-threaded**: GS runs in the game loop, one tick at a time
- **Opcode budget**: Limited operations per tick; suspension when exceeded
- **Sleep**: `GSController.Sleep(ticks)` — voluntarily yield for N ticks
- **Command delay**: `GSController.SetCommandDelay(ticks)` — min ticks between commands

### 1.4 AI Scripts vs GameScript

| Feature | AI Script | GameScript (GS) |
|---------|-----------|-----------------|
| Count | One per company | One per game (server-wide) |
| Scope | Own company only | All companies (deity mode) |
| Company switching | N/A | `GSCompanyMode(company_id)` |
| Town manipulation | No | Yes (found, expand, rate) |
| Industry control | No | Yes (production, exclusives) |
| Game settings | No | Yes (read/write) |
| Subsidy creation | No | Yes |
| Goals/News/Stories | No | Yes |
| API prefix | `AI*` classes | `GS*` classes |

### 1.5 Execution Modes

| Mode | Class | Behavior |
|------|-------|----------|
| **Execute** | `GSExecMode()` | Commands execute and modify game state (default) |
| **Test** | `GSTestMode()` | Commands validate + calculate cost without executing |
| **Async** | `GSAsyncMode(true)` | Commands queued for later execution; preliminary feedback |

All modes use RAII pattern — create instance to enter mode, destroy to restore previous mode.

### 1.6 Company Mode

`GSCompanyMode(company_id)` — Switch context to act as a specific company.

- All subsequent build/remove/vehicle commands execute as that company
- Financial costs charged to that company
- Reverts on destruction (RAII)
- `GSCompanyMode.IsValid()` — true if in company mode
- `GSCompanyMode.IsDeity()` — true if in deity mode (no company context)

**Critical**: Many GS-exclusive actions (town/industry control) require **deity mode** (no active GSCompanyMode).

---

## 2. Complete API Class Inventory (191 Classes)

### 2.1 Core Entity Classes

| Class | Purpose | Methods |
|-------|---------|---------|
| GSVehicle | Vehicle queries and actions | 44 |
| GSOrder | Order management | 30+ |
| GSRail | Rail infrastructure | 30+ |
| GSRoad | Road infrastructure | 30+ |
| GSMarine | Water infrastructure | 16 |
| GSAirport | Airport management | 17 |
| GSBridge | Bridge management | 11 |
| GSTunnel | Tunnel management | 4 |
| GSTile | Tile queries and modification | 30+ |
| GSTown | Town queries and GS-exclusive actions | 34 |
| GSIndustry | Industry queries and GS control | 30 |
| GSCompany | Company finances and management | 35+ |
| GSStation | Station queries | 22+ |
| GSBaseStation | Base station properties | 6 |
| GSEngine | Engine/vehicle type info | 25+ |
| GSGroup | Vehicle group management | 25+ |
| GSMap | Map dimensions and distance | 11 |
| GSDate | Game time queries | 7 |
| GSCargo | Cargo type info | 10 |
| GSSign | Map sign management | 7 |
| GSSubsidy | Subsidy management | 10 |
| GSWaypoint | Waypoint queries | 3 + inherited |
| GSIndustryType | Industry type metadata | varies |

### 2.2 Control & Communication Classes

| Class | Purpose |
|-------|---------|
| GSController | Script lifecycle (Start, Save, Load, Sleep, GetTick) |
| GSCompanyMode | Switch company context |
| GSExecMode | Execute mode (commands run) |
| GSTestMode | Test mode (validate + cost only) |
| GSAsyncMode | Async mode (queue commands) |
| GSAdmin | Send JSON to admin port |
| GSEvent | Receive events from game |
| GSGameSettings | Read/write game settings |
| GSAccounting | Track command costs |
| GSError | Query last error |
| GSLog | Debug logging (Info/Warning/Error) |

### 2.3 UI & Narrative Classes (GS-Exclusive)

| Class | Purpose |
|-------|---------|
| GSGoal | Define/track game goals |
| GSNews | Create news messages |
| GSStoryPage | Create narrative story pages |
| GSLeagueTable | Create custom league tables |
| GSViewport | Scroll player viewports |
| GSWindow | Window interaction (limited) |

### 2.4 List/Iterator Classes

| Class | Contents | Use |
|-------|----------|-----|
| GSTownList | All towns | Iterate + valuate |
| GSIndustryList | All industries | Iterate + valuate |
| GSIndustryList_CargoAccepting | Industries accepting cargo X | Filter by cargo |
| GSIndustryList_CargoProducing | Industries producing cargo X | Filter by cargo |
| GSStationList | All stations (company-scoped) | Iterate + valuate |
| GSStationList_Vehicle | Stations visited by vehicle | Vehicle route analysis |
| GSStationList_Cargo* | 10+ variants | Cargo waiting/planned by from/via |
| GSVehicleList | All vehicles (company-scoped) | Iterate + valuate |
| GSVehicleList_Station | Vehicles visiting station | Station usage |
| GSVehicleList_Group | Vehicles in group | Group management |
| GSVehicleList_Depot | Vehicles in depot | Depot contents |
| GSVehicleList_SharedOrders | Vehicles sharing orders | Route analysis |
| GSVehicleList_DefaultGroup | Ungrouped vehicles | Cleanup |
| GSEngineList | Available engines by type | Vehicle purchasing |
| GSCargoList | All cargo types | Game setup |
| GSCargoList_IndustryAccepting | Cargo accepted by industry | Route planning |
| GSCargoList_IndustryProducing | Cargo produced by industry | Route planning |
| GSCargoList_StationAccepting | Cargo accepted by station | Station analysis |
| GSSignList | All signs | Sign management |
| GSSubsidyList | All subsidies | Opportunity finding |
| GSDepotList | All depots by type | Depot finding |
| GSGroupList | All groups (company-scoped) | Group management |
| GSWaypointList | All waypoints | Navigation |
| GSWaypointList_Vehicle | Waypoints visited by vehicle | Route analysis |
| GSBridgeList | All bridge types | Bridge selection |
| GSBridgeList_Length | Bridge types for length | Bridge selection |
| GSRailTypeList | All rail types | Tech level check |
| GSRoadTypeList | All road types | Tech level check |
| GSTileList | Custom tile collection | Map analysis |
| GSTileList_IndustryAccepting | Tiles in industry acceptance area | Station placement |
| GSTileList_IndustryProducing | Tiles in industry production area | Station placement |
| GSTileList_StationCoverage | Tiles in station coverage | Coverage analysis |
| GSNewGRFList | Loaded NewGRFs | Compatibility |
| GSObjectTypeList | Map object types | Object queries |

**All lists support**: `Valuate(function)`, `Sort(type, ascending)`, `KeepAboveValue/BelowValue/BetweenValue()`, `RemoveAboveValue/BelowValue()`, `KeepTop/Bottom(count)`, `Count()`, `IsEmpty()`, `Begin/Next/IsEnd()`, `HasItem()`, `GetValue()`.

### 2.5 Event Classes

| Class | Contents |
|-------|----------|
| GSEvent | Base event class |
| GSEventAdminPort | Data from admin port |
| GSEventCompanyNew | New company created |
| GSEventCompanyInTrouble | Company in financial trouble |
| GSEventCompanyMerger | Company merger |
| GSEventCompanyBankrupt | Company bankrupt |
| GSEventCompanyRenamed | Company renamed |
| GSEventCompanyTown | Company-town interaction |
| GSEventPresidentRenamed | President renamed |
| GSEventVehicleCrashed | Vehicle crash |
| GSEventIndustryOpen | New industry spawned |
| GSEventIndustryClose | Industry closing |
| GSEventSubsidyOffer | New subsidy offered |
| GSEventSubsidyOfferExpired | Subsidy offer expired |
| GSEventSubsidyAwarded | Subsidy claimed |
| GSEventSubsidyExpired | Active subsidy expired |
| GSEventStationFirstVehicle | First vehicle visits station |
| GSEventTownFounded | New town founded |
| GSEventExclusiveTransportRights | Exclusive rights granted |
| GSEventRoadReconstruction | Town road reconstruction |
| GSEventGoalQuestionAnswer | Player answered goal question |
| GSEventStoryPageButtonClick | Story page button clicked |
| GSEventStoryPageTileSelect | Story page tile selected |
| GSEventStoryPageVehicleSelect | Story page vehicle selected |
| GSEventWindowWidgetClick | Window widget clicked |

### 2.6 Miscellaneous

| Class | Purpose |
|-------|---------|
| GSBase | Random number generation |
| GSClient | Multiplayer client info |
| GSClientList | All connected clients |
| GSClientList_Company | Clients in a company |
| GSGame | Game mode queries |
| GSInfo | Script metadata base class |
| GSInfrastructure | Infrastructure piece counts and costs |
| GSCargoMonitor | Track cargo delivery/pickup per company |
| GSNewGRF | NewGRF compatibility |
| GSObjectType | Map object type info |
| GSPriorityQueue | Priority queue data structure |
| GSText | Localized text strings |

---

## 3. Detailed Method Reference — Core Classes

### 3.1 GSVehicle

#### Query Methods
| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| IsValidVehicle | vehicle_id | bool | Check if vehicle exists |
| IsPrimaryVehicle | vehicle_id | bool | Is main vehicle (not wagon) |
| GetNumWagons | vehicle_id | int | Number of wagons |
| GetName | vehicle_id | string | Vehicle name |
| GetOwner | vehicle_id | CompanyID | Owning company |
| GetLocation | vehicle_id | TileIndex | Current tile position |
| GetEngineType | vehicle_id | EngineID | Engine type |
| GetWagonEngineType | vehicle_id, wagon | EngineID | Wagon engine type |
| GetUnitNumber | vehicle_id | int | Display unit number |
| GetAge | vehicle_id | int | Age in days |
| GetWagonAge | vehicle_id, wagon | int | Specific wagon age |
| GetMaxAge | vehicle_id | int | Maximum age in days |
| GetAgeLeft | vehicle_id | int | Days until retirement |
| GetCurrentSpeed | vehicle_id | int | Current speed |
| GetState | vehicle_id | VehicleState | Running/stopped/crashed/etc |
| GetRunningCost | vehicle_id | Money | Annual running cost |
| GetProfitThisYear | vehicle_id | Money | Current year profit |
| GetProfitLastYear | vehicle_id | Money | Last year profit |
| GetCurrentValue | vehicle_id | Money | Current sale value |
| GetVehicleType | vehicle_id | VehicleType | Rail/Road/Water/Air |
| GetRoadType | vehicle_id | RoadType | Road type (road vehicles) |
| IsInDepot | vehicle_id | bool | In any depot |
| IsStoppedInDepot | vehicle_id | bool | Stopped in depot |
| GetRefitCapacity | vehicle_id, cargo | int | Capacity if refitted |
| GetCapacity | vehicle_id, cargo | int | Current cargo capacity |
| GetLength | vehicle_id | int | Train length in tiles/16 |
| GetCargoLoad | vehicle_id, cargo | int | Currently loaded cargo |
| GetGroupID | vehicle_id | GroupID | Assigned group |
| IsArticulated | vehicle_id | bool | Multi-part vehicle |
| HasSharedOrders | vehicle_id | bool | Has shared orders |
| GetReliability | vehicle_id | int | Current reliability % |
| GetMaximumOrderDistance | vehicle_id | int | Max order distance |

#### Action Methods
| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| SetName | vehicle_id, name | bool | Rename vehicle |
| BuildVehicle | depot_tile, engine_id | VehicleID | Purchase vehicle |
| BuildVehicleWithRefit | depot_tile, engine_id, cargo | VehicleID | Purchase with refit |
| CloneVehicle | depot_tile, vehicle_id, share_orders | VehicleID | Clone vehicle |
| MoveWagon | src_vid, src_wagon, dst_vid, dst_wagon | bool | Move single wagon |
| MoveWagonChain | src_vid, src_wagon, dst_vid, dst_wagon | bool | Move wagon chain |
| RefitVehicle | vehicle_id, cargo | bool | Change cargo type |
| SellVehicle | vehicle_id | bool | Sell entire vehicle |
| SellWagon | vehicle_id, wagon | bool | Sell single wagon |
| SellWagonChain | vehicle_id, wagon | bool | Sell wagon + trailing |
| SendVehicleToDepot | vehicle_id | bool | Go to nearest depot |
| SendVehicleToDepotForServicing | vehicle_id | bool | Service at depot |
| StartStopVehicle | vehicle_id | bool | Toggle running state |
| ReverseVehicle | vehicle_id | bool | Reverse direction |

### 3.2 GSOrder

#### Query Methods
| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| IsValidVehicleOrder | vid, pos | bool | Valid order position |
| IsGotoStationOrder | vid, pos | bool | Station order |
| IsGotoDepotOrder | vid, pos | bool | Depot order |
| IsGotoWaypointOrder | vid, pos | bool | Waypoint order |
| IsConditionalOrder | vid, pos | bool | Conditional order |
| IsVoidOrder | vid, pos | bool | Invalid/void order |
| IsRefitOrder | vid, pos | bool | Has refit cargo |
| IsCurrentOrderPartOfOrderList | vid | bool | Current order in list |
| GetOrderCount | vid | int | Total orders |
| GetOrderDestination | vid, pos | TileIndex | Destination tile |
| GetOrderFlags | vid, pos | OrderFlags | Order flags bitmask |
| GetOrderJumpTo | vid, pos | OrderPosition | Conditional jump target |
| GetOrderCondition | vid, pos | OrderCondition | Condition type |
| GetOrderCompareFunction | vid, pos | CompareFunction | Comparison function |
| GetOrderCompareValue | vid, pos | int | Comparison value |
| GetStopLocation | vid, pos | StopLocation | Train stop position |
| GetOrderRefit | vid, pos | CargoType | Refit cargo type |
| GetOrderDistance | vtype, tile1, tile2 | int | Distance for vehicle type |

#### Action Methods
| Method | Parameters | Returns | Description |
|--------|-----------|---------|-------------|
| AppendOrder | vid, tile, flags | bool | Add order at end |
| InsertOrder | vid, pos, tile, flags | bool | Insert before position |
| RemoveOrder | vid, pos | bool | Remove order |
| MoveOrder | vid, from, to | bool | Reorder |
| SkipToOrder | vid, pos | bool | Jump to order |
| CopyOrders | vid, src_vid | bool | One-time copy |
| ShareOrders | vid, src_vid | bool | Share order list |
| UnshareOrders | vid | bool | Break sharing |
| AppendConditionalOrder | vid, jump_to | bool | Add conditional at end |
| InsertConditionalOrder | vid, pos, jump_to | bool | Insert conditional |
| SetOrderFlags | vid, pos, flags | bool | Modify flags |
| SetOrderJumpTo | vid, pos, jump_to | bool | Set conditional target |
| SetOrderCondition | vid, pos, condition | bool | Set condition type |
| SetOrderCompareFunction | vid, pos, func | bool | Set comparison |
| SetOrderCompareValue | vid, pos, value | bool | Set compare value |
| SetStopLocation | vid, pos, location | bool | Set train stop pos |
| SetOrderRefit | vid, pos, cargo | bool | Set refit cargo |

### 3.3 GSRail

| Method | Parameters | Returns | Type |
|--------|-----------|---------|------|
| GetName | rail_type | string | Query |
| IsRailTile | tile | bool | Query |
| IsLevelCrossingTile | tile | bool | Query |
| IsRailDepotTile | tile | bool | Query |
| IsRailStationTile | tile | bool | Query |
| IsRailWaypointTile | tile | bool | Query |
| IsRailTypeAvailable | rail_type | bool | Query |
| GetCurrentRailType | — | RailType | Query |
| SetCurrentRailType | rail_type | void | Setup |
| TrainCanRunOnRail | engine_type, track_type | bool | Query |
| TrainHasPowerOnRail | engine_type, track_type | bool | Query |
| GetRailType | tile | RailType | Query |
| GetRailDepotFrontTile | depot_tile | TileIndex | Query |
| GetRailStationDirection | tile | RailTrack | Query |
| GetRailTracks | tile | int | Query |
| AreTilesConnected | from, tile, to | bool | Query |
| GetSignalType | tile, front | SignalType | Query |
| GetBuildCost | railtype, build_type | Money | Query |
| GetMaxSpeed | railtype | int | Query |
| GetMaintenanceCostFactor | railtype | int | Query |
| ConvertRailType | start, end, convert_to | bool | Action |
| BuildRailDepot | tile, front | bool | Action |
| BuildRailStation | tile, dir, platforms, length, station_id | bool | Action |
| BuildNewGRFRailStation | tile, dir, platforms, length, id, cargo, src_industry, dst_industry, distance, is_source | bool | Action |
| BuildRailWaypoint | tile | bool | Action |
| RemoveRailWaypointTileRectangle | tile, tile2, keep_rail | bool | Action |
| RemoveRailStationTileRectangle | tile, tile2, keep_rail | bool | Action |
| BuildRailTrack | tile, rail_track | bool | Action |
| RemoveRailTrack | tile, rail_track | bool | Action |
| BuildRail | from, tile, to | bool | Action |
| RemoveRail | from, tile, to | bool | Action |
| BuildSignal | tile, front, signal_type | bool | Action |
| RemoveSignal | tile, front | bool | Action |

### 3.4 GSRoad

| Method | Parameters | Returns | Type |
|--------|-----------|---------|------|
| GetName | road_type | string | Query |
| IsRoadTypeAvailable | road_type | bool | Query |
| GetCurrentRoadType | — | RoadType | Query |
| SetCurrentRoadType | road_type | void | Setup |
| GetRoadTramType | road_type | RoadTramTypes | Query |
| IsRoadTile | tile | bool | Query |
| IsRoadDepotTile | tile | bool | Query |
| IsRoadStationTile | tile | bool | Query |
| IsDriveThroughRoadStationTile | tile | bool | Query |
| HasRoadType | tile, road_type | bool | Query |
| AreRoadTilesConnected | tile1, tile2 | bool | Query |
| GetNeighbourRoadCount | tile | int | Query |
| GetRoadDepotFrontTile | tile | TileIndex | Query |
| GetRoadStationFrontTile | tile | TileIndex | Query |
| GetDriveThroughBackTile | tile | TileIndex | Query |
| RoadVehCanRunOnRoad | engine_type, road_type | bool | Query |
| RoadVehHasPowerOnRoad | engine_type, road_type | bool | Query |
| GetBuildCost | road_type, build_type | Money | Query |
| GetMaxSpeed | road_type | int | Query |
| GetMaintenanceCostFactor | road_type | int | Query |
| BuildRoad | from, to | bool | Action |
| BuildRoadFull | from, to | bool | Action |
| BuildOneWayRoad | from, to | bool | Action |
| BuildOneWayRoadFull | from, to | bool | Action |
| BuildRoadDepot | tile, front | bool | Action |
| BuildRoadStation | tile, front, veh_type, station_id | bool | Action |
| BuildDriveThroughRoadStation | tile, front, veh_type, station_id | bool | Action |
| RemoveRoad | from, to | bool | Action |
| RemoveRoadFull | from, to | bool | Action |
| RemoveRoadDepot | tile | bool | Action |
| RemoveRoadStation | tile | bool | Action |
| ConvertRoadType | start, end, road_type | bool | Action |

### 3.5 GSTown

| Method | Parameters | Returns | Type |
|--------|-----------|---------|------|
| GetTownCount | — | int | Query |
| IsValidTown | town_id | bool | Query |
| GetName | town_id | string | Query |
| GetPopulation | town_id | int | Query |
| GetHouseCount | town_id | int | Query |
| GetLocation | town_id | TileIndex | Query |
| GetLastMonthProduction | town_id, cargo | int | Query |
| GetLastMonthSupplied | town_id, cargo | int | Query |
| GetLastMonthTransportedPercentage | town_id, cargo | int | Query |
| GetLastMonthReceived | town_id, town_effect | int | Query |
| GetCargoGoal | town_id, town_effect | int | Query |
| GetGrowthRate | town_id | int | Query |
| GetDistanceManhattanToTile | town_id, tile | int | Query |
| IsWithinTownInfluence | town_id, tile | bool | Query |
| HasStatue | town_id | bool | Query |
| IsCity | town_id | bool | Query |
| GetRoadReworkDuration | town_id | int | Query |
| GetFundBuildingsDuration | town_id | int | Query |
| GetExclusiveRightsCompany | town_id | CompanyID | Query |
| GetExclusiveRightsDuration | town_id | int | Query |
| IsActionAvailable | town_id, action | bool | Query |
| GetRating | town_id, company_id | TownRating | Query |
| GetDetailedRating | town_id, company_id | int | Query |
| GetAllowedNoise | town_id | int | Query |
| GetRoadLayout | town_id | RoadLayout | Query |
| SetName | town_id, name | bool | GS Action |
| SetText | town_id, text | bool | GS Action |
| SetCargoGoal | town_id, effect, goal | bool | GS Action |
| SetGrowthRate | town_id, days | bool | GS Action |
| PerformTownAction | town_id, action | bool | GS Action |
| ExpandTown | town_id, houses | bool | GS Action |
| FoundTown | tile, size, city, layout, name | bool | GS Action |
| ChangeRating | town_id, company_id, delta | bool | GS Action |

### 3.6 GSCompany

| Method | Parameters | Returns | Type |
|--------|-----------|---------|------|
| ResolveCompanyID | company | CompanyID | Query |
| IsMine | company | bool | Query |
| GetName | company | string | Query |
| GetPresidentName | company | string | Query |
| GetPresidentGender | company | Gender | Query |
| GetBankBalance | company | Money | Query |
| GetLoanAmount | — | Money | Query (needs CompanyMode) |
| GetMaxLoanAmount | — | Money | Query (needs CompanyMode) |
| GetLoanInterval | — | Money | Query |
| GetQuarterlyIncome | company, quarter | Money | Query |
| GetQuarterlyExpenses | company, quarter | Money | Query |
| GetQuarterlyCargoDelivered | company, quarter | int | Query |
| GetQuarterlyPerformanceRating | company, quarter | int | Query |
| GetQuarterlyCompanyValue | company, quarter | Money | Query |
| GetCompanyHQ | company | TileIndex | Query |
| GetAutoRenewStatus | company | bool | Query |
| GetAutoRenewMonths | company | int | Query |
| GetAutoRenewMoney | company | Money | Query |
| GetPrimaryLiveryColour | scheme | Colours | Query |
| GetSecondaryLiveryColour | scheme | Colours | Query |
| SetName | name | bool | Action |
| SetPresidentName | name | bool | Action |
| SetPresidentGender | gender | bool | Action |
| SetLoanAmount | loan | bool | Action |
| SetMinimumLoanAmount | loan | bool | Action |
| BuildCompanyHQ | tile | bool | Action |
| SetAutoRenewStatus | bool | bool | Action |
| SetAutoRenewMonths | months | bool | Action |
| SetAutoRenewMoney | money | bool | Action |
| SetPrimaryLiveryColour | scheme, colour | bool | Action |
| SetSecondaryLiveryColour | scheme, colour | bool | Action |
| ChangeBankBalance | company, delta, type, tile | bool | GS Action |
| SetMaxLoanAmountForCompany | company, amount | bool | GS Action |
| ResetMaxLoanAmountForCompany | company | bool | GS Action |

### 3.7 Other Key Classes (Summary)

**GSStation**: GetCargoWaiting/From/Via/FromVia, GetCargoPlanned/From/Via/FromVia, GetCargoRating, HasCargoRating, GetCoverageRadius, HasStationType, HasRoadType, GetNearestTown, IsAirportClosed, OpenCloseAirport

**GSIndustry**: GetIndustryCount, GetName/Location/Type, GetLastMonthProduction/Transported/TransportedPercentage, GetStockpiledCargo, IsCargoAccepted, HasHeliport/Dock, GetHeliportLocation/DockLocation, GetAmountOfStationsAround, GetProductionLevel, SetProductionLevel, SetControlFlags, SetExclusiveSupplier/Consumer, SetText

**GSEngine**: IsValidEngine, IsBuildable, GetName/VehicleType/CargoType/Capacity/Price/RunningCost/Reliability/MaxSpeed/Power/Weight/MaxTractiveEffort/MaxAge/DesignDate, CanRefitCargo/CanPullCargo, GetRailType/RoadType/PlaneType, IsWagon/IsArticulated, EnableForCompany/DisableForCompany

**GSMarine**: IsWaterDepotTile/IsDockTile/IsBuoyTile/IsLockTile/IsCanalTile, AreWaterTilesConnected, BuildWaterDepot/BuildDock/BuildBuoy/BuildLock/BuildCanal, Remove* for each, GetBuildCost

**GSAirport**: IsValidAirportType, GetPrice, IsHangarTile/IsAirportTile, GetAirportWidth/Height/CoverageRadius, GetNumHangars/GetHangarOfAirport, BuildAirport/RemoveAirport, GetAirportType, GetNoiseLevelIncrease/GetNearestTown, GetMaintenanceCostFactor/GetMonthlyMaintenanceCost

**GSBridge**: IsValidBridge, IsBridgeTile, GetBridgeType/GetName/GetMaxSpeed/GetPrice/GetMaxLength/GetMinLength, BuildBridge/RemoveBridge, GetOtherBridgeEnd

**GSTunnel**: IsTunnelTile, GetOtherTunnelEnd, BuildTunnel, RemoveTunnel

**GSTile**: IsBuildable/IsBuildableRectangle, IsSeaTile/IsRiverTile/IsWaterTile/IsCoastTile/IsStationTile/IsHouseTile, HasTreeOnTile/IsFarmTile/IsRockTile, GetTerrainType/GetSlope/GetMinHeight/GetMaxHeight/GetCornerHeight, GetOwner, HasTransportType, GetCargoAcceptance/GetCargoProduction, GetDistanceManhattanToTile, GetTownAuthority/GetClosestTown, GetBuildCost, RaiseTile/LowerTile/LevelTiles/DemolishTile/PlantTree/PlantTreeRectangle

---

## 4. Event System Deep Dive

### 4.1 Event Loop Pattern

```squirrel
while (GSEventController.IsEventWaiting()) {
  local event = GSEventController.GetNextEvent();
  switch (event.GetEventType()) {
    case GSEvent.ET_ADMIN_PORT:
      local admin = GSEventAdminPort.Convert(event);
      local data = admin.GetObject(); // JSON table
      break;
    case GSEvent.ET_VEHICLE_CRASHED:
      local crash = GSEventVehicleCrashed.Convert(event);
      local vid = crash.GetVehicleID();
      local site = crash.GetCrashSite();
      local reason = crash.GetCrashReason();
      local victims = crash.GetVictims();
      break;
    // ... etc
  }
}
```

### 4.2 All 35 Event Types

| Event Type | Data Available | Use Case |
|-----------|---------------|----------|
| **ET_ADMIN_PORT** | `GetObject()` → Squirrel table (JSON) | Receive commands from external systems |
| **ET_COMPANY_NEW** | `GetCompanyID()` | Track new companies joining |
| **ET_COMPANY_IN_TROUBLE** | `GetCompanyID()` | Company low on funds |
| **ET_COMPANY_MERGER** | Old company, new company | Company acquired |
| **ET_COMPANY_BANKRUPT** | `GetCompanyID()` | Company went bankrupt |
| **ET_COMPANY_RENAMED** | Company ID | Company name changed |
| **ET_PRESIDENT_RENAMED** | Company ID | President name changed |
| **ET_VEHICLE_CRASHED** | `GetVehicleID()`, `GetCrashSite()`, `GetCrashReason()`, `GetVictims()`, `GetVehicleOwner()` | React to crashes |
| **ET_VEHICLE_LOST** | Vehicle ID | Vehicle can't find path |
| **ET_VEHICLE_WAITING_IN_DEPOT** | Vehicle ID | Vehicle arrived at depot |
| **ET_VEHICLE_UNPROFITABLE** | Vehicle ID | Vehicle losing money |
| **ET_VEHICLE_AUTOREPLACED** | Vehicle ID | Auto-replace completed |
| **ET_INDUSTRY_OPEN** | `GetIndustryID()` | New industry spawned |
| **ET_INDUSTRY_CLOSE** | `GetIndustryID()` | Industry closing down |
| **ET_ENGINE_PREVIEW** | Engine ID | Exclusive engine preview offer |
| **ET_ENGINE_AVAILABLE** | Engine ID | New engine type available |
| **ET_SUBSIDY_OFFER** | `GetSubsidyID()` | New subsidy available |
| **ET_SUBSIDY_OFFER_EXPIRED** | Subsidy ID | Unclaimed subsidy expired |
| **ET_SUBSIDY_AWARDED** | Subsidy ID | Subsidy claimed by company |
| **ET_SUBSIDY_EXPIRED** | Subsidy ID | Active subsidy expired |
| **ET_STATION_FIRST_VEHICLE** | Station ID | First vehicle visits new station |
| **ET_TOWN_FOUNDED** | Town ID | New town created |
| **ET_AIRCRAFT_DEST_TOO_FAR** | Vehicle ID | Aircraft can't reach destination |
| **ET_EXCLUSIVE_TRANSPORT_RIGHTS** | Town ID, Company ID | Exclusive rights granted |
| **ET_ROAD_RECONSTRUCTION** | Town ID | Town rebuilding roads |
| **ET_GOAL_QUESTION_ANSWER** | Player response data | Player answered GS question |
| **ET_STORYPAGE_BUTTON_CLICK** | Page ID, element ID | Player clicked story button |
| **ET_STORYPAGE_TILE_SELECT** | Page ID, tile | Player selected tile |
| **ET_STORYPAGE_VEHICLE_SELECT** | Page ID, vehicle ID | Player selected vehicle |
| **ET_WINDOW_WIDGET_CLICK** | Window class, number, widget | Player clicked UI widget |
| **ET_DISASTER_ZEPPELINER_CRASHED** | Station ID | Zeppelin crashed at station |
| **ET_DISASTER_ZEPPELINER_CLEARED** | Station ID | Zeppelin wreckage cleared |

### 4.3 Vehicle Crash Reasons

| Constant | Meaning |
|----------|---------|
| CRASH_TRAIN | Two trains collided |
| CRASH_RV_LEVEL_CROSSING | Road vehicle hit by train at crossing |
| CRASH_RV_UFO | Road vehicle hit by UFO (disaster) |
| CRASH_PLANE_LANDING | Plane crashed on landing |
| CRASH_AIRCRAFT_NO_AIRPORT | Aircraft couldn't find airport |
| CRASH_FLOODED | Vehicle submerged by flooding |

---

## 5. Error System

### 5.1 Error Categories (13)

ERR_CAT_NONE, ERR_CAT_GENERAL, ERR_CAT_VEHICLE, ERR_CAT_STATION, ERR_CAT_BRIDGE, ERR_CAT_TUNNEL, ERR_CAT_TILE, ERR_CAT_SIGN, ERR_CAT_RAIL, ERR_CAT_ROAD, ERR_CAT_ORDER, ERR_CAT_MARINE, ERR_CAT_WAYPOINT

### 5.2 Common Error Types

| Error | Meaning |
|-------|---------|
| ERR_NONE | No error |
| ERR_UNKNOWN | Unknown error |
| ERR_PRECONDITION_FAILED | Precondition check failed |
| ERR_NOT_ENOUGH_CASH | Insufficient funds |
| ERR_LOCAL_AUTHORITY_REFUSES | Town authority rating too low |
| ERR_ALREADY_BUILT | Structure already exists |
| ERR_AREA_NOT_CLEAR | Tile occupied |
| ERR_OWNED_BY_ANOTHER_COMPANY | Not your property |
| ERR_NAME_IS_NOT_UNIQUE | Name already taken |
| ERR_FLAT_LAND_REQUIRED | Need flat terrain |
| ERR_LAND_SLOPED_WRONG | Wrong slope direction |
| ERR_VEHICLE_IN_THE_WAY | Vehicle blocking construction |
| ERR_SITE_UNSUITABLE | Location not suitable |
| ERR_TOO_CLOSE_TO_EDGE | Too near map edge |
| ERR_STATION_TOO_SPREAD_OUT | Station parts too far apart |
| ERR_BRIDGE_TOO_LOW | Bridge height insufficient |

### 5.3 GS Error Handling Pattern

```squirrel
if (!GSRail.BuildRailTrack(tile, track)) {
  local error = GSError.GetLastErrorString();
  local category = GSError.GetErrorCategory();
  return { success = false, error = error };
}
```

---

## 6. Financial Tracking

### 6.1 GSAccounting

Track costs of operations:
```squirrel
local accounting = GSAccounting();
// ... execute commands ...
local total_cost = accounting.GetCosts();
accounting.ResetCosts(); // reset to zero
// accounting is destroyed when scope exits, restoring previous state
```

### 6.2 Company Financial Queries

| Method | Returns |
|--------|---------|
| GSCompany.GetBankBalance(company) | Current cash |
| GSCompany.GetLoanAmount() | Current loan (in CompanyMode) |
| GSCompany.GetMaxLoanAmount() | Max available loan |
| GSCompany.GetLoanInterval() | Loan step amount |
| GSCompany.GetQuarterlyIncome(company, quarter) | Revenue (quarter 1=current) |
| GSCompany.GetQuarterlyExpenses(company, quarter) | Expenses |
| GSCompany.GetQuarterlyCargoDelivered(company, quarter) | Cargo units delivered |
| GSCompany.GetQuarterlyPerformanceRating(company, quarter) | Rating (0-1000) |
| GSCompany.GetQuarterlyCompanyValue(company, quarter) | Total company value |

### 6.3 Infrastructure Costs

| Method | Returns |
|--------|---------|
| GSInfrastructure.GetRailPieceCount(company, rail_type) | Rail pieces owned |
| GSInfrastructure.GetRoadPieceCount(company, road_type) | Road pieces owned |
| GSInfrastructure.GetMonthlyRailCosts(company, rail_type) | Monthly rail maintenance |
| GSInfrastructure.GetMonthlyRoadCosts(company, road_type) | Monthly road maintenance |
| GSInfrastructure.GetMonthlyInfrastructureCosts(company, infra_type) | Monthly total maintenance |

### 6.4 Cargo Monitoring

| Method | Returns |
|--------|---------|
| GSCargoMonitor.GetTownDeliveryAmount(company, cargo, town, keep) | Cargo delivered to town since last query |
| GSCargoMonitor.GetIndustryDeliveryAmount(company, cargo, industry, keep) | Cargo delivered to industry |
| GSCargoMonitor.GetTownPickupAmount(company, cargo, town, keep) | Cargo picked up from town |
| GSCargoMonitor.GetIndustryPickupAmount(company, cargo, industry, keep) | Cargo picked up from industry |
| GSCargoMonitor.StopAllMonitoring() | Stop all monitoring |

The `keep` parameter: if true, continue monitoring; if false, stop after this query.

---

## 7. Game Settings Control

### 7.1 GSGameSettings

```squirrel
GSGameSettings.IsValid("economy.inflation")     // Check if setting exists
GSGameSettings.GetValue("economy.inflation")     // Get current value
GSGameSettings.SetValue("economy.inflation", 0)  // Disable inflation
```

**Key game settings for AI control**:

| Setting | Values | Effect |
|---------|--------|--------|
| `game_creation.starting_year` | Year | Starting game year |
| `economy.inflation` | 0/1 | Enable/disable inflation |
| `economy.smooth_economy` | 0/1 | Smooth vs default production changes |
| `difficulty.max_loan` | Amount | Maximum loan available |
| `vehicle.max_trains` | 0-5000 | Max trains per company |
| `vehicle.max_roadveh` | 0-5000 | Max road vehicles |
| `vehicle.max_aircraft` | 0-5000 | Max aircraft |
| `vehicle.max_ships` | 0-5000 | Max ships |
| `construction.max_bridge_length` | Tiles | Maximum bridge span |
| `station.station_spread` | Tiles | Max station spread |

### 7.2 Disabled Vehicle Types

```squirrel
GSGameSettings.IsDisabledVehicleType(GSVehicle.VT_RAIL)  // Check if trains disabled
```

---

## 8. Communication: Admin Port Protocol

### 8.1 GS → External (Sending)

```squirrel
GSAdmin.Send({ key = "value", number = 42, array = [1, 2, 3] });
```

- **Limit**: 1450 bytes per JSON packet
- **Format**: Squirrel table → JSON
- **No acknowledgment**: Fire-and-forget

### 8.2 External → GS (Receiving)

Via `ET_ADMIN_PORT` events:
```squirrel
local event = GSEventAdminPort.Convert(generic_event);
local data = event.GetObject(); // Squirrel table from JSON
```

### 8.3 Protocol Design (as implemented in nttd)

**Command** (external → GS):
```json
{ "id": "gs_42", "action": "build_road", "params": { "company_id": 0, "from_x": 10, "from_y": 20, "to_x": 10, "to_y": 25 } }
```

**Response** (GS → external):
```json
{ "id": "gs_42", "success": true, "result": { "from": [10, 20], "to": [10, 25] } }
```

**Chunked response** (for large arrays):
```json
{ "id": "gs_42", "success": true, "result": [...10 items...], "_chunk": 0, "_total": 3 }
{ "id": "gs_42", "success": true, "result": [...10 items...], "_chunk": 1, "_total": 3 }
{ "id": "gs_42", "success": true, "result": [...5 items...], "_chunk": 2, "_total": 3 }
```

---

## 9. Known Squirrel/GS Gotchas

| Issue | Details |
|-------|---------|
| **Reserved keywords** | Cannot use `clone`, `parent`, `delete`, `in`, `for`, `function`, `class`, `extends` as variable/key names |
| **GetLoanAmount() takes NO args** | Must be called inside GSCompanyMode context |
| **GetMaxLoanAmount() takes NO args** | Same as above |
| **GSBridge.GetName() needs 2 args** | `GetName(bridge_type, vehicle_type)` — second arg is VT_ROAD etc |
| **GSAirport.GetNoiseLevelIncrease** | `(tile, type)` — tile first, type second |
| **CloneVehicle result** | Store in `cid`, not `clone` (reserved keyword) |
| **Admin packet null terminator** | JSON from GS includes `\x00` — strip before parsing |
| **OpenTTD 15.x config** | `[game_scripts]` requires quoted name; admin_password in secrets.cfg |
| **1450 byte packet limit** | Large responses must be chunked |
| **Sequential company mode** | Can only act as one company per GSCompanyMode scope |
| **Save() restrictions** | Only primitive types (int, string, bool, null, array, table); no classes, max 25 nesting |
| **Stable IDs across saves** | StationID, TownID, VehicleID persist; CargoID, EngineID, BridgeID may change |
