# Operator

Scenario setup rather than play. Refused during a scored game, and listed here so it is clear they exist and why they are unavailable.

**Generated. Do not edit.** Run `uv run python scripts/generate_action_manifest.py`.
Part of the [action reference](../action_reference.md). 9 of 129 actions.

## Contents

- **finance**: `change_bank_balance`, `set_max_loan`
- **settings**: `set_game_setting`
- **subsidy**: `create_subsidy`
- **town_deity**: `change_town_rating`, `expand_town`, `found_town`, `set_cargo_goal`, `set_town_growth`

Every action on one line, across all three pages: [index.md](index.md).

## finance

### `change_bank_balance`

Move money into or out of a company's account directly. Operator-tier: this is scenario machinery, not play, and it is refused during a scored game.

- `delta` (integer, required) How much to add. Negative subtracts.
- `expense_type` (integer, default GSCompany.EXPENSES_OTHER) Which column of the company accounts the money moves through.

`expense_type` accepts (GSCompany): `EXPENSES_AIRCRAFT_INC` = 9, `EXPENSES_AIRCRAFT_RUN` = 4, `EXPENSES_CONSTRUCTION` = 0, `EXPENSES_LOAN_INT` = 11, `EXPENSES_NEW_VEHICLES` = 1, `EXPENSES_OTHER` = 12, `EXPENSES_PROPERTY` = 6, `EXPENSES_ROADVEH_INC` = 8, `EXPENSES_ROADVEH_RUN` = 3, `EXPENSES_SHIP_INC` = 10, `EXPENSES_SHIP_RUN` = 5, `EXPENSES_TRAIN_INC` = 7, `EXPENSES_TRAIN_RUN` = 2

### `set_max_loan`

Set the ceiling a company may borrow up to. Operator-tier: it changes the terms of the game rather than playing it.

- `amount` (integer, required) An amount of money, in the game's currency units.

## settings

### `set_game_setting`

Change a game setting mid-game. Operator-tier: it alters the rules rather than playing by them, and is refused during a scored game.

- `key` (string, required) Name of a game setting, as it appears in openttd.cfg.
- `value` (integer, required) The value to set.

## subsidy

### `create_subsidy`

Create a subsidy for carrying a cargo between two places. Operator-tier: subsidies are part of setting a scenario, not of playing one.

- `cargo_type` (integer, required) Which cargo. Numbered by the running game, so ask get_cargo_types rather than assuming.
- `from_id` (integer, required) The industry or town the cargo is collected from, matching from_type.
- `from_type` (integer, required) Whether the source is an industry or a town.
- `to_id` (integer, required) The industry or town the cargo is delivered to, matching to_type.
- `to_type` (integer, required) Whether the destination is an industry or a town.

`from_type` accepts (GSSubsidy): `SPT_INDUSTRY` = 0, `SPT_TOWN` = 1

`to_type` accepts (GSSubsidy): `SPT_INDUSTRY` = 0, `SPT_TOWN` = 1

## town_deity

### `change_town_rating`

Set a company's standing with a town directly. Operator-tier: it overrides the reputation a contestant is supposed to earn.

- `delta` (integer, required) How much to add. Negative subtracts.
- `town_id` (integer, required) Which town.

### `expand_town`

Grow a town by a number of houses at once. Operator-tier.

- `houses` (integer, default 5) How many houses to add.
- `town_id` (integer, required) Which town.

### `found_town`

Found a new town at a tile. Operator-tier: it changes the map the scenario is scored on.

- `is_city` (boolean, default false) Found a city rather than an ordinary town. Cities grow faster.
- `name` (string, default null) A name to give.
- `road_layout` (integer, default GSTown.ROAD_LAYOUT_ORIGINAL) The street pattern the town grows into.
- `size` (integer, default GSTown.TOWN_SIZE_SMALL) How large to start.
- `x` (integer, required) X coordinate on the map, counting from 0.
- `y` (integer, required) Y coordinate on the map, counting from 0.

`road_layout` accepts (GSTown): `ROAD_LAYOUT_2x2` = 2, `ROAD_LAYOUT_3x3` = 3, `ROAD_LAYOUT_BETTER_ROADS` = 1, `ROAD_LAYOUT_ORIGINAL` = 0, `ROAD_LAYOUT_RANDOM` = 4

`size` accepts (GSTown): `TOWN_SIZE_LARGE` = 2, `TOWN_SIZE_MEDIUM` = 1, `TOWN_SIZE_SMALL` = 0

### `set_cargo_goal`

Set how much of a cargo a town must receive. Operator-tier: this is goal-setting machinery for a scenario.

- `goal` (integer, required) How much cargo the town must receive.
- `town_effect` (integer, required) Which cargo effect the goal is set against.
- `town_id` (integer, required) Which town.

`town_effect` accepts (GSCargo): `TE_FOOD` = 5, `TE_GOODS` = 3, `TE_MAIL` = 2, `TE_NONE` = 0, `TE_PASSENGERS` = 1, `TE_WATER` = 4

### `set_town_growth`

Set how often a town adds a house, in days. Operator-tier.

- `days` (integer, required) A number of days.
- `town_id` (integer, required) Which town.

