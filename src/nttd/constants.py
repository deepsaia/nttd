"""Project-wide constants — single source of truth for action types and categories."""

# All known action types, grouped by category.
# Used by: action_routes.py, interpreter/validator.py, mcp/tools/validation.py
ACTION_CATEGORIES: dict[str, list[str]] = {
    "road": [
        "connect_road",
        "build_road_depot", "build_road_stop",
        "remove_road", "remove_road_depot", "remove_road_stop",
    ],
    "rail": [
        "connect_rail",
        "build_rail_station", "build_rail_depot",
        "build_rail_signal", "build_rail_waypoint",
        "remove_rail", "remove_rail_track", "remove_signal", "remove_rail_station",
        "convert_rail",
    ],
    "marine": [
        "build_path",
        "build_canal", "build_lock", "build_buoy", "build_water_depot",
        "remove_canal", "remove_lock", "remove_buoy", "remove_water_depot",
    ],
    "air_and_other": [
        "build_airport", "remove_airport", "open_close_airport",
        "build_dock", "build_bridge", "build_tunnel", "demolish_tile",
    ],
    "company": ["build_company_hq", "set_loan", "rename_company"],
    "town_deity": [
        "found_town", "expand_town", "set_town_growth",
        "perform_town_action", "change_town_rating", "set_cargo_goal",
    ],
    "sign": ["build_sign", "remove_sign"],
    "group": ["create_group", "delete_group", "move_to_group", "set_auto_replace"],
    "vehicle": [
        "buy_vehicle", "sell_vehicle", "sell_wagon", "move_wagon",
        "start_vehicle", "stop_vehicle", "send_to_depot", "send_to_depot_service",
        "clone_vehicle", "refit_vehicle", "reverse_vehicle", "rename_vehicle",
    ],
    "order": [
        "add_order", "insert_order", "remove_order", "skip_to_order",
        "move_order", "set_order_flags", "share_orders", "copy_orders",
    ],
    "subsidy": ["create_subsidy"],
}

# Flat set of all known action type strings — derived from ACTION_CATEGORIES.
KNOWN_ACTIONS: set[str] = {
    action for actions in ACTION_CATEGORIES.values() for action in actions
}
