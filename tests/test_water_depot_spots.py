"""A ship depot spot is searched in all four orientations, and reports which one fits.

A ship depot occupies two tiles. The finder tested only ``BuildWaterDepot(tile, tile + 1)``,
the eastern neighbour, so every stretch of water running north to south was rejected. Measured
on a 256x256 map with thirteen coastal towns: **one** usable spot in the whole world, and water
mode was unplayable because there was nowhere to build a ship. After searching all four, ten of
fourteen towns had one, with the working orientation a mix of 0 and 1 -- which is to say the
north-south spots that had been invisible were the majority of what was missing.

``depot_direction`` is returned because ``build_water_depot`` takes a direction. A spot without
one leaves the caller guessing, and guessing wrong is a refusal that reads like bad ground.
"""

from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_GS = _ROOT / "ottd_config" / "game" / "nttd-gs" / "main.nut"


def _finder_source() -> str:
    text = _GS.read_text()
    start = text.index("function CmdFindWaterDepotSpots")
    return text[start:text.index("function Cmd", start + 10)]


def test_the_finder_tries_every_orientation() -> None:
    body = _finder_source()
    assert "_GetAdjacentTile(tile, dir)" in body, "the partner tile must be derived per direction"
    assert "dir < 4" in body, "all four neighbours, not just the eastern one"


def test_it_no_longer_hardcodes_the_eastern_neighbour() -> None:
    """The exact expression that caused it, so the regression is named."""
    assert "BuildWaterDepot(tile, tile + 1)" not in _finder_source()


def test_the_working_orientation_is_reported() -> None:
    body = _finder_source()
    assert "depot_direction = found_dir" in body


def test_the_manifest_declares_the_direction_it_returns() -> None:
    """Regenerated from the GameScript, so this fails if the field is ever dropped."""
    manifest = json.loads((_ROOT / "config" / "actions" / "manifest.json").read_text())
    entry = manifest["actions"]["find_water_depot_spots"]
    assert "depot_direction" in (entry.get("returns") or {}).get("fields", [])


def test_the_build_action_still_takes_a_direction_to_pair_with_it() -> None:
    manifest = json.loads((_ROOT / "config" / "actions" / "manifest.json").read_text())
    entry = manifest["actions"]["build_water_depot"]
    assert "direction" in entry["parameters"]
