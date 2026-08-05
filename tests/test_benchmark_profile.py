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
    ALLOWED_RANGES,
    DIMENSION_PREFIX,
    LOCKED_SETTINGS,
    PROFILE_VERSION,
    VARIABLE_SETTINGS,
    active_profile,
    deviations,
    load_profile,
)
from nttd.config.scenario_config import (
    ScenarioConfigError,
    load,
    scenario_to_settings,
)

_BENCHMARK_DIR = Path(__file__).parent.parent / "config" / "benchmark"
_EXAMPLES = ("t2_example", "t3_subarctic_example")


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
# Allowed ranges on the settings that may vary
# ---------------------------------------------------------------------------


def test_ranges_cover_exactly_the_variable_settings() -> None:
    """A dimension that may vary but has no range would be unbounded."""
    assert set(ALLOWED_RANGES) == set(VARIABLE_SETTINGS)


def test_map_sizes_are_powers_of_two_within_openttd_limits() -> None:
    """A non-power-of-two would be refused by OpenTTD at generation, so the profile
    must not offer one as a legal choice."""
    for axis in ("size_x", "size_y"):
        for size in ALLOWED_RANGES[axis]:
            assert 64 <= int(size) <= 4096
            assert int(size) & (int(size) - 1) == 0


def test_the_largest_openttd_sizes_are_excluded() -> None:
    """Observation is always the full entitled state, so 2048x2048 is a payload
    problem (16x the tiles of 1024x1024) rather than a transport one."""
    assert 2048 not in ALLOWED_RANGES["size_x"]
    assert 4096 not in ALLOWED_RANGES["size_x"]


def test_custom_terrain_is_not_an_allowed_value() -> None:
    """The hole this enumeration closes.

    terrain_type = "custom" unlocks custom_terrain_height over 1..255, an unbounded
    world axis that no leaderboard column discloses -- so a 240-height world and a
    flat one would produce rows reading identically.
    """
    assert "custom" not in ALLOWED_RANGES["terrain_type"]


def test_a_value_outside_its_range_is_a_deviation() -> None:
    assert len(deviations({"size_x": 2048}, _get)) == 1
    assert len(deviations({"landscape": "martian"}, _get)) == 1
    assert len(deviations({"terrain_type": "custom"}, _get)) == 1


def test_a_ranged_deviation_lists_the_permitted_values() -> None:
    """An author should not have to read source to find out what is allowed."""
    problem = deviations({"terrain_type": "custom"}, _get)[0]
    assert "map.terrain_type" in problem
    assert "mountainous" in problem


def test_every_in_range_value_is_accepted() -> None:
    for key, allowed in ALLOWED_RANGES.items():
        for value in allowed:
            assert deviations({key: value}, _get) == [], f"{key}={value} refused"


def test_a_numeric_size_may_be_written_as_a_string() -> None:
    """HOCON hands back an int or a str depending on quoting, and both are
    reasonable to write."""
    assert deviations({"size_x": "512"}, _get) == []


def test_an_omitted_ranged_setting_is_not_a_deviation() -> None:
    """scenario_to_settings supplies OpenTTD's own default, which is in range."""
    assert deviations({}, _get) == []


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
    # Derived from the rules rather than hand-written, so it cannot be forgotten when
    # they change. Its value is a digest; what matters is that it is present and
    # tracks the active profile.
    assert settings["_profile_version"] == active_profile().version
    assert len(settings["_profile_version"]) == 12


def test_free_play_records_no_profile_version(tmp_path: Path) -> None:
    settings = scenario_to_settings(load(_write(tmp_path, scored=False)), strict=True)
    assert "_profile_version" not in settings


def test_the_variable_dimensions_are_emitted_for_the_leaderboard(
    tmp_path: Path,
) -> None:
    """They are permitted to differ precisely because they are disclosed."""
    path = _write(tmp_path, scored=True, size_x=512, terrain_type="hilly")
    settings = scenario_to_settings(load(path), strict=True)
    assert settings["_dim_size_x"] == "512"
    assert settings["_dim_terrain_type"] == "hilly"
    assert settings["_dim_landscape"] == "temperate"


def test_locked_settings_are_not_emitted_as_map_columns(tmp_path: Path) -> None:
    """They are constant across every scored run, so a column would say nothing."""
    settings = scenario_to_settings(load(_write(tmp_path, scored=True)), strict=True)
    assert "_dim_number_towns" not in settings
    assert "_dim_starting_year" not in settings


# ---------------------------------------------------------------------------
# The shipped example scenarios
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("example", _EXAMPLES)
def test_shipped_examples_pass_strict_validation(example: str) -> None:
    settings = scenario_to_settings(load(_BENCHMARK_DIR / f"{example}.conf"), strict=True)
    assert settings["_scored"] == "1"
    assert settings["_map_seed"], "reproducibility requires a pinned seed"


def test_the_examples_differ_on_the_free_dimensions() -> None:
    """The second example exists to show varying them is legal and disclosed.

    If both examples described the same world, nothing would demonstrate that a
    contestant may choose, which is the point the ranges are documented for.
    """
    worlds = []
    for example in _EXAMPLES:
        settings = scenario_to_settings(
            load(_BENCHMARK_DIR / f"{example}.conf"), strict=True,
        )
        worlds.append({
            key: value for key, value in settings.items()
            if key.startswith(DIMENSION_PREFIX)
        })
    assert worlds[0] != worlds[1]


def test_the_examples_agree_on_every_locked_setting() -> None:
    """Different worlds, same rules. This is what makes them both benchmark runs."""
    locked_emissions = []
    for example in _EXAMPLES:
        settings = scenario_to_settings(
            load(_BENCHMARK_DIR / f"{example}.conf"), strict=True,
        )
        locked_emissions.append({
            "year": settings["game_creation.starting_year"],
            "towns": settings["difficulty.number_towns"],
            "industry": settings["difficulty.industry_density"],
            "variety": settings["game_creation.variety"],
            "smoothness": settings["game_creation.tgen_smoothness"],
            "rivers": settings["game_creation.amount_of_rivers"],
            "sea": settings["difficulty.quantity_sea_lakes"],
            "borders": settings["game_creation.water_borders"],
            "names": settings["game_creation.town_name"],
        })
    assert locked_emissions[0] == locked_emissions[1]


def test_the_profile_is_the_only_copy_of_the_locked_values() -> None:
    """There was a second copy, config/benchmark/defaults.conf, which scenarios
    included. It was byte-identical to the locked block and kept in sync only by a
    test, so it was deleted: omitting a locked key now inherits the profile, and
    scenario_to_settings emits the profile's value.
    """
    assert not (_BENCHMARK_DIR / "defaults.conf").exists(), (
        "a second copy of the locked values is back; the profile is the authority"
    )


def test_an_example_scenario_restates_no_locked_value() -> None:
    """An example that restated them would teach authors to duplicate the rules."""
    for example in _EXAMPLES:
        text = (_BENCHMARK_DIR / f"{example}.conf").read_text()
        body = "\n".join(
            line for line in text.splitlines() if not line.strip().startswith("#")
        )
        for key in LOCKED_SETTINGS:
            assert f"{key} " not in body and f"{key}=" not in body, (
                f"{example}.conf sets locked value {key}; remove it to inherit"
            )


def test_the_example_documents_every_allowed_range() -> None:
    """The example is the only place a contestant learns the ranges, so a range
    added in code without a matching comment leaves them guessing."""
    text = (_BENCHMARK_DIR / "t2_example.conf").read_text()
    for key, allowed in ALLOWED_RANGES.items():
        for value in allowed:
            assert str(value) in text, f"{key} value {value} is not documented"


# ---------------------------------------------------------------------------
# The profile is data, editable by hand
# ---------------------------------------------------------------------------
# Which worlds a leaderboard admits is operator policy: it changes without any
# behaviour changing, so it must be a reviewable file rather than a Python literal.


def test_the_active_profile_comes_from_the_shipped_file() -> None:
    """If this reads "built-in fallback", hand edits to profile.conf do nothing."""
    profile = active_profile()
    assert profile.source.endswith("config/benchmark/profile.conf"), (
        f"profile loaded from {profile.source!r}, so editing profile.conf would "
        f"have no effect"
    )


def test_the_fallback_matches_the_shipped_file() -> None:
    """The fallback only exists for a broken or missing file. If it disagrees with
    the shipped rules, a file problem would silently change what is scoreable."""
    from nttd.config.benchmark_profile import _FALLBACK_ALLOWED, _FALLBACK_LOCKED

    shipped = load_profile(_BENCHMARK_DIR / "profile.conf")
    assert shipped.locked == _FALLBACK_LOCKED
    assert shipped.allowed == _FALLBACK_ALLOWED


def test_narrowing_a_range_by_hand_refuses_a_previously_valid_world(
    tmp_path: Path,
) -> None:
    """The operator lever: restrict the board without touching code."""
    narrowed = tmp_path / "profile.conf"
    narrowed.write_text(
        "profile {\n"
        "  locked {\n" + "".join(
            f"    {key} = " + (str(value) if isinstance(value, int) else f'"{value}"') + "\n"
            for key, value in LOCKED_SETTINGS.items()
        ) + "  }\n"
        "  allowed {\n"
        "    size_x = [256]\n    size_y = [256]\n"
        '    landscape = ["temperate"]\n    terrain_type = ["flat"]\n'
        "  }\n  scenario_allowlist = []\n}\n"
    )
    profile = load_profile(narrowed)
    assert profile.version != active_profile().version, (
        "narrowing the rules must change the recorded version"
    )

    # 512x512 sub-arctic hilly was admitted by the shipped profile.
    problems = profile.deviations(
        {"size_x": 512, "size_y": 512, "landscape": "sub-arctic", "terrain_type": "hilly"},
        _get,
    )
    assert len(problems) == 4
    assert profile.deviations(
        {"size_x": 256, "size_y": 256, "landscape": "temperate", "terrain_type": "flat"},
        _get,
    ) == []


def test_an_empty_allowlist_admits_any_conforming_scenario() -> None:
    """The default posture: conformance is the credential."""
    profile = active_profile()
    assert profile.scenario_allowlist == ()
    assert profile.deviations({}, _get, "anything-at-all") == []


def test_an_allowlist_restricts_scoring_to_a_fixed_slate(tmp_path: Path) -> None:
    """For a seasonal competition or a freeze, where the board needs a known slate."""
    path = tmp_path / "profile.conf"
    path.write_text(
        'profile {\n  locked { variety = "none" }\n'
        '  allowed { landscape = ["temperate"] }\n'
        '  scenario_allowlist = ["benchmark-t2-example"]\n}\n'
    )
    profile = load_profile(path)

    assert profile.deviations({}, _get, "benchmark-t2-example") == []
    refused = profile.deviations({}, _get, "my-own-variant")
    assert len(refused) == 1
    assert "not on the scored allowlist" in refused[0]
    assert "benchmark-t2-example" in refused[0], "must say what IS admitted"


def test_a_missing_profile_falls_back_rather_than_admitting_everything(
    tmp_path: Path,
) -> None:
    """Refusing every scored run over a missing policy file would be a worse
    failure, but so would admitting every world. Fall back to the known rules."""
    profile = load_profile(tmp_path / "absent.conf")
    assert profile.source == "built-in fallback"
    assert profile.locked
    assert profile.deviations({"terrain_type": "custom"}, _get) != []


def test_an_unparseable_profile_falls_back(tmp_path: Path) -> None:
    path = tmp_path / "profile.conf"
    path.write_text("profile { locked { {{{ not = = hocon }\n")
    profile = load_profile(path)
    assert profile.source == "built-in fallback"
    assert profile.locked == LOCKED_SETTINGS


def test_a_profile_with_no_rules_falls_back(tmp_path: Path) -> None:
    """An empty locked/allowed pair would admit every world, which is never the
    intent of editing the file -- far likelier a truncation or a bad merge."""
    path = tmp_path / "profile.conf"
    path.write_text("profile {\n  locked {}\n  allowed {}\n}\n")
    assert load_profile(path).source == "built-in fallback"


def test_the_profile_version_is_derived_from_the_rules(tmp_path: Path) -> None:
    """A hand-written version has to be remembered, and the one time it is not, two
    runs admitted under different rules look equally comparable. Hashing the rules
    means the recorded version changes exactly when they do."""
    assert active_profile().version == PROFILE_VERSION

    changed = load_profile(tmp_path / "absent.conf")
    changed.locked["starting_year"] = 1960
    assert changed.version != PROFILE_VERSION


def test_every_allowed_key_is_a_recorded_leaderboard_column() -> None:
    """Disclosure is the condition on which a setting may vary. An allowed key with
    no column would let two runs differ invisibly."""
    from nttd.store.result_writer import _SCHEMA

    columns = set(_SCHEMA.names)
    for key in active_profile().allowed:
        column = f"map_{key}" if key.startswith("size_") else key
        assert column in columns, f"allowed dimension {key} has no result column"
