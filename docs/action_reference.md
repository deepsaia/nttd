# Action reference

Every action nttd can run, what it takes, and what the values mean.

**Generated. Do not edit.** Run `uv run python scripts/generate_action_manifest.py`.
The shape comes from `ottd_config/game/nttd-gs/main.nut`, the prose from
`config/actions/descriptions.json`, and the enum values from the OpenTTD build
itself (`15.3`) via `scripts/dump_gs_enums.py`.

The same content is served at `/v1/public/actions`, offered to MCP clients, and
printed by `nttd actions`.

Split by what running it does to the game, because that is the first thing worth
knowing and because reading all of it at once is rarely what you want.

| Reference | Count | What it is |
| --- | --- | --- |
| [Observations](actions/observations.md) | 44 | Read the world. Changes nothing. |
| [Actions](actions/actions.md) | 76 | Change the world. This is play. |
| [Operator](actions/operator.md) | 9 | Scenario setup. Refused during scored play. |

One caveat worth stating plainly: `get_cargo_flows` is filed as an observation
but is not free of consequence. Reading it resets the cargo monitors, so a
second read reports only what moved since the first. Every other observation can
be repeated without changing anything.

## Where a value comes from

Rail types, road types, cargo types, bridge types and airport types are numbered
by the running game, not fixed by nttd. Ask for them rather than assuming:
`get_rail_types`, `get_road_types`, `get_cargo_types`, `get_bridge_types`,
`get_airport_types`.

Where a parameter takes a named constant instead, the accepted values are listed
with it. Those are read from the OpenTTD build rather than written by hand,
because a wrong constant is worse than a missing one: `OF_UNLOAD` and
`OF_SERVICE_IF_NEEDED` are both 4.

`company_id` is never a parameter. nttd takes it from the participant token and
overwrites whatever was sent, so an action always runs as the company that
submitted it.

