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
    """Load from the real config/scenario.conf file."""
    return load()


@pytest.fixture
def default_settings(default_config: ScenarioConfig) -> dict[str, str]:
    return scenario_to_settings(default_config)


# ---------------------------------------------------------------------------
# load() tests
# ---------------------------------------------------------------------------


def test_load_default_config() -> None:
    """Loading the project's scenario.conf returns a valid ScenarioConfig."""
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
    """The default scenario.conf should not produce any validation warnings."""
    cfg = load()
    scenario_to_settings(cfg)  # triggers validation internally
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 0, f"Unexpected warnings: {[r.message for r in warnings]}"
