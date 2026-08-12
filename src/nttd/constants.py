"""Project-wide constants: the action vocabulary, grouped by category and tier.

The rule for what a contestant may do is HUMAN PARITY: an agent may take any
action a human player can take through the OpenTTD GUI, and nothing more. Actions
with no human equivalent are operator-tier, available for scenario authoring and
debugging but not for play.

Used by: action_routes.py, the action manifest generator (which reads the tiers and
categories from here), and mcp/action_types.py, which turns them into the enums an MCP
client sees in its tool schema.
"""

# ---------------------------------------------------------------------------
# How many companies a contestant plays

MAX_CONTESTANT_COMPANIES = 1
"""One company per session, in every mode.

A multi-agent entry is several agents driving *one* company: the orchestrator decides
what the company does and submits one batch per step. RL and ES runs are one policy per
session and spawn their own. So nothing needs a second contestant company, and allowing
one would produce runs nothing can compare: a world shared by two contestants is a
different problem from a solo run on the same world, and no result row records which it
was.

Extra *non-contestant* companies are unaffected. ``num_ai_companies`` still creates idle
slots; they do not compete for cargo or town ratings.
"""

IDLE_AI_NAME = "nttd Idle"
"""The only AI nttd will run, and it does nothing at all.

**There are no AI opponents in nttd, by design.** ``ottd_config/ai/nttd-idle`` sleeps
forever; it exists to hold a company slot open, not to play. Every slot in the shipped
``openttd.cfg`` names it, and ``config_builder`` refuses to write a config that names
anything else.

A benchmark measures building a transport business in an empty market. Adding a real
competitor from OpenTTD's content service would make it measure something else, and
worse, something that varies: two runs on one seed would face different pressure
depending on which AI was installed and how it happened to play, and no result row
records either. nttd would be comparing runs that were never the same problem.

nttd is self-hosted, so this is not a defence against a contestant. It is a guarantee
that a world generated from a seed is the world anybody else generates from it.
"""

# ---------------------------------------------------------------------------
# Participant tier: actions a human player can take through the GUI
# ---------------------------------------------------------------------------

ACTION_CATEGORIES: dict[str, list[str]] = {
    "road": [
        "connect_road",
        "build_road_depot", "build_road_stop",
        "remove_road", "remove_road_depot", "remove_road_stop",
        # One-way roads and road/tram conversion are ordinary build-toolbar
        # operations. They were implemented in the GameScript but unreachable.
        "build_one_way_road", "build_one_way_road_full", "convert_road_type",
    ],
    "rail": [
        "connect_rail",
        "build_rail_station", "build_rail_depot",
        "build_rail_signal", "build_rail_waypoint",
        "build_rail_track",
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
    "town": [
        # perform_town_action covers advertising, funding buildings, statues, road
        # reconstruction, bribing the local authority, and buying exclusive
        # transport rights. All of these are buttons in the town window, so they
        # are legitimate strategy rather than a special power.
        "perform_town_action",
    ],
    "sign": ["build_sign", "remove_sign"],
    "group": ["create_group", "delete_group", "move_to_group", "set_auto_replace"],
    "vehicle": [
        "buy_vehicle", "build_train", "sell_vehicle", "sell_wagon", "move_wagon",
        "start_vehicle", "stop_vehicle", "send_to_depot", "send_to_depot_service",
        "clone_vehicle", "refit_vehicle", "reverse_vehicle", "rename_vehicle",
    ],
    "order": [
        "add_order", "insert_order", "remove_order", "skip_to_order",
        "move_order", "set_order_flags", "share_orders", "copy_orders",
        # Conditional orders ("skip unless load < 50%") are set in the orders
        # window and are what separates expert routing from novice routing. The
        # three set_order_compare/condition commands existed but could not be
        # reached, so an agent could not build branching vehicle logic at all.
        "set_order_condition", "set_order_compare_function",
        "set_order_compare_value", "set_stop_location",
    ],
    "landscape": [
        # Terraforming is a build-toolbar operation. Without it an agent cannot
        # prepare uneven ground, which rules out much of the map.
        "raise_tile", "lower_tile", "level_tiles",
        # Tree planting is how a human repairs a town's opinion of them.
        "plant_tree", "plant_tree_rectangle",
    ],
    "planning": [
        # A human sees the price in the build cursor before committing, so pricing
        # an action first is parity, not an advantage. Exposing it closes a gap:
        # the GameScript has implemented it all along with no way to reach it.
        "estimate_cost",
    ],
}

# Flat set of every action a contestant may take.
KNOWN_ACTIONS: set[str] = {
    action for actions in ACTION_CATEGORIES.values() for action in actions
}


# ---------------------------------------------------------------------------
# Operator tier: no human equivalent, so not available for play
# ---------------------------------------------------------------------------

OPERATOR_ACTION_CATEGORIES: dict[str, list[str]] = {
    "town_deity": [
        # A human cannot conjure a town, force its growth rate, or edit its
        # opinion of a company. These shape the world rather than play in it, so
        # they belong to whoever authors the scenario.
        "found_town", "expand_town", "set_town_growth",
        "change_town_rating", "set_cargo_goal",
    ],
    "subsidy": [
        # A human can only CLAIM a subsidy that the game offers. Minting one is
        # strictly superhuman.
        "create_subsidy",
    ],
    "finance": [
        # Free money, and raising one's own borrowing ceiling. max_loan is a
        # scenario setting from a player's point of view.
        "change_bank_balance", "set_max_loan",
    ],
    "settings": [
        # Rewriting game settings mid-run changes the task itself.
        "set_game_setting",
    ],
}

OPERATOR_ACTIONS: set[str] = {
    action for actions in OPERATOR_ACTION_CATEGORIES.values() for action in actions
}

# Sanity: an action cannot be both play and authoring.
assert not (KNOWN_ACTIONS & OPERATOR_ACTIONS)


# ---------------------------------------------------------------------------
# Read-only GameScript commands
# ---------------------------------------------------------------------------

# POST /state/gs/query reaches the GameScript directly, so it can call any command
# the GS implements -- it was a byte-for-byte clone of the guarded
# /actions/gs/execute. Verified: set_max_loan raised a scored company's credit
# ceiling from 300,000 to 9,000,000 through it.
#
# An explicit set rather than a "get_*" prefix rule, because a prefix rule silently
# admits any future mutator that happens to be named like a getter. A test
# cross-checks this against the GameScript dispatch table.
READ_ONLY_GS_ACTIONS: frozenset[str] = frozenset({
    "ping",
    "find_airport_spots", "find_bus_stop_spots", "find_depot_spots", "find_dock_spots",
    "find_flat_spots", "find_rail_depot_spot", "find_station_spot", "find_water_depot_spots",
    "get_airport_types", "get_bridge_types", "get_cargo_flows", "get_cargo_types",
    "get_clients", "get_companies", "get_company_finance", "get_date",
    "get_engine_details", "get_engines", "get_expense_breakdown", "get_game_settings",
    "get_groups", "get_hangars", "get_industries", "get_industry_info",
    "get_infrastructure_costs", "get_map_size", "get_map_terrain", "get_orders",
    "get_rail_types", "get_road_types", "get_signs", "get_station_info",
    "get_stations", "get_subsidies", "get_tile_area", "get_tile_info",
    "get_town_info", "get_town_rating", "get_towns", "get_vehicle_info",
    "get_vehicles", "get_waypoints", "scan_town_area",
})

# A read-only command must never also be an action, or the query endpoint would be
# a route around the action allowlist.
assert not (READ_ONLY_GS_ACTIONS & KNOWN_ACTIONS)
assert not (READ_ONLY_GS_ACTIONS & OPERATOR_ACTIONS)


# ---------------------------------------------------------------------------
# Actions that cannot execute while the game is paused
# ---------------------------------------------------------------------------

# These two search for a route inside the GameScript, and their A* yields every 500
# iterations through _YieldAndProcessEvents (main.nut:1920 and :2468), whose first
# statement is Sleep(1). Sleep counts GAME TICKS, and a paused game delivers none, so a
# long search hangs at any pause level. Everything else is safe paused: at
# construction.command_pause_level = 3 a paused build returns success in about 0.1s.
#
# Derived by reading the dispatch table rather than guessed: _FindRoadPath and
# _FindRailPath are the only functions that yield, and CmdConnectRoad and CmdConnectRail
# are their only callers. A test cross-checks that against the GameScript.
#
# The step flush consults this so that a batch without either can run against a still
# world, which is what makes a stepped run's advance exact rather than merely intended.
TICK_DEPENDENT_ACTIONS: frozenset[str] = frozenset({
    "connect_rail",
    "connect_road",
})

assert TICK_DEPENDENT_ACTIONS <= KNOWN_ACTIONS
