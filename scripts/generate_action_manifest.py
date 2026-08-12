#!/usr/bin/env python3
"""Generate the action manifest skeleton from the GameScript.

    uv run python scripts/generate_action_manifest.py

nttd has no declarative description of its own action surface. ``constants.py`` holds
129 names in categories and nothing else, and ``ActionEnvelope.parameters`` is
``dict[str, Any]`` -- an opaque passthrough. The real contract lives in
``ottd_config/game/nttd-gs/main.nut``, in Squirrel, which nothing else can read.

So the manifest is generated from there rather than hand-listed beside it. A
hand-written copy is the defect this replaces: ``interpreter/validator.py`` covered 14
of 129 actions and had already drifted, declaring ``plant_tree_rectangle`` takes
``x1,y1,x2,y2`` when the GameScript reads ``x, y, width, height`` and refuses anything
else.

**This writes a skeleton, not a finished manifest.** Names, parameters, requiredness and
defaults come out mechanically. Descriptions do not: they are written by hand into
``config/actions/descriptions.json`` and merged here, so regenerating never destroys
them. An action with no description is reported, and the drift test fails until one
exists.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent
GAMESCRIPT = ROOT / "ottd_config" / "game" / "nttd-gs" / "main.nut"
OUTPUT = ROOT / "config" / "actions" / "manifest.json"
DESCRIPTIONS = ROOT / "config" / "actions" / "descriptions.json"
ENUMS = ROOT / "config" / "actions" / "enums.json"

# One file per tier rather than one of everything. The whole surface is about 16k tokens,
# and an agent deciding what to observe should not have to read 76 build actions to do
# it. action_reference.md stays as the index so existing links still resolve.
REFERENCE = ROOT / "docs" / "action_reference.md"
REFERENCE_DIR = ROOT / "docs" / "actions"

MANIFEST_VERSION = 1

# The reference splits on tier before category, because the first thing a reader needs to
# know about an action is whether running it costs anything. Grouping by category alone
# put get_stations next to build_rail_station.
#
# Operator actions get no page. Nobody playing a session can call them, so a reader of
# these pages cannot use one, and their parameter tables cost about 1100 tokens to say
# so. They keep their entries in manifest.json and the GameScript, where the admin routes
# that can call them look them up, and `nttd actions --operator` prints them in full.
# The reference still names them, because "nine superhuman actions exist and are refused"
# is a fairness claim rather than an implementation detail, and a claim that cannot be
# checked is worth less.
_TIER_SECTIONS = [
    (
        "read_only",
        "observations",
        "Observations",
        "Read the world. These cost nothing, change nothing, and can be repeated freely.\n\n"
        "**These are queries, and they are not submitted as actions.** Ask one with "
        "`POST /state/gs/query?action=get_stations`, with the parameters as the whole "
        "body: `{\"industry_id\": 7}`, or `{}` for a query that takes none. The action "
        "name is a QUERY STRING parameter, not a body field, and putting it in the body "
        "returns 422. "
        "Submitting one as an action is refused, because a query endpoint that also "
        "executed actions would be a way around the action allowlist, and that hole was "
        "real: `set_max_loan` once raised a scored company's credit ceiling from 300,000 "
        "to 9,000,000 through it.\n\n"
        "The distinction is worth reading once rather than discovering. An agent that "
        "submitted `get_hangars` as an action spent two of its five actions on it, never "
        "found its hangar, and could then not buy the aircraft it was for.",
    ),
    (
        "participant",
        "actions",
        "Actions",
        "Change the world. These cost money, take effect in the game, and are recorded "
        "against your company.\n\n"
        "**These are submitted as actions**, through `POST /actions/submit` in real-time "
        "play or in a step's batch. Anything on the "
        "[observations page](observations.md) is a query instead, asked a different way.",
    ),
]

# case "name": return this.CmdX(p);   -- takes parameters
# case "name": return this.CmdX();    -- takes none
# case "name": return { ... };        -- answered inline
_DISPATCH_WITH_PARAMS = re.compile(r'case\s+"([a-z_0-9]+)":\s*return\s+this\.(Cmd\w+)\(p\)')
_DISPATCH_NO_PARAMS = re.compile(r'case\s+"([a-z_0-9]+)":\s*return\s+this\.(Cmd\w+)\(\)')
_DISPATCH_INLINE = re.compile(r'case\s+"([a-z_0-9]+)":\s*return\s+\{')

_FUNCTION = re.compile(r'\n  function (Cmd\w+)\(p(?:\s*=\s*\{\})?\)\s*\{')

# local x = ("name" in p) ? p.name : default;
_OPTIONAL = re.compile(r'"([a-z_0-9]+)"\s+in\s+p\)?\s*\?\s*p\.[a-z_0-9]+\s*:\s*([^;,\)]+)')
# if (!("name" in p)) ... error
_REQUIRED = re.compile(r'!\(\s*"([a-z_0-9]+)"\s+in\s+p\s*\)')
# any other mention
_MENTIONED_IN = re.compile(r'"([a-z_0-9]+)"\s+in\s+p')
_MENTIONED_DOT = re.compile(r'\bp\.([a-z_0-9]+)')

# Resolved by a shared helper rather than read directly, so the parameters never appear
# in the function body. Any action calling it accepts a tile index or an x,y pair.
_TILE_HELPERS = {
    "_ResolveTile(p)": ("tile", "x", "y"),
    "_ResolveTilePair(p)": ("from_x", "from_y", "to_x", "to_y", "tile_from", "tile_to"),
}

# What each helper insists on. It accepts a tile index or a coordinate pair and refuses
# the call outright when given neither, so the alternation is part of the contract rather
# than a convenience. Derived from the helper rather than declared per action, because
# every one of the 11 callers has the same requirement.
# What ``_Dispatch`` resolves before ANY handler runs, keyed by the coordinate pair it
# produces. This is a property of the dispatcher, not of a handler, so it applies to
# every action taking that pair whether or not the handler calls a helper.
#
# It used to be keyed on the helper call instead, which under-reported badly: an action
# reading p.x directly got no alternative, so the manifest said x and y were the only way
# in. That is not a documentation nicety. ``interpreter/validator.py`` drives its
# required-parameter check off this manifest and sits on the submit path, so nttd refused
# build_dock(tile=N) with "missing required params: x, y" while the GameScript would have
# resolved it happily. Measured before the fix: build_dock(tile=..) rejected,
# build_road_stop(tile=..) accepted, and the only difference was which one called a helper.
#
# It matters for agents in particular because the find_*_spots family returns
# {tile, x, y}, so tile is the natural thing to hand back.
_DISPATCH_TILE_RESOLUTIONS = {
    ("x", "y"): "tile",
    ("from_x", "from_y"): "tile_from",
    ("to_x", "to_y"): "tile_to",
    ("depot_x", "depot_y"): "depot_tile",
}

# company_id is supplied by nttd from the participant token and overwritten on the way
# in, so it is never a contestant's parameter.
_NOT_A_PARAMETER = {"company_id"}


def _function_bodies(source: str) -> dict[str, str]:
    """Return each Cmd function's body, matched by brace depth."""
    bodies: dict[str, str] = {}
    for match in _FUNCTION.finditer(source):
        name, start = match.group(1), match.end()
        depth, index = 1, start
        while index < len(source) and depth:
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
            index += 1
        bodies[name] = source[start:index]
    return bodies


def _parameters(body: str) -> dict[str, dict[str, Any]]:
    """Extract one action's parameters, with requiredness and defaults where stated.

    Requiredness follows one rule: a parameter is required when the body dereferences
    ``p.name`` and never tests for it. The moment ``"name" in p`` appears anywhere, the
    GameScript has a path that runs without it, so it is optional.

    Testing for a mention and calling it required was the earlier rule, and it was wrong
    wherever the GameScript accepts alternatives. ``CmdInsertOrder`` takes station_id or
    dest_tile or destination; that rule marked all three required, which no caller can
    satisfy. Which alternatives belong together is declared in descriptions.json as
    ``one_of``, because only the call site says so.
    """
    guarded = {n for n in _MENTIONED_IN.findall(body) if n not in _NOT_A_PARAMETER}
    dereferenced = {n for n in _MENTIONED_DOT.findall(body) if n not in _NOT_A_PARAMETER}
    demanded = {n for n in _REQUIRED.findall(body) if n not in _NOT_A_PARAMETER}

    params: dict[str, dict[str, Any]] = {}
    for name in sorted(guarded | dereferenced | demanded):
        params[name] = {"required": name in demanded or name not in guarded}

    for name, default in _OPTIONAL.findall(body):
        if name in _NOT_A_PARAMETER or name in demanded:
            continue
        # A default that tests another parameter is not a default: it is the next branch
        # of an alternation, and recording it produced literal garbage such as
        # `("order_position" in p` in place of a value.
        if '" in p' in default:
            params[name] = {"required": False}
            continue
        params[name] = {"required": False, "default": _literal(default.strip())}

    for call, supplied in _TILE_HELPERS.items():
        if call in body:
            for name in supplied:
                params.setdefault(name, {"required": False, "via": "tile_resolver"})

    return params


def _literal(text: str) -> Any:
    """Turn a Squirrel default into JSON, or keep the source when it is an expression."""
    text = text.strip().rstrip(";")
    if text in ("true", "false"):
        return text == "true"
    if text == "null":
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    if text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    return {"expression": text}


def _tiers() -> dict[str, str]:
    """Map every declared action to its trust tier."""
    sys.path.insert(0, str(ROOT / "src"))
    from nttd.constants import (  # noqa: PLC0415
        ACTION_CATEGORIES,
        OPERATOR_ACTION_CATEGORIES,
        READ_ONLY_GS_ACTIONS,
    )

    tiers: dict[str, str] = {}
    for actions in ACTION_CATEGORIES.values():
        for action in actions:
            tiers[action] = "participant"
    for actions in OPERATOR_ACTION_CATEGORIES.values():
        for action in actions:
            tiers[action] = "operator"
    for action in READ_ONLY_GS_ACTIONS:
        tiers[action] = "read_only"
    return tiers


def _categories() -> dict[str, str]:
    """Map every declared action to its category."""
    sys.path.insert(0, str(ROOT / "src"))
    from nttd.constants import ACTION_CATEGORIES, OPERATOR_ACTION_CATEGORIES  # noqa: PLC0415

    categories: dict[str, str] = {}
    for category, actions in {**ACTION_CATEGORIES, **OPERATOR_ACTION_CATEGORIES}.items():
        for action in actions:
            categories[action] = category
    return categories


def build() -> dict[str, Any]:
    """Read the GameScript and produce the manifest."""
    source = GAMESCRIPT.read_text()
    bodies = _function_bodies(source)
    tiers = _tiers()
    categories = _categories()
    written = _descriptions()

    actions: dict[str, Any] = {}

    for name, function in _DISPATCH_WITH_PARAMS.findall(source):
        body = bodies.get(function, "")
        params = _parameters(body)
        actions[name] = _entry(
            name, function, params, tiers, categories, written, _tile_alternatives(params)
        )

    for name, function in _DISPATCH_NO_PARAMS.findall(source):
        actions[name] = _entry(name, function, {}, tiers, categories, written, [])

    for name in _DISPATCH_INLINE.findall(source):
        actions[name] = _entry(name, None, {}, tiers, categories, written, [])

    return {
        "manifest_version": MANIFEST_VERSION,
        "generated_from": str(GAMESCRIPT.relative_to(ROOT)),
        "enum_values_from": _enum_document().get("openttd_version", "unknown"),
        "actions": dict(sorted(actions.items())),
    }


def _entry(
    name: str,
    function: str | None,
    params: dict[str, dict[str, Any]],
    tiers: dict[str, str],
    categories: dict[str, str],
    written: dict[str, Any],
    derived: list[list[list[str]]],
) -> dict[str, Any]:
    """One manifest entry, merging the hand-written prose with the generated shape."""
    prose = (written.get("actions") or {}).get(name, {})
    # Alternatives: the action needs one branch of each group, so no single member is
    # required on its own. Declared rather than extracted because only the GameScript
    # call site says which parameters substitute for which.
    #
    # A branch can be several parameters together: build_train takes depot_tile, or
    # depot_x and depot_y as a pair. Treating every branch as a single name left depot_y
    # marked required, which no caller supplying depot_tile could satisfy.
    one_of = [
        [_branch(branch) for branch in group] for group in prose.get("one_of", [])
    ] + list(derived)
    alternatives = {param for group in one_of for branch in group for param in branch}
    for param in alternatives & set(params):
        params[param]["required"] = False
    # A tile the dispatcher resolves never appears in the handler body, so it is absent
    # from the extracted parameters and would be advertised in `one_of` while missing
    # from `parameters`. An agent reading the entry would see it offered and undescribed.
    for param in sorted(alternatives - set(params)):
        params[param] = {"required": False}

    entry: dict[str, Any] = {
        "description": prose.get("description", ""),
        "tier": tiers.get(name, "unknown"),
        "category": categories.get(name, "query"),
        "gamescript_function": function or "inline",
        "parameters": {},
    }
    if one_of:
        entry["one_of"] = one_of
    for param, meta in sorted(params.items()):
        entry["parameters"][param] = _parameter(name, param, meta, prose, written)
    return entry


def _tile_alternatives(params: dict[str, dict[str, Any]]) -> list[list[list[str]]]:
    """The alternations the dispatcher's tile resolution imposes on this action.

    Read off the parameter shape rather than the handler body, because ``_Dispatch``
    resolves these for every action before the switch. An action taking x and y accepts
    a tile whether or not its handler ever mentions one.

    Coordinate pairs only. ``x1, y1, x2, y2`` rectangles are untouched: the dispatcher
    resolves no single tile for a rectangle, and inventing one would advertise a call
    the game would refuse.
    """
    groups: list[list[list[str]]] = []
    for pair, single in _DISPATCH_TILE_RESOLUTIONS.items():
        if all(axis in params for axis in pair):
            groups.append([[single], list(pair)])
    return groups


def _branch(branch: str | list[str]) -> list[str]:
    """One arm of an alternation, as a list of parameters that must be supplied together."""
    return [branch] if isinstance(branch, str) else list(branch)


def _parameter(
    action: str,
    param: str,
    meta: dict[str, Any],
    prose: dict[str, Any],
    written: dict[str, Any],
) -> dict[str, Any]:
    """One parameter's published shape: type, prose, and any enum it draws from.

    The prose resolves action-specific override first, then the shared glossary. The
    glossary is what keeps 36 uses of ``x`` saying the same thing; the override is for
    the parameters that genuinely differ, and ``direction`` is why it exists: it selects
    a track orientation for ``build_rail_station`` and an adjacent tile everywhere else.
    """
    glossary = written.get("parameter_glossary") or {}
    override = (prose.get("parameters") or {}).get(param)
    if isinstance(override, str):
        override = {"description": override}
    override = override or {}
    shared = glossary.get(param) or {}

    published: dict[str, Any] = dict(meta)
    published["description"] = override.get("description") or shared.get("description", "")
    published["type"] = override.get("type") or shared.get("type", "")

    values = _enum_for(action, param, written)
    if values:
        published["enum"] = values
    return published


def _enum_for(action: str, param: str, written: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve a parameter's accepted constants, read from the OpenTTD build.

    The binding is hand-written because only the GameScript call site says which enum a
    parameter feeds. The values are not: they come from ``enums.json``, dumped from the
    same build a session runs on, because a wrong constant is worse than a missing one.
    ``OF_UNLOAD`` and ``OF_SERVICE_IF_NEEDED`` are both 4.
    """
    bindings = written.get("enum_bindings") or {}
    binding = bindings.get(f"{action}.{param}") or bindings.get(f"*.{param}")
    if not binding:
        return None

    enums = _enum_document().get("enums", {})
    members = enums.get(binding["class"], {})
    prefix = binding["prefix"]
    values = {
        name: value
        for name, value in members.items()
        if name.startswith(prefix) and not name.endswith("_INVALID")
    }
    if not values:
        return None
    return {"class": binding["class"], "values": dict(sorted(values.items()))}


def problems(manifest: dict[str, Any], written: dict[str, Any]) -> list[str]:
    """Report hand-written entries that no longer match the GameScript.

    The generator merges prose by key and ignores keys that match nothing, which is what
    makes regenerating safe. It also means stale prose rots quietly: a description for a
    deleted action, a glossary entry nobody reads, an enum binding whose class moved. The
    parameter simply loses its values and nothing says so.

    This is the direction the reproducibility test cannot see. Regenerating reproduces the
    same manifest whether or not descriptions.json is full of entries that match nothing.
    """
    actions = manifest["actions"]
    found: list[str] = []

    for name, prose in (written.get("actions") or {}).items():
        entry = actions.get(name)
        if entry is None:
            found.append(
                f"descriptions.json describes '{name}', "
                f"which the GameScript does not dispatch"
            )
            continue
        for param in prose.get("parameters") or {}:
            if param not in entry["parameters"]:
                found.append(
                    f"descriptions.json overrides '{name}.{param}', "
                    f"which that action does not take"
                )
        for group in prose.get("one_of") or []:
            for param in [p for branch in group for p in _branch(branch)]:
                if param not in entry["parameters"]:
                    found.append(
                        f"descriptions.json lists '{name}.{param}' as an alternative, "
                        f"which that action does not take"
                    )

    used = {param for entry in actions.values() for param in entry["parameters"]}
    for param in written.get("parameter_glossary") or {}:
        if param not in used:
            found.append(f"the glossary describes '{param}', which no action takes")

    for key, binding in (written.get("enum_bindings") or {}).items():
        found.extend(_binding_problems(key, binding, actions))

    found.extend(_orphan_problems())
    found.extend(_unadvertised_tile_problems(actions))

    return found


def _unadvertised_tile_problems(actions: dict[str, Any]) -> list[str]:
    """Report an action taking a coordinate pair without offering the tile that resolves it.

    The blind spot this closes cost real behaviour rather than just documentation.
    ``_Dispatch`` resolves tile into x and y for every action, but the alternation used to
    be derived from whether a handler called a tile helper. An action reading p.x directly
    got none, and ``interpreter/validator.py`` drives its required-parameter check off this
    manifest and sits on the submit path, so nttd answered build_dock(tile=N) with
    "missing required params: x, y" for a call the game would have accepted.

    Derived from the parameter shape now, so this should never fire. It exists because the
    previous rule also looked correct.
    """
    return [
        f"'{name}' takes {', '.join(pair)} but does not advertise '{single}', "
        f"which the dispatcher resolves into it"
        for name, entry in sorted(actions.items())
        for pair, single in _DISPATCH_TILE_RESOLUTIONS.items()
        if all(axis in entry["parameters"] for axis in pair)
        and single not in entry["parameters"]
    ]


def _orphan_problems() -> list[str]:
    """Report handlers the dispatch table never reaches.

    The blind spot this closes: the manifest is *derived from* the dispatch table, so a
    handler with no ``case`` is not a mismatch anywhere. It is absent from the manifest,
    absent from the docs, and absent from every parity test, which all agree with each
    other about a function that cannot be called. Four accumulated that way before
    anyone noticed, and one of them was the missing inverse of a remove.

    Deleting a handler is a fine answer and so is dispatching it. Leaving it is not,
    because the surface then depends on which file you read.
    """
    source = GAMESCRIPT.read_text()
    defined = set(_FUNCTION.findall("\n" + source))
    reached = set(re.findall(r"this\.(Cmd\w+)\s*\(", source))
    return [
        f"the GameScript defines '{name}', which no case dispatches: "
        f"delete it or give it a case"
        for name in sorted(defined - reached)
    ]


def _binding_problems(key: str, binding: dict[str, str], actions: dict[str, Any]) -> list[str]:
    """Report an enum binding that matches no parameter or resolves to no values."""
    action_name, _, param = key.rpartition(".")
    if action_name == "*":
        matched = [n for n, e in actions.items() if param in e["parameters"]]
    else:
        matched = [action_name] if param in (actions.get(action_name) or {}).get("parameters", {}) else []

    if not matched:
        return [f"enum_bindings binds '{key}', which matches no action parameter"]

    members = _enum_document().get("enums", {}).get(binding["class"], {})
    if not any(name.startswith(binding["prefix"]) for name in members):
        return [
            f"enum_bindings binds '{key}' to {binding['class']}.{binding['prefix']}*, "
            f"which the OpenTTD dump has no constants for"
        ]
    return []


def _descriptions() -> dict[str, Any]:
    """Hand-written prose, kept in its own file so regenerating cannot destroy it."""
    if not DESCRIPTIONS.exists():
        return {}
    return json.loads(DESCRIPTIONS.read_text())


def _enum_document() -> dict[str, Any]:
    """The constants dumped from the OpenTTD build by ``scripts/dump_gs_enums.py``."""
    if not ENUMS.exists():
        return {}
    return json.loads(ENUMS.read_text())


def _markdown(manifest: dict[str, Any]) -> str:
    """Render the manifest as a reference page.

    Generated rather than written, for the same reason the manifest is: a hand-kept copy
    of this table is the drift defect all of this replaces. Agents that read files rather
    than call endpoints get the same content the validator enforces.
    """
    actions = manifest["actions"]
    counts: dict[str, int] = {}
    for entry in actions.values():
        counts[entry["tier"]] = counts.get(entry["tier"], 0) + 1

    lines = [
        "# Action reference",
        "",
        "Every action nttd can run, what it takes, and what the values mean.",
        "",
        "**Generated. Do not edit.** Run `uv run python scripts/generate_action_manifest.py`.",
        "The shape comes from `ottd_config/game/nttd-gs/main.nut`, the prose from",
        "`config/actions/descriptions.json`, and the enum values from the OpenTTD build",
        f"itself (`{manifest['enum_values_from']}`) via `scripts/dump_gs_enums.py`.",
        "",
        "The same content is served at `/v1/public/actions`, offered to MCP clients, and",
        "printed by `nttd actions`.",
        "",
        "Split by what running it does to the game, because that is the first thing worth",
        "knowing and because reading all of it at once is rarely what you want.",
        "",
        "Start with **[the index](actions/index.md)**: every action on one line with its",
        "call shape. Choosing one costs about 3k tokens there rather than the 16k of",
        "reading the detail pages below.",
        "",
        "| Reference | Count | What it is |",
        "| --- | --- | --- |",
        f"| [Observations](actions/observations.md) | {counts['read_only']} "
        "| Read the world. Changes nothing. Asked with `POST /state/gs/query`, never "
        "submitted as an action. |",
        f"| [Actions](actions/actions.md) | {counts['participant']} "
        "| Change the world. This is play. |",
        "",
        "One caveat worth stating plainly: `get_cargo_flows` is filed as an observation",
        "but is not free of consequence. Reading it resets the cargo monitors, so a",
        "second read reports only what moved since the first. Every other observation can",
        "be repeated without changing anything.",
        "",
        "## Where a value comes from",
        "",
        "Rail types, road types, cargo types, bridge types and airport types are numbered",
        "by the running game, not fixed by nttd. Ask for them rather than assuming:",
        "`get_rail_types`, `get_road_types`, `get_cargo_types`, `get_bridge_types`,",
        "`get_airport_types`.",
        "",
        "Where a parameter takes a named constant instead, the accepted values are listed",
        "with it. Those are read from the OpenTTD build rather than written by hand,",
        "because a wrong constant is worse than a missing one: `OF_UNLOAD` and",
        "`OF_SERVICE_IF_NEEDED` are both 4.",
        "",
        "`company_id` is never a parameter. nttd takes it from the participant token and",
        "overwrites whatever was sent, so an action always runs as the company that",
        "submitted it.",
        "",
    ]
    lines += _markdown_operator_note(actions, counts["operator"])
    return "\n".join(lines) + "\n"


def _markdown_operator_note(actions: dict[str, Any], count: int) -> list[str]:
    """Name the operator actions without documenting how to call them.

    Nobody playing a session can call one, so parameter tables for them are noise in a
    reference an agent reads. They are still named, because nttd's claim is that these
    exist and are refused, and a claim nobody can check is worth less than one they can.
    """
    operators = sorted(name for name, entry in actions.items() if entry["tier"] == "operator")
    lines = [
        "## The actions nobody can play",
        "",
        f"{count} actions have no human equivalent: no amount of skill at OpenTTD lets a",
        "person found a town or set their own bank balance. They exist because building a",
        "scenario needs them, they are reachable only through the operator routes, and a",
        "scored session refuses them.",
        "",
    ]
    for name in operators:
        summary = actions[name]["description"].split(". ")[0].rstrip(".")
        summary = summary.replace(" Operator-tier", "").rstrip(":").rstrip()
        lines.append(f"- `{name}` {summary}.")
    lines += [
        "",
        "Their parameters are in `config/actions/manifest.json` and printed by",
        "`nttd actions --operator`, which is where an operator setting up a scenario",
        "would look. They are deliberately absent from the two pages above: a reader of",
        "those cannot call one, and saying so at length would cost more than it tells.",
        "",
    ]
    return lines


def _markdown_index_page(manifest: dict[str, Any]) -> str:
    """Every action as one line: signature and what it does.

    The detail pages are the wrong thing to read when the question is "which action do I
    want". actions.md is about 11k tokens, and answering that question should not cost
    that. This is the whole surface at roughly a fifth of the size, with a pointer to the
    section that has the parameters and accepted values.
    """
    actions = manifest["actions"]
    lines = [
        "# Every action, one line each",
        "",
        "The whole surface at a glance, for choosing what to call. For a parameter's type,",
        "default, and the constants it accepts, follow the link or run",
        "`nttd actions <name>`.",
        "",
        "**Generated. Do not edit.** Run `uv run python scripts/generate_action_manifest.py`.",
        "",
        "Signatures read: required parameters first, then a choice as `a|b`, then optional",
        "ones in brackets. So `remove_order(vehicle_id, order_index|order_position)` needs",
        "the vehicle and one of the two positions.",
        "",
    ]
    for tier, filename, title, _ in _TIER_SECTIONS:
        entries = {n: e for n, e in actions.items() if e["tier"] == tier}
        if not entries:
            continue
        lines += [
            f"## {title}",
            "",
            f"Full detail in [{filename}.md]({filename}.md).",
            "",
        ]
        for name, entry in sorted(entries.items()):
            summary = entry["description"].split(". ")[0].rstrip(".")
            lines.append(f"- `{_signature(name, entry)}` {summary}.")
        lines.append("")
    return "\n".join(lines) + "\n"


def _markdown_section(
    manifest: dict[str, Any], tier: str, title: str, blurb: str
) -> str:
    """One tier's reference, grouped by category."""
    entries = {
        name: entry
        for name, entry in manifest["actions"].items()
        if entry["tier"] == tier
    }
    by_category: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for name, entry in entries.items():
        by_category.setdefault(entry["category"], []).append((name, entry))

    lines = [
        f"# {title}",
        "",
        blurb,
        "",
        "**Generated. Do not edit.** Run `uv run python scripts/generate_action_manifest.py`.",
        f"Part of the [action reference](../action_reference.md). {len(entries)} of "
        f"{len(manifest['actions'])} actions.",
        "",
        "## Contents",
        "",
    ]
    for category in sorted(by_category):
        names = ", ".join(f"`{name}`" for name, _ in sorted(by_category[category]))
        lines.append(f"- **{category}**: {names}")
    lines += ["", "Every action on one line, across all three pages: [index.md](index.md).", ""]

    for category in sorted(by_category):
        lines += [f"## {category}", ""]
        for name, entry in sorted(by_category[category]):
            lines += _markdown_action(name, entry)
    return "\n".join(lines) + "\n"


def _markdown_action(name: str, entry: dict[str, Any]) -> list[str]:
    """One action's section, nested under its category."""
    lines = [f"### `{name}`", ""]
    lines += [entry["description"] or "_No description yet._", ""]

    for group in entry.get("one_of", []):
        supply = " or ".join(
            " and ".join(f"`{param}`" for param in branch) for branch in group
        )
        lines += [f"Supply one of: {supply}.", ""]

    if not entry["parameters"]:
        lines += ["Takes no parameters.", ""]
        return lines

    # A list rather than a table. 93 of the 129 actions take three parameters or fewer,
    # and a table spends two lines of scaffolding before saying anything: about 2400
    # tokens across the reference, for punctuation.
    for param, meta in entry["parameters"].items():
        lines.append(f"- `{param}` ({_markdown_facts(meta)}) {meta.get('description') or ''}")
    lines.append("")

    for param, meta in entry["parameters"].items():
        if "enum" not in meta:
            continue
        values = ", ".join(f"`{n}` = {v}" for n, v in meta["enum"]["values"].items())
        lines += [f"`{param}` accepts ({meta['enum']['class']}): {values}", ""]
    return lines


def _markdown_facts(meta: dict[str, Any]) -> str:
    """Type, requiredness and default, compressed into one parenthesis."""
    facts = [meta.get("type") or "value"]
    if meta.get("required"):
        facts.append("required")
    elif "default" in meta:
        default = meta["default"]
        rendered = (
            default.get("expression", "") if isinstance(default, dict) else json.dumps(default)
        )
        facts.append(f"default {rendered}")
    else:
        facts.append("optional")
    return ", ".join(facts)


def _signature(name: str, entry: dict[str, Any]) -> str:
    """A one-line call shape, for choosing an action without reading its section.

    Required parameters first, then each choice as ``a|b``, then the optional ones in
    brackets. This is what makes the index usable: an agent picking between
    build_road_stop and build_rail_station can see the difference without either
    section.
    """
    grouped = {p for group in entry.get("one_of", []) for branch in group for p in branch}
    required = [p for p, m in entry["parameters"].items() if m.get("required")]
    optional = sorted(
        p for p, m in entry["parameters"].items() if not m.get("required") and p not in grouped
    )

    parts = sorted(required)
    for group in entry.get("one_of", []):
        parts.append("|".join(",".join(branch) for branch in group))
    if optional:
        parts.append(f"[{', '.join(optional)}]")
    return f"{name}({', '.join(parts)})"


def main() -> None:
    manifest = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(manifest, indent=2) + "\n")
    REFERENCE.parent.mkdir(parents=True, exist_ok=True)
    REFERENCE.write_text(_markdown(manifest))
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    (REFERENCE_DIR / "index.md").write_text(_markdown_index_page(manifest))
    for tier, filename, title, blurb in _TIER_SECTIONS:
        path = REFERENCE_DIR / f"{filename}.md"
        path.write_text(_markdown_section(manifest, tier, title, blurb))

    actions = manifest["actions"]
    undescribed = [name for name, entry in actions.items() if not entry["description"]]
    params_total = sum(len(entry["parameters"]) for entry in actions.values())
    params_undescribed = sum(
        1
        for entry in actions.values()
        for meta in entry["parameters"].values()
        if not meta["description"]
    )

    stale = problems(manifest, _descriptions())
    if stale:
        print("Hand-written entries that match nothing in the GameScript:", file=sys.stderr)
        for problem in stale:
            print(f"  {problem}", file=sys.stderr)
        raise SystemExit(1)

    print(f"Wrote {OUTPUT.relative_to(ROOT)} and {REFERENCE.relative_to(ROOT)}")
    print(f"  actions        : {len(actions)}")
    print(f"  parameters     : {params_total}")
    print(f"  undescribed    : {len(undescribed)} action(s), {params_undescribed} parameter(s)")
    if undescribed:
        print(f"  first few      : {', '.join(undescribed[:5])}")


if __name__ == "__main__":
    main()
