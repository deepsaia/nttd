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
_TIER_SECTIONS = [
    (
        "read_only",
        "observations",
        "Observations",
        "Read the world. These cost nothing, change nothing, and can be repeated freely.",
    ),
    (
        "participant",
        "actions",
        "Actions",
        "Change the world. These cost money, take effect in the game, and are recorded "
        "against your company.",
    ),
    (
        "operator",
        "operator",
        "Operator",
        "Scenario setup rather than play. Refused during a scored game, and listed here "
        "so it is clear they exist and why they are unavailable.",
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
_TILE_HELPER_ALTERNATIVES = {
    "_ResolveTile(p)": [[["tile"], ["x", "y"]]],
    "_ResolveTilePair(p)": [
        [["tile_from"], ["from_x", "from_y"]],
        [["tile_to"], ["to_x", "to_y"]],
    ],
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
        actions[name] = _entry(
            name, function, _parameters(body), tiers, categories, written, _tile_alternatives(body)
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


def _tile_alternatives(body: str) -> list[list[list[str]]]:
    """The alternations a shared tile helper imposes on whichever action calls it."""
    groups: list[list[list[str]]] = []
    for call, alternatives in _TILE_HELPER_ALTERNATIVES.items():
        if call in body:
            groups.extend(alternatives)
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
    counts = {tier: 0 for tier, _, _, _ in _TIER_SECTIONS}
    for entry in actions.values():
        if entry["tier"] in counts:
            counts[entry["tier"]] += 1

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
        "| Reference | Count | What it is |",
        "| --- | --- | --- |",
        f"| [Observations](actions/observations.md) | {counts['read_only']} "
        "| Read the world. Changes nothing. |",
        f"| [Actions](actions/actions.md) | {counts['participant']} "
        "| Change the world. This is play. |",
        f"| [Operator](actions/operator.md) | {counts['operator']} "
        "| Scenario setup. Refused during scored play. |",
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
    lines.append("")

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

    lines += [
        "| Parameter | Type | Required | Default | Description |",
        "| --- | --- | --- | --- | --- |",
    ]
    for param, meta in entry["parameters"].items():
        lines.append(
            f"| `{param}` | {meta.get('type') or ''} | "
            f"{'yes' if meta.get('required') else 'no'} | "
            f"{_markdown_default(meta)} | {meta.get('description') or ''} |"
        )
    lines.append("")

    for param, meta in entry["parameters"].items():
        if "enum" not in meta:
            continue
        values = ", ".join(f"`{n}` = {v}" for n, v in meta["enum"]["values"].items())
        lines += [f"`{param}` accepts ({meta['enum']['class']}): {values}", ""]
    return lines


def _markdown_default(meta: dict[str, Any]) -> str:
    """How a default renders in the table."""
    if meta.get("via") == "tile_resolver":
        return "_tile or x,y_"
    if "default" not in meta:
        return ""
    default = meta["default"]
    if isinstance(default, dict):
        return f"`{default.get('expression', '')}`"
    return f"`{json.dumps(default)}`"


def main() -> None:
    manifest = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(manifest, indent=2) + "\n")
    REFERENCE.parent.mkdir(parents=True, exist_ok=True)
    REFERENCE.write_text(_markdown(manifest))
    REFERENCE_DIR.mkdir(parents=True, exist_ok=True)
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

    print(f"Wrote {OUTPUT.relative_to(ROOT)} and {REFERENCE.relative_to(ROOT)}")
    print(f"  actions        : {len(actions)}")
    print(f"  parameters     : {params_total}")
    print(f"  undescribed    : {len(undescribed)} action(s), {params_undescribed} parameter(s)")
    if undescribed:
        print(f"  first few      : {', '.join(undescribed[:5])}")


if __name__ == "__main__":
    main()
