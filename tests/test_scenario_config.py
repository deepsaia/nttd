"""Tests for scenario_config: load, settings conversion, and validation.

Run with: uv run pytest tests/test_scenario_config.py -v
"""
import logging
from typing import Any

import pytest

from nttd.config.scenario_config import (
    EndConditionsConfig,
    HeartbeatConfig,
    MaxHeartbeatsConfig,
    RuntimeConfig,
    ScenarioConfig,
    TimeLimitConfig,
    load,
    scenario_to_settings,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def default_config() -> ScenarioConfig:
    """Load the shipped default, which is config/benchmark/t2_example.conf."""
    return load()


@pytest.fixture
def default_settings(default_config: ScenarioConfig) -> dict[str, str]:
    return scenario_to_settings(default_config)


# ---------------------------------------------------------------------------
# load() tests
# ---------------------------------------------------------------------------


def test_load_default_config() -> None:
    """Loading the shipped default returns a valid ScenarioConfig."""
    cfg = load()
    assert isinstance(cfg, ScenarioConfig)
    assert cfg._raw is not None  # has a parsed ConfigTree


def test_load_missing_file_returns_defaults() -> None:
    """A missing config file returns safe defaults."""
    cfg = load("/tmp/nonexistent_scenario_config.conf")
    assert cfg.name == "default"
    assert cfg._raw is None


def test_load_heartbeat_config() -> None:
    cfg = load()
    assert isinstance(cfg.heartbeat, HeartbeatConfig)
    assert cfg.heartbeat.interval_days > 0
    assert cfg.heartbeat.action_window_seconds > 0


def test_load_end_conditions() -> None:
    cfg = load()
    ec = cfg.end_conditions
    assert isinstance(ec, EndConditionsConfig)
    assert ec.logic in ("any", "all")
    assert isinstance(ec.time_limit, TimeLimitConfig)
    assert isinstance(ec.max_heartbeats, MaxHeartbeatsConfig)


def test_load_runtime_config() -> None:
    cfg = load()
    assert isinstance(cfg.runtime, RuntimeConfig)
    assert cfg.runtime.mode in ("async_realtime", "heartbeat", "assisted")


# ---------------------------------------------------------------------------
# scenario_to_settings() tests
# ---------------------------------------------------------------------------


def test_settings_has_required_keys(default_settings: dict[str, str]) -> None:
    """All essential OpenTTD settings are present."""
    required = [
        "game_creation.map_x",
        "game_creation.map_y",
        "game_creation.landscape",
        "difficulty.terrain_type",
        "game_creation.starting_year",
        "difficulty.max_no_competitors",
    ]
    for key in required:
        assert key in default_settings, f"Missing required setting: {key}"


def test_settings_values_are_strings(default_settings: dict[str, str]) -> None:
    """All settings values must be strings (OpenTTD INI format)."""
    for key, value in default_settings.items():
        assert isinstance(value, str), f"{key} value is {type(value)}, expected str"


def test_settings_map_dimensions_are_log2(default_settings: dict[str, str]) -> None:
    """Map dimensions should be log2 values (e.g., 256 -> 8)."""
    map_x = int(default_settings["game_creation.map_x"])
    map_y = int(default_settings["game_creation.map_y"])
    # log2(64)=6, log2(4096)=12
    assert 6 <= map_x <= 12, f"map_x={map_x} is out of valid range"
    assert 6 <= map_y <= 12, f"map_y={map_y} is out of valid range"


def test_settings_no_raw_returns_empty() -> None:
    """ScenarioConfig with no _raw returns empty settings dict."""
    cfg = ScenarioConfig()
    settings = scenario_to_settings(cfg)
    assert settings == {}


def test_settings_landscape_valid_values(default_settings: dict[str, str]) -> None:
    landscape = default_settings["game_creation.landscape"]
    assert landscape in ("0", "1", "2", "3"), f"Invalid landscape: {landscape}"


def test_settings_custom_values_conditional() -> None:
    """Custom values should only appear when their parent is 'custom'."""
    cfg = load()
    settings = scenario_to_settings(cfg)

    # With default config, terrain_type is "hilly" (not "custom"),
    # so custom_terrain_type should NOT be in settings
    from nttd.config.scenario_config import _get
    raw = cfg._raw
    m = _get(raw, "map", {})

    terrain = _get(m, "terrain_type", "hilly")
    if terrain != "custom":
        assert "game_creation.custom_terrain_type" not in settings

    sea = _get(m, "sea_level", "medium")
    if sea != "custom":
        assert "game_creation.custom_sea_level" not in settings

    towns = _get(m, "number_towns", "normal")
    if towns != "custom":
        assert "game_creation.custom_town_number" not in settings

    industry = _get(m, "industry_density", "normal")
    if industry != "custom":
        assert "game_creation.custom_industry_number" not in settings


def test_terrain_type_matches_openttd_enum() -> None:
    """terrain_type must index GenworldMaxHeight, not an off-by-one of it.

    OpenTTD src/settings_type.h: VeryFlat=0, Flat=1, Hilly=2, Mountainous=3,
    Alpinist=4, Custom=5. nttd previously mapped flat=0/hilly=1/..., so "hilly"
    silently generated Flat terrain. Verified against OpenTTD 15.3 by sampling
    tile heights (mean 1.42 / 2.42 / 4.52 / 6.26 for values 0..3).
    """
    from nttd.config.scenario_config import _TERRAIN_MAP

    assert _TERRAIN_MAP == {
        "very_flat": "0", "flat": "1", "hilly": "2",
        "mountainous": "3", "alpinist": "4", "custom": "5",
    }


def test_strict_mode_rejects_unknown_enum(tmp_path: Any) -> None:
    """A typo in a scored run must raise, not silently pick a different world."""
    from nttd.config.scenario_config import ScenarioConfigError

    path = tmp_path / "typo.conf"
    path.write_text('scenario { map { size_x = 256, size_y = 256, terrain_type = "hily" } }')
    cfg = load(path)

    # Lenient mode (the default) falls back and keeps going.
    assert scenario_to_settings(cfg)["difficulty.terrain_type"] == "1"

    with pytest.raises(ScenarioConfigError, match="terrain_type"):
        scenario_to_settings(cfg, strict=True)


def test_strict_mode_rejects_bad_map_size(tmp_path: Any) -> None:
    """Non-power-of-2 map dimensions must be refused in strict mode."""
    from nttd.config.scenario_config import ScenarioConfigError

    path = tmp_path / "badsize.conf"
    path.write_text("scenario { map { size_x = 300, size_y = 256 } }")
    with pytest.raises(ScenarioConfigError, match="power of 2"):
        scenario_to_settings(load(path), strict=True)


def test_strict_mode_rejects_missing_config() -> None:
    """A missing/unparseable file must not silently become a defaults run."""
    from nttd.config.scenario_config import ScenarioConfigError

    cfg = load("/tmp/nonexistent_scenario_for_strict_test.conf")
    assert scenario_to_settings(cfg) == {}  # lenient: empty settings
    with pytest.raises(ScenarioConfigError, match="no parsed tree"):
        scenario_to_settings(cfg, strict=True)


def test_strict_mode_reports_every_problem(tmp_path: Any) -> None:
    """Strict mode collects all problems, so one run surfaces the whole list."""
    from nttd.config.scenario_config import ScenarioConfigError

    path = tmp_path / "multi.conf"
    path.write_text(
        'scenario { map { size_x = 300, size_y = 256, terrain_type = "nope", '
        'rivers = "loads" }, companies { num_ai_companies = 99 } }'
    )
    with pytest.raises(ScenarioConfigError) as exc:
        scenario_to_settings(load(path), strict=True)
    message = str(exc.value)
    for expected in ("terrain_type", "rivers", "power of 2", "num_ai_companies"):
        assert expected in message


def test_shipped_configs_are_strict_clean() -> None:
    """Every shipped scenario must pass strict validation."""
    from pathlib import Path

    # profile.conf is the admission rules, not a scenario, so it is excluded.
    configs = [
        path for path in sorted(Path("config/benchmark").glob("*.conf"))
        if path.name != "profile.conf"
    ]
    assert configs, "expected shipped scenario configs"
    for path in configs:
        scenario_to_settings(load(path), strict=True)


def test_shipped_configs_are_seeded() -> None:
    """Every shipped scenario must pin a seed, or its runs are not comparable."""
    from pathlib import Path

    for path in sorted(Path("config/benchmark").glob("*.conf")):
        if path.name == "profile.conf":
            continue
        settings = scenario_to_settings(load(path), strict=True)
        assert settings.get("_map_seed"), f"{path.name} has no map.seed"


def test_timekeeping_defaults_to_calendar() -> None:
    """Absent config, timekeeping is OpenTTD's default calendar mode at 12 min/yr."""
    cfg = load()
    settings = scenario_to_settings(cfg)
    assert settings["economy.timekeeping_units"] == "0"
    assert settings["economy.minutes_per_calendar_year"] == "12"
    assert cfg.runtime.timekeeping_units == "calendar"


def test_wallclock_unlocks_minutes_per_calendar_year(tmp_path: Any) -> None:
    """Wallclock mode allows a long calendar year, which freezes the tech tree."""
    path = tmp_path / "wallclock.conf"
    path.write_text(
        'scenario { map { size_x = 256, size_y = 256 }, '
        'runtime { timekeeping_units = "wallclock", minutes_per_calendar_year = 600 } }'
    )
    settings = scenario_to_settings(load(path), strict=True)
    assert settings["economy.timekeeping_units"] == "1"
    assert settings["economy.minutes_per_calendar_year"] == "600"


def test_strict_rejects_nondefault_minutes_in_calendar_mode(tmp_path: Any) -> None:
    """OpenTTD clamps the calendar year to 12 outside wallclock mode -- refuse it."""
    from nttd.config.scenario_config import ScenarioConfigError

    path = tmp_path / "clamped.conf"
    path.write_text(
        'scenario { map { size_x = 256, size_y = 256 }, '
        'runtime { minutes_per_calendar_year = 3 } }'
    )
    with pytest.raises(ScenarioConfigError, match="wallclock"):
        scenario_to_settings(load(path), strict=True)


def test_strict_rejects_out_of_range_wallclock_minutes(tmp_path: Any) -> None:
    """Wallclock allows 0..10080; anything beyond is refused."""
    from nttd.config.scenario_config import ScenarioConfigError

    path = tmp_path / "toobig.conf"
    path.write_text(
        'scenario { map { size_x = 256, size_y = 256 }, '
        'runtime { timekeeping_units = "wallclock", minutes_per_calendar_year = 99999 } }'
    )
    with pytest.raises(ScenarioConfigError, match=r"\[0, 10080\]"):
        scenario_to_settings(load(path), strict=True)


def test_settings_seed_emits_both_cfg_key_and_spawn_key(tmp_path: Any) -> None:
    """A configured seed must produce the cfg key AND the _map_seed spawn key.

    OpenTTD 15.3 does not pin map generation from game_creation.generation_seed
    in the config alone -- only the -G command-line flag does. _map_seed is what
    SessionManager threads to that flag, so emitting only the cfg key would give
    every contestant a different world while appearing seeded.
    """
    path = tmp_path / "seeded.conf"
    path.write_text('scenario { name = "s", map { size_x = 256, size_y = 256, seed = 4242 } }')
    settings = scenario_to_settings(load(path))
    assert settings["game_creation.generation_seed"] == "4242"
    assert settings["_map_seed"] == "4242", "seed must reach the spawn, not just the cfg"


def test_settings_seed_absent_when_unset(tmp_path: Any) -> None:
    """No seed configured means no seed keys -- the map is explicitly random."""
    path = tmp_path / "unseeded.conf"
    path.write_text('scenario { name = "s", map { size_x = 256, size_y = 256 } }')
    settings = scenario_to_settings(load(path))
    assert "game_creation.generation_seed" not in settings
    assert "_map_seed" not in settings


def test_settings_water_borders() -> None:
    """Water borders should be a valid integer bitmask string."""
    cfg = load()
    settings = scenario_to_settings(cfg)
    borders = int(settings["game_creation.water_borders"])
    # Valid range: 0-31 (NE=1 | SE=2 | SW=4 | NW=8 | random=16)
    assert 0 <= borders <= 31, f"Invalid water_borders: {borders}"


def test_settings_max_loan_omitted_when_default() -> None:
    """max_loan should only appear if different from the default 300000."""
    cfg = load()
    settings = scenario_to_settings(cfg)
    from nttd.config.scenario_config import _get
    raw = cfg._raw
    co = _get(raw, "companies", {})
    max_loan = int(_get(co, "max_loan", 300000))
    if max_loan == 300000:
        assert "difficulty.max_loan" not in settings
    else:
        assert "difficulty.max_loan" in settings


# ---------------------------------------------------------------------------
# Validation tests (via logging)
# ---------------------------------------------------------------------------


def test_validation_warns_on_unknown_enum(caplog: pytest.LogCaptureFixture) -> None:
    """Unknown enum values should produce warnings."""
    from nttd.config.scenario_config import _validate_config

    m = {"landscape": "mars"}
    co: dict[str, Any] = {}
    with caplog.at_level(logging.WARNING, logger="nttd.config.scenario_config"):
        _validate_config(m, co)

    assert any("Unknown landscape" in r.message for r in caplog.records)


def test_validation_warns_on_bad_map_size(caplog: pytest.LogCaptureFixture) -> None:
    """Non-power-of-2 map sizes should produce warnings."""
    from nttd.config.scenario_config import _validate_config

    m = {"size_x": 300, "size_y": 256}
    co: dict[str, Any] = {}
    with caplog.at_level(logging.WARNING, logger="nttd.config.scenario_config"):
        _validate_config(m, co)

    assert any("not a power of 2" in r.message for r in caplog.records)


def test_validation_warns_on_ai_count_out_of_range(caplog: pytest.LogCaptureFixture) -> None:
    """AI company count > 14 should produce a warning."""
    from nttd.config.scenario_config import _validate_config

    m: dict[str, Any] = {}
    co = {"num_ai_companies": 20}
    with caplog.at_level(logging.WARNING, logger="nttd.config.scenario_config"):
        _validate_config(m, co)

    assert any("num_ai_companies" in r.message for r in caplog.records)


def test_validation_warns_on_conflicting_water_borders(caplog: pytest.LogCaptureFixture) -> None:
    """Setting water border flags without map_edges='manual' should warn."""
    from nttd.config.scenario_config import _validate_config

    m = {"map_edges": "random", "water_borders_ne": 1}
    co: dict[str, Any] = {}
    with caplog.at_level(logging.WARNING, logger="nttd.config.scenario_config"):
        _validate_config(m, co)

    assert any("will be ignored" in r.message for r in caplog.records)


def test_validation_no_warnings_on_valid_config(caplog: pytest.LogCaptureFixture) -> None:
    """The shipped default should not produce any validation warnings."""
    cfg = load()
    scenario_to_settings(cfg)  # triggers validation internally
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 0, f"Unexpected warnings: {[r.message for r in warnings]}"


def test_strict_refuses_a_scenario_fairness_block(tmp_path: Any) -> None:
    """How much a contestant may do is operator policy, not a scenario's choice.

    Left in the scenario it would vary between tasks that are otherwise identical,
    and a contestant writing their own conforming scenario would be setting their own
    budget. Refused rather than ignored, so an author is told where it went.
    """
    from nttd.config.scenario_config import ScenarioConfigError

    path = tmp_path / "fair.conf"
    path.write_text(
        'scenario { map { size_x = 256, size_y = 256 }, '
        'fairness { max_actions_per_step = 200 } }'
    )
    with pytest.raises(ScenarioConfigError, match="operator policy"):
        scenario_to_settings(load(path), strict=True)


def test_the_refusal_points_at_the_profile(tmp_path: Any) -> None:
    from nttd.config.scenario_config import ScenarioConfigError

    path = tmp_path / "fair.conf"
    path.write_text(
        'scenario { map { size_x = 256 }, fairness { poll_interval = 0.5 } }'
    )
    with pytest.raises(ScenarioConfigError) as excinfo:
        scenario_to_settings(load(path), strict=True)
    assert "config/benchmark/profile.conf" in str(excinfo.value)


def test_no_fairness_keys_are_emitted(tmp_path: Any) -> None:
    """The _fair_* settings are gone: the limit is read from the profile at session
    start, so carrying it through session settings would be a second copy a client
    could try to supply."""
    path = tmp_path / "plain.conf"
    path.write_text('scenario { map { size_x = 256, size_y = 256 } }')
    settings = scenario_to_settings(load(path), strict=True)
    assert not [key for key in settings if key.startswith("_fair_")]


def test_an_unknown_top_level_key_is_ignored(tmp_path: Any) -> None:
    """A scenario names the world and the rules. Anything else, including the
    agents list old scenarios carried, is simply not read: which agents play a task
    belongs to the runner's own config, and nttd runs no agents."""
    path = tmp_path / "extra.conf"
    path.write_text(
        'scenario { map { size_x = 256, size_y = 256 }, '
        'agents = [ { agent_id = "a", model = "gpt-5.2" } ] }'
    )
    settings = scenario_to_settings(load(path), strict=True)
    assert settings["game_creation.map_x"] == "8"
    assert not any("agent" in key for key in settings)
