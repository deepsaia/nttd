"""Every text the MCP server shows to an agent.

Tool descriptions, parameter descriptions, connection instructions and error notes all
live here, so they can be reviewed in one place before an experiment.
"""

from __future__ import annotations

MOVES_FORMAT_HINT = (
    'moves must be a list of objects, each {"command": <name>, '
    '"parameters": {...}}. Use the list_commands tool for parameter details.'
)

PARAMETERS_FORMAT_HINT = 'parameters must be an object, e.g. {"town_id": 3}.'

TIMEOUT_NOTE = (
    "The game searched for a route until its 120 s limit and found none. "
    "A search between two points with no possible route runs to the limit."
)

GAME_ENDED_NOTE = "The game has ended. No more actions can be taken."

MISSING_RESULT_NOTE = "The game returned no result for this command."

INSTRUCTIONS = """\
You are playing OpenTTD as one company, through nttd.

You build transport infrastructure and run vehicles to move cargo and passengers for
profit. You are scored on OpenTTD's own performance rating, which rewards delivered
cargo, vehicle count, station count, profit and money in hand.

Start by calling nttd_observe to see the world, and nttd_actions to look up anything you
have not called before. Prefer nttd_query for what the snapshot does not carry, such as
where a station will fit or which engines exist this year.

Actions are refused for ordinary reasons: too little money, a tile that will not take the
structure, a town with a poor opinion of you. A refusal is information, not a fault.
"""

AGENT_TAG_PARAM = "Name of the agent making the call. Leave it empty when there is only one agent."

OBSERVE = """Read the game state: the company, towns, industries, stations,
vehicles, routes, and the rest of the world.

The reply is the full state, not a summary.
With a focus set, the map part covers only the focus.
The state does not say which tiles are buildable or what a game command would cost; the query tool answers that.
"""

MOVE_COMMAND_PARAM = "Which game command to run."
MOVE_PARAMETERS_PARAM = "Its parameters. See the list_commands tool."
ACT_MOVES_PARAM = "Game commands, each with a command name and its parameters. They run in the specified order."
ACT_DRY_RUN_PARAM = "Only check the commands. Nothing is sent, the day does not advance, and you do not count as a submitter."

ACT_OPENING_STEPPED = "Send game commands to the company, or pass the day without any."
ACT_TIMING_STEPPED = """The commands of all agents in this turn form one batch. The batch runs
the agents in a random order, and the game advances one day after it. An empty moves list sends no command;
the day still advances and you count as a submitter."""
ACT_EMPTY_EXAMPLE_STEPPED = "pass the day:  "

ACT_OPENING_CLOCKED = "Send game commands to the company."
ACT_TIMING_CLOCKED = """The game runs on its own clock. Your commands run as soon as they
arrive, in the order given; the commands of other agents run when theirs
arrive. An empty moves list sends no command; you still count as a submitter."""
ACT_EMPTY_EXAMPLE_CLOCKED = "no command:    "

ACT_BODY = """{opening}
This single turn action can carry several commands: the moves list
holds them, and they run in the order given.

{timing} The reply reports
the outcome of each of your commands. A refused command is normal play
and can happen for many in-game reasons.

With dry_run true the commands are only checked for their names and
parameters. Nothing is sent, the day does not advance, and you do not
count as a submitter.

Examples of command formatting:
  {empty_example}   {{"moves": []}}
  one command:      {{"moves": [{{"command": "command_name", "parameters": {{"key": value}}}}]}}
  several commands: {{"moves": [{{"command": "command_name", "parameters": {{"key": value, "another_key": another_value}}}},
                               {{"command": "command_name", "parameters": {{"key": value, "another_key": another_value}}}}]}}

With a focus set, the snapshot in the reply covers only the focus; the
command outcomes are always complete.

Available game commands, by group. The list_commands tool gives the parameters of each:
{commands_by_group}
"""

QUERY_QUERY_PARAM = "Name of the query."
QUERY_PARAMETERS_PARAM = "The query's parameters as an object. The list_commands tool lists them per query."
QUERY_BODY = """Ask the running game a question.

Queries read what the state from observe does not carry. Examples include whether a tile
is buildable, where a station fits, which engines are for sale this
year, what an action would cost, a town's rating. Parameters differ per
query; the list_commands tool lists them.

Available queries:
  {queries}
"""

LIST_COMMANDS_NAME_PARAM = "A command or query name. Empty lists all of them."
LIST_COMMANDS = """Describe a command or query: its parameters, their types,
defaults, and the exact values they accept.

Without a name the reply is one line per command and query. Some
parameters take named constants or ids assigned by the game; the
reply says which, and the query tool returns the ids.
"""

FOCUS_TOWNS_PARAM = "Town names or ids to include."
FOCUS_INDUSTRIES_PARAM = "Industry names or ids to include."
FOCUS_X1_PARAM = "Left tile column of a rectangle to include."
FOCUS_Y1_PARAM = "Top tile row of a rectangle to include."
FOCUS_X2_PARAM = "Right tile column of a rectangle to include."
FOCUS_Y2_PARAM = "Bottom tile row of a rectangle to include."
FOCUS_PADDING_PARAM = "Tiles added on each side of the named places. Default {default_padding}."
FOCUS_CLEAR_PARAM = "True removes the focus."
FOCUS = """Choose the part of the map that your game replies describe.

Name towns or industries, by name or id, or give a tile rectangle
x1, y1, x2, y2, or both. The focus is the rectangle around them,
widened by padding tiles on each side. From then on, replies from
observe and act list only what is inside the focus: towns, industries
and stations by position, vehicles that are inside or have an order to
a station inside, and routes with a station or vehicle inside. The
company, the date and the outcomes of your own commands stay complete.
Each reply also carries an outside section, the towns and industries
outside with their coordinates and the counts of everything left out,
and the names of the agents whose focus overlaps yours. Agents without
a focus see the whole map.

Examples of params:
  two places:   {"towns": ["<town name>"], "industries": ["<industry name>"]}
  a rectangle:  {"x1": 100, "y1": 20, "x2": 160, "y2": 80}
  remove it:    {"clear": true}

The reply is the game state seen through the new focus.
"""

BATCH_ROUND = """Round envelope for an orchestrator that runs several agents.
Carries every agent's call for one round as {agent_tag, tool, args} entries,
where tool is one of observe, act, query, list_commands, focus. Reads run first,
all moves are sent together with the agents in a random order, and the game
advances exactly once. Replies with per-agent results keyed by agent_tag.
A single agent never needs this tool.
"""


def commands_by_group(manifest: dict, names: list[str]) -> str:
    """One line per manifest category, listing the given command names."""
    groups: dict[str, list[str]] = {}
    for name in names:
        category = manifest.get("actions", {}).get(name, {}).get("category", "other")
        groups.setdefault(category, []).append(name)
    return "\n".join(
        f"  {category}: {', '.join(sorted(members))}"
        for category, members in sorted(groups.items())
    )


def act_description(mode: str, manifest: dict, commands: list[str]) -> str:
    """The act tool text for the session's mode."""
    if mode == "stepped":
        opening, timing, example = ACT_OPENING_STEPPED, ACT_TIMING_STEPPED, ACT_EMPTY_EXAMPLE_STEPPED
    else:
        opening, timing, example = ACT_OPENING_CLOCKED, ACT_TIMING_CLOCKED, ACT_EMPTY_EXAMPLE_CLOCKED
    return ACT_BODY.format(
        opening=opening, timing=timing, empty_example=example,
        commands_by_group=commands_by_group(manifest, commands),
    )


def query_description(queries: list[str]) -> str:
    """The query tool text, naming every query."""
    return QUERY_BODY.format(queries=", ".join(sorted(queries)))
