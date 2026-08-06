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

MANIFEST_VERSION = 1

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
    """Extract one action's parameters, with requiredness and defaults where stated."""
    params: dict[str, dict[str, Any]] = {}

    for name, default in _OPTIONAL.findall(body):
        if name in _NOT_A_PARAMETER:
            continue
        params[name] = {"required": False, "default": _literal(default.strip())}

    for name in _REQUIRED.findall(body):
        if name in _NOT_A_PARAMETER:
            continue
        params[name] = {"required": True}

    for name in set(_MENTIONED_IN.findall(body)) | set(_MENTIONED_DOT.findall(body)):
        if name in _NOT_A_PARAMETER or name in params:
            continue
        # Read without a guard and without a default: the GameScript expects it.
        params[name] = {"required": True}

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
        actions[name] = _entry(name, function, _parameters(body), tiers, categories, written)

    for name, function in _DISPATCH_NO_PARAMS.findall(source):
        actions[name] = _entry(name, function, {}, tiers, categories, written)

    for name in _DISPATCH_INLINE.findall(source):
        actions[name] = _entry(name, None, {}, tiers, categories, written)

    return {
        "manifest_version": MANIFEST_VERSION,
        "generated_from": str(GAMESCRIPT.relative_to(ROOT)),
        "actions": dict(sorted(actions.items())),
    }


def _entry(
    name: str,
    function: str | None,
    params: dict[str, dict[str, Any]],
    tiers: dict[str, str],
    categories: dict[str, str],
    written: dict[str, Any],
) -> dict[str, Any]:
    """One manifest entry, merging any hand-written prose."""
    prose = written.get(name, {})
    entry: dict[str, Any] = {
        "description": prose.get("description", ""),
        "tier": tiers.get(name, "unknown"),
        "category": categories.get(name, "query"),
        "gamescript_function": function or "inline",
        "parameters": {},
    }
    for param, meta in sorted(params.items()):
        described = (prose.get("parameters") or {}).get(param, "")
        entry["parameters"][param] = {"description": described, **meta}
    return entry


def _descriptions() -> dict[str, Any]:
    """Hand-written prose, kept in its own file so regenerating cannot destroy it."""
    if not DESCRIPTIONS.exists():
        return {}
    return json.loads(DESCRIPTIONS.read_text()).get("actions", {})


def main() -> None:
    manifest = build()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(manifest, indent=2) + "\n")

    actions = manifest["actions"]
    undescribed = [name for name, entry in actions.items() if not entry["description"]]
    params_total = sum(len(entry["parameters"]) for entry in actions.values())
    params_undescribed = sum(
        1
        for entry in actions.values()
        for meta in entry["parameters"].values()
        if not meta["description"]
    )

    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    print(f"  actions        : {len(actions)}")
    print(f"  parameters     : {params_total}")
    print(f"  undescribed    : {len(undescribed)} action(s), {params_undescribed} parameter(s)")
    if undescribed:
        print(f"  first few      : {', '.join(undescribed[:5])}")


if __name__ == "__main__":
    main()
