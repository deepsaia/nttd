# Operator

Scenario setup rather than play. Refused during a scored game, and listed here so it is clear they exist and why they are unavailable.

**Generated. Do not edit.** Run `uv run python scripts/generate_action_manifest.py`.
Part of the [action reference](../action_reference.md). 9 of 129 actions.

## Contents

- **finance**: `change_bank_balance`, `set_max_loan`
- **settings**: `set_game_setting`
- **subsidy**: `create_subsidy`
- **town_deity**: `change_town_rating`, `expand_town`, `found_town`, `set_cargo_goal`, `set_town_growth`

## finance

### `change_bank_balance`

Move money into or out of a company's account directly. Operator-tier: this is scenario machinery, not play, and it is refused during a scored game.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `delta` | integer | yes |  | How much to add. Negative subtracts. |
| `expense_type` | integer | no | `GSCompany.EXPENSES_OTHER` | Which column of the company accounts the money moves through. |

`expense_type` accepts (GSCompany): `EXPENSES_AIRCRAFT_INC` = 9, `EXPENSES_AIRCRAFT_RUN` = 4, `EXPENSES_CONSTRUCTION` = 0, `EXPENSES_LOAN_INT` = 11, `EXPENSES_NEW_VEHICLES` = 1, `EXPENSES_OTHER` = 12, `EXPENSES_PROPERTY` = 6, `EXPENSES_ROADVEH_INC` = 8, `EXPENSES_ROADVEH_RUN` = 3, `EXPENSES_SHIP_INC` = 10, `EXPENSES_SHIP_RUN` = 5, `EXPENSES_TRAIN_INC` = 7, `EXPENSES_TRAIN_RUN` = 2

### `set_max_loan`

Set the ceiling a company may borrow up to. Operator-tier: it changes the terms of the game rather than playing it.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `amount` | integer | yes |  | An amount of money, in the game's currency units. |

## settings

### `set_game_setting`

Change a game setting mid-game. Operator-tier: it alters the rules rather than playing by them, and is refused during a scored game.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `key` | string | yes |  | Name of a game setting, as it appears in openttd.cfg. |
| `value` | integer | yes |  | The value to set. |

## subsidy

### `create_subsidy`

Create a subsidy for carrying a cargo between two places. Operator-tier: subsidies are part of setting a scenario, not of playing one.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `cargo_type` | integer | yes |  | Which cargo. Numbered by the running game, so ask get_cargo_types rather than assuming. |
| `from_id` | integer | yes |  | The industry or town the cargo is collected from, matching from_type. |
| `from_type` | integer | yes |  | Whether the source is an industry or a town. |
| `to_id` | integer | yes |  | The industry or town the cargo is delivered to, matching to_type. |
| `to_type` | integer | yes |  | Whether the destination is an industry or a town. |

`from_type` accepts (GSSubsidy): `SPT_INDUSTRY` = 0, `SPT_TOWN` = 1

`to_type` accepts (GSSubsidy): `SPT_INDUSTRY` = 0, `SPT_TOWN` = 1

## town_deity

### `change_town_rating`

Set a company's standing with a town directly. Operator-tier: it overrides the reputation a contestant is supposed to earn.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `delta` | integer | yes |  | How much to add. Negative subtracts. |
| `town_id` | integer | yes |  | Which town. |

### `expand_town`

Grow a town by a number of houses at once. Operator-tier.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `houses` | integer | no | `5` | How many houses to add. |
| `town_id` | integer | yes |  | Which town. |

### `found_town`

Found a new town at a tile. Operator-tier: it changes the map the scenario is scored on.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `is_city` | boolean | no | `false` | Found a city rather than an ordinary town. Cities grow faster. |
| `name` | string | no | `null` | A name to give. |
| `road_layout` | integer | no | `GSTown.ROAD_LAYOUT_ORIGINAL` | The street pattern the town grows into. |
| `size` | integer | no | `GSTown.TOWN_SIZE_SMALL` | How large to start. |
| `x` | integer | yes |  | X coordinate on the map, counting from 0. |
| `y` | integer | yes |  | Y coordinate on the map, counting from 0. |

`road_layout` accepts (GSTown): `ROAD_LAYOUT_2x2` = 2, `ROAD_LAYOUT_3x3` = 3, `ROAD_LAYOUT_BETTER_ROADS` = 1, `ROAD_LAYOUT_ORIGINAL` = 0, `ROAD_LAYOUT_RANDOM` = 4

`size` accepts (GSTown): `TOWN_SIZE_LARGE` = 2, `TOWN_SIZE_MEDIUM` = 1, `TOWN_SIZE_SMALL` = 0

### `set_cargo_goal`

Set how much of a cargo a town must receive. Operator-tier: this is goal-setting machinery for a scenario.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `goal` | integer | yes |  | How much cargo the town must receive. |
| `town_effect` | integer | yes |  | Which cargo effect the goal is set against. |
| `town_id` | integer | yes |  | Which town. |

`town_effect` accepts (GSCargo): `TE_FOOD` = 5, `TE_GOODS` = 3, `TE_MAIL` = 2, `TE_NONE` = 0, `TE_PASSENGERS` = 1, `TE_WATER` = 4

### `set_town_growth`

Set how often a town adds a house, in days. Operator-tier.

| Parameter | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `days` | integer | yes |  | A number of days. |
| `town_id` | integer | yes |  | Which town. |

