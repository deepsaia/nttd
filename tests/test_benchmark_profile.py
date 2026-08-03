"""Tests for the benchmark profile: which world settings a scored run may choose.

OpenTTD's generation knobs are wide enough that two scored runs can face worlds
with nothing in common, which produces a table of unrelated anecdotes rather than a
leaderboard. The profile locks the settings whose effect is invisible to a reader of
the board and lets through the ones recorded as columns.

Run with: uv run pytest tests/test_benchmark_profile.py -v
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from nttd.config.benchmark_profile import (
    LOCKED_SETTINGS,
    VARIABLE_SETTINGS,
    deviations,
)
from nttd.config.scenario_config import (
    ScenarioConfigError,
    load,
    scenario_to_settings,
)

_BENCHMARK_DIR = Path(__file__).parent.parent / "config" / "benchmark"
_TIERS = ("t1", "t2", "t3", "t4")


def _get(cfg: Any, path: str, default: Any = None) -> Any:
    """Minimal dot-path reader, matching what scenario_config passes in."""
    node = cfg
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


# ---------------------------------------------------------------------------
# The locked/variable split
# ---------------------------------------------------------------------------


def test_locked_and_variable_settings_do_not_overlap() -> None:
    """A setting cannot be both fixed and free."""
    assert not (set(LOCKED_SETTINGS) & VARIABLE_SETTINGS)


def test_water_border_flags_are_not_in_the_profile() -> None:
    """OpenTTD ignores them unless map_edges = manual, which the profile locks.

    Listing them would imply they take effect.
    """
    for direction in ("ne", "se", "sw", "nw"):
        assert f"water_borders_{direction}" not in LOCKED_SETTINGS
        assert f"water_borders_{direction}" not in VARIABLE_SETTINGS


def test_the_user_specified_settings_are_all_locked() -> None:
    """Guards the profile against silent narrowing.

    These are the settings the benchmark was defined to fix, so a later edit that
    drops one should fail here rather than quietly widen what a scored run may do.
    """
    assert LOCKED_SETTINGS == {
        "variety": "none",
        "smoothness": "smooth",
        "rivers": "medium",
        "sea_level": "medium",
        "map_edges": "random",
        "starting_year": 2020,
        "town_names": "english",
        "number_towns": "normal",
        "industry_density": "normal",
    }


def test_size_landscape_and_terrain_may_vary() -> None:
    """The axes a player most wants to choose, and each is a leaderboard column."""
    assert VARIABLE_SETTINGS == {"size_x", "size_y", "landscape", "terrain_type"}


# ---------------------------------------------------------------------------
# deviations()
# ---------------------------------------------------------------------------


def test_a_conforming_map_has_no_deviations() -> None:
    assert deviations(dict(LOCKED_SETTINGS), _get) == []


def test_an_omitted_setting_inherits_the_profile() -> None:
    """Silence is conformance, which is what makes the shared defaults file useful.

    A scored scenario that includes benchmark/defaults.conf and adds nothing must
    pass, and one that omits a key entirely must not be refused for the omission.
    """
    assert deviations({}, _get) == []


def test_every_deviation_is_reported_not_just_the_first() -> None:
    """An author should be able to fix a config in one pass."""
    problems = deviations(
        {"variety": "high", "number_towns": "high", "starting_year": 1960}, _get,
    )
    assert len(problems) == 3


def test_a_deviation_names_the_key_and_the_required_value() -> None:
    problems = deviations({"industry_density": "high"}, _get)
    assert "map.industry_density" in problems[0]
    assert "'high'" in problems[0]
    assert "'normal'" in problems[0]


def test_starting_year_compares_numerically() -> None:
    """HOCON may hand back a string or an int, and 2020 == '2020' should hold."""
    assert deviations({"starting_year": "2020"}, _get) == []
    assert deviations({"starting_year": 2020}, _get) == []
    assert len(deviations({"starting_year": 1960}, _get)) == 1


def test_a_non_numeric_starting_year_is_a_deviation_not_a_crash() -> None:
    problems = deviations({"starting_year": "nineteen sixty"}, _get)
    assert len(problems) == 1


# ---------------------------------------------------------------------------
# Enforcement through scenario validation
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, scored: bool, **overrides: Any) -> Path:
    """Write a minimal scenario, conforming except for the given overrides."""
    map_values: dict[str, Any] = {
        **LOCKED_SETTINGS,
        "size_x": 256, "size_y": 256,
        "landscape": "temperate", "terrain_type": "flat",
        "seed": 1001,
    }
    map_values.update(overrides)
    lines = [
        "scenario {", '  name = "probe"', f"  scored = {str(scored).lower()}", "  map {",
    ]
    for key, value in map_values.items():
        rendered = value if isinstance(value, int) else f'"{value}"'
        lines.append(f"    {key} = {rendered}")
    lines += ["  }", "}"]
    path = tmp_path / "probe.conf"
    path.write_text("\n".join(lines) + "\n")
    return path


def test_a_scored_scenario_that_deviates_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, scored=True, number_towns="high")
    with pytest.raises(ScenarioConfigError, match="number_towns"):
        scenario_to_settings(load(path), strict=True)


def test_free_play_may_set_anything(tmp_path: Path) -> None:
    """Scenario authoring and debugging have no comparability to protect."""
    path = _write(
        tmp_path, scored=False,
        number_towns="high", industry_density="high", starting_year=1960,
        variety="very_high", town_names="german",
    )
    settings = scenario_to_settings(load(path), strict=True)
    assert settings["difficulty.number_towns"] == "3"
    assert settings["game_creation.starting_year"] == "1960"


def test_a_scored_scenario_may_still_vary_size_and_terrain(tmp_path: Path) -> None:
    path = _write(
        tmp_path, scored=True, size_x=512, size_y=512, terrain_type="mountainous",
    )
    settings = scenario_to_settings(load(path), strict=True)
    assert settings["game_creation.map_x"] == "9"
    assert settings["difficulty.terrain_type"] == "3"


def test_the_lenient_path_warns_rather_than_refusing(tmp_path: Path) -> None:
    """nttd session create only warns, so a deviating scored config still runs.

    That is deliberate for the interactive path, but it means the strict path is
    the one a benchmark must use.
    """
    path = _write(tmp_path, scored=True, number_towns="high")
    settings = scenario_to_settings(load(path), strict=False)
    assert settings["difficulty.number_towns"] == "3"


# ---------------------------------------------------------------------------
# What reaches the result record
# ---------------------------------------------------------------------------


def test_a_scored_run_records_the_profile_version(tmp_path: Path) -> None:
    """Two runs under different profiles are not comparable, so the record says."""
    settings = scenario_to_settings(load(_write(tmp_path, scored=True)), strict=True)
    assert settings["_profile_version"] == "1"


def test_free_play_records_no_profile_version(tmp_path: Path) -> None:
    settings = scenario_to_settings(load(_write(tmp_path, scored=False)), strict=True)
    assert "_profile_version" not in settings


def test_the_variable_dimensions_are_emitted_for_the_leaderboard(
    tmp_path: Path,
) -> None:
    """They are permitted to differ precisely because they are disclosed."""
    path = _write(tmp_path, scored=True, size_x=512, terrain_type="hilly")
    settings = scenario_to_settings(load(path), strict=True)
    assert settings["_map_size_x"] == "512"
    assert settings["_map_terrain_type"] == "hilly"
    assert settings["_map_landscape"] == "temperate"


def test_locked_settings_are_not_emitted_as_map_columns(tmp_path: Path) -> None:
    """They are constant across every scored run, so a column would say nothing."""
    settings = scenario_to_settings(load(_write(tmp_path, scored=True)), strict=True)
    assert "_map_number_towns" not in settings
    assert "_map_starting_year" not in settings


# ---------------------------------------------------------------------------
# The shipped tier scenarios
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tier", _TIERS)
def test_shipped_tier_configs_pass_strict_validation(tier: str) -> None:
    settings = scenario_to_settings(load(_BENCHMARK_DIR / f"{tier}.conf"), strict=True)
    assert settings["_scored"] == "1"
    assert settings["_map_seed"] == "1001", "reproducibility requires a pinned seed"


@pytest.mark.parametrize(
    ("tier", "wall_minutes"),
    [("t1", 15.0), ("t2", 30.0), ("t3", 60.0), ("t4", 120.0)],
)
def test_tiers_differ_only_in_time(tier: str, wall_minutes: float) -> None:
    """A tier fixes the horizon, not the world."""
    settings = scenario_to_settings(load(_BENCHMARK_DIR / f"{tier}.conf"), strict=True)
    assert settings["_ec_wall_minutes"] == str(wall_minutes)


def test_every_tier_generates_the_same_world() -> None:
    """Otherwise a tier would be two changes at once, and scores across tiers
    would not be attributable to the horizon alone."""
    worlds = []
    for tier in _TIERS:
        settings = scenario_to_settings(load(_BENCHMARK_DIR / f"{tier}.conf"), strict=True)
        worlds.append({
            key: value for key, value in settings.items()
            if key.startswith(("game_creation.", "difficulty.", "_map_"))
        })
    assert all(world == worlds[0] for world in worlds)


def test_the_defaults_file_covers_every_locked_setting() -> None:
    """An author who includes it must inherit conformance, not partial conformance."""
    text = (_BENCHMARK_DIR / "defaults.conf").read_text()
    for key in LOCKED_SETTINGS:
        assert f"{key} =" in text, f"benchmark/defaults.conf does not set {key}"


def test_the_defaults_file_sets_nothing_variable() -> None:
    """Pinning a variable dimension there would remove a choice the profile allows."""
    for line in (_BENCHMARK_DIR / "defaults.conf").read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key = stripped.split("=")[0].strip()
        assert key not in VARIABLE_SETTINGS, f"{key} may vary; do not fix it in defaults"
