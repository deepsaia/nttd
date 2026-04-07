"""Loads and exposes the scenario HOCON config as typed dataclasses.

Map/company settings are read directly from the pyhocon ConfigTree --
no dataclasses needed since they're only used to produce OpenTTD INI values.
Runtime, heartbeat, and end-condition configs use dataclasses because they're
passed around as typed objects in the orchestrator and end-condition checker.

If pyhocon is not installed or the config file is missing, returns safe defaults
so the server can start without a config file present.
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config" / "scenario.conf"

# ---------------------------------------------------------------------------
# Value maps: human-readable config strings -> OpenTTD INI integer values
# ---------------------------------------------------------------------------

_LANDSCAPE_MAP: dict[str, str] = {
    "temperate": "0", "sub-arctic": "1", "sub-tropical": "2", "toyland": "3",
    "arctic": "1", "tropic": "2",
}

_TERRAIN_MAP: dict[str, str] = {
    "flat": "0", "hilly": "1", "mountainous": "2", "alpinist": "3", "custom": "4",
}

_VARIETY_MAP: dict[str, str] = {
    "none": "0", "very_low": "1", "low": "2", "medium": "3", "high": "4", "very_high": "5",
}

_SMOOTHNESS_MAP: dict[str, str] = {
    "very_smooth": "0", "smooth": "1", "rough": "2", "very_rough": "3",
}

_RIVERS_MAP: dict[str, str] = {
    "none": "0", "few": "1", "medium": "2", "many": "3",
}

_SEA_LEVEL_MAP: dict[str, str] = {
    "very_low": "0", "low": "1", "medium": "2", "high": "3", "custom": "4",
}

_TOWNS_MAP: dict[str, str] = {
    "very_low": "0", "low": "1", "normal": "2", "high": "3", "custom": "4",
}

_INDUSTRY_MAP: dict[str, str] = {
    "funding_only": "0", "minimal": "1", "very_low": "2", "low": "3",
    "normal": "4", "high": "5", "custom": "6",
}

_TOWN_NAMES_MAP: dict[str, str] = {
    "english": "0", "french": "1", "german": "2", "american": "3",
    "latin_american": "4", "silly": "5", "swedish": "6", "dutch": "7",
    "finnish": "8", "polish": "9", "slovak": "10", "norwegian": "11",
    "hungarian": "12", "austrian": "13", "romanian": "14", "czech": "15",
    "swiss": "16", "danish": "17", "turkish": "18", "italian": "19",
    "catalan": "20", "english_additional": "21",
}

# OpenTTD water_borders bitmask: NE=1, SE=2, SW=4, NW=8, random=16
_WATER_BORDER_NE = 1
_WATER_BORDER_SE = 2
_WATER_BORDER_SW = 4
_WATER_BORDER_NW = 8
_WATER_BORDER_RANDOM = 16

# ---------------------------------------------------------------------------
# Dataclasses (only for configs used as typed objects in the runtime)
# ---------------------------------------------------------------------------


@dataclass
class HeartbeatConfig:
    interval_days: int = 30
    action_window_seconds: float = 5.0
    game_speed: int = 1


@dataclass
class TimeLimitConfig:
    enabled: bool = True
    wall_minutes: float = 60.0


@dataclass
class GameDateLimitConfig:
    enabled: bool = False
    end_year: int = 2000


@dataclass
class RevenueThresholdConfig:
    enabled: bool = False
    total_revenue: int = 1_000_000


@dataclass
class CargoThresholdConfig:
    enabled: bool = False
    total_cargo_delivered: int = 50_000


@dataclass
class MaxHeartbeatsConfig:
    enabled: bool = False
    count: int = 1000


@dataclass
class EndConditionsConfig:
    logic: str = "any"
    time_limit: TimeLimitConfig = field(default_factory=TimeLimitConfig)
    game_date_limit: GameDateLimitConfig = field(default_factory=GameDateLimitConfig)
    revenue_threshold: RevenueThresholdConfig = field(default_factory=RevenueThresholdConfig)
    cargo_threshold: CargoThresholdConfig = field(default_factory=CargoThresholdConfig)
    max_heartbeats: MaxHeartbeatsConfig = field(default_factory=MaxHeartbeatsConfig)


@dataclass
class RuntimeConfig:
    mode: str = "async_realtime"
    game_speed: int = 1
    snapshot_interval_days: int = 1


@dataclass
class ScenarioConfig:
    """Top-level scenario config. Map/company settings live in _raw (ConfigTree)."""
    name: str = "default"
    description: str = ""
    heartbeat: HeartbeatConfig = field(default_factory=HeartbeatConfig)
    end_conditions: EndConditionsConfig = field(default_factory=EndConditionsConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)
    _raw: Any = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# scenario_to_settings: reads map/company values directly from ConfigTree
# ---------------------------------------------------------------------------

def _get(cfg: Any, path: str, default: Any = None) -> Any:
    """Safely traverse a pyhocon ConfigTree by dot-path."""
    try:
        parts = path.split(".")
        node = cfg
        for part in parts:
            node = node[part]
        return node
    except Exception:
        return default


def _log2(n: int) -> int:
    """Return log2 of n (OpenTTD uses log2 for map dimensions)."""
    result = 0
    while n > 1:
        n >>= 1
        result += 1
    return result


def _compute_water_borders(map_cfg: Any) -> str:
    """Compute OpenTTD water_borders bitmask from the map config tree."""
    edges = _get(map_cfg, "map_edges", "random")
    if edges == "random":
        return str(_WATER_BORDER_RANDOM)
    if edges == "all_water":
        return str(_WATER_BORDER_NE | _WATER_BORDER_SE | _WATER_BORDER_SW | _WATER_BORDER_NW)
    bitmask = 0
    if _get(map_cfg, "water_borders_ne", 0):
        bitmask |= _WATER_BORDER_NE
    if _get(map_cfg, "water_borders_se", 0):
        bitmask |= _WATER_BORDER_SE
    if _get(map_cfg, "water_borders_sw", 0):
        bitmask |= _WATER_BORDER_SW
    if _get(map_cfg, "water_borders_nw", 0):
        bitmask |= _WATER_BORDER_NW
    return str(bitmask)


def _validate_config(m: Any, co: Any) -> None:
    """Validate map and company config values, logging warnings for issues.

    Checks for: unknown enum values, out-of-range numbers, conflicting combos.
    """
    # --- Enum validation: warn on unknown values ---
    _enum_checks: list[tuple[str, dict[str, str], Any]] = [
        ("landscape", _LANDSCAPE_MAP, _get(m, "landscape", "temperate")),
        ("terrain_type", _TERRAIN_MAP, _get(m, "terrain_type", "hilly")),
        ("variety", _VARIETY_MAP, _get(m, "variety", "none")),
        ("smoothness", _SMOOTHNESS_MAP, _get(m, "smoothness", "smooth")),
        ("rivers", _RIVERS_MAP, _get(m, "rivers", "medium")),
        ("sea_level", _SEA_LEVEL_MAP, _get(m, "sea_level", "medium")),
        ("number_towns", _TOWNS_MAP, _get(m, "number_towns", "normal")),
        ("industry_density", _INDUSTRY_MAP, _get(m, "industry_density", "normal")),
        ("town_names", _TOWN_NAMES_MAP, _get(m, "town_names", "english")),
    ]
    for field_name, valid_map, value in _enum_checks:
        if value not in valid_map:
            logger.warning(
                "Unknown %s value %r -- falling back to default. Valid: %s",
                field_name, value, ", ".join(valid_map.keys()),
            )

    # --- Map dimensions: must be powers of 2, range 64..4096 ---
    for dim in ("size_x", "size_y"):
        val = int(_get(m, dim, 256))
        if val < 64 or val > 4096:
            logger.warning("map.%s = %d is outside OpenTTD range [64, 4096]", dim, val)
        elif val & (val - 1) != 0:
            logger.warning("map.%s = %d is not a power of 2 -- OpenTTD requires powers of 2", dim, val)

    # --- Custom terrain height: 1..255 ---
    terrain = _get(m, "terrain_type", "hilly")
    if terrain == "custom":
        h = int(_get(m, "custom_terrain_height", 30))
        if h < 1 or h > 255:
            logger.warning("custom_terrain_height = %d is outside range [1, 255]", h)

    # --- Custom sea level: 1..90 ---
    sea = _get(m, "sea_level", "medium")
    if sea == "custom":
        sl = int(_get(m, "custom_sea_level", 1))
        if sl < 1 or sl > 90:
            logger.warning("custom_sea_level = %d is outside range [1, 90]", sl)

    # --- Custom town/industry numbers: must be >= 1 ---
    towns = _get(m, "number_towns", "normal")
    if towns == "custom":
        tn = int(_get(m, "custom_town_number", 1))
        if tn < 1:
            logger.warning("custom_town_number = %d must be >= 1", tn)

    industry = _get(m, "industry_density", "normal")
    if industry == "custom":
        ind = int(_get(m, "custom_industry_number", 1))
        if ind < 1:
            logger.warning("custom_industry_number = %d must be >= 1", ind)

    # --- Water borders: individual flags ignored unless map_edges = "manual" ---
    edges = _get(m, "map_edges", "random")
    has_individual = any(
        _get(m, f"water_borders_{d}", 0) for d in ("ne", "se", "sw", "nw")
    )
    if edges != "manual" and has_individual:
        logger.warning(
            "water_borders_ne/se/sw/nw are set but map_edges = %r (not 'manual') -- "
            "individual border flags will be ignored",
            edges,
        )

    # --- Starting year: OpenTTD range ---
    year = int(_get(m, "starting_year", 1950))
    if year < 0 or year > 5000000:
        logger.warning("starting_year = %d is outside reasonable range", year)

    # --- AI companies: 0..14 ---
    num_ai = int(_get(co, "num_ai_companies", 2))
    if num_ai < 0 or num_ai > 14:
        logger.warning("num_ai_companies = %d is outside range [0, 14]", num_ai)

    # --- Max loan: must be positive ---
    max_loan = int(_get(co, "max_loan", 300000))
    if max_loan < 0:
        logger.warning("max_loan = %d must be non-negative", max_loan)


def scenario_to_settings(cfg: ScenarioConfig) -> dict[str, str]:
    """Convert a ScenarioConfig to OpenTTD INI settings dict.

    Map and company values are read from the raw pyhocon ConfigTree.
    Returns key-value pairs baked into the per-session openttd.cfg.
    """
    settings: dict[str, str] = {}
    raw = cfg._raw

    # If no raw config (defaults only), produce minimal settings
    if raw is None:
        return settings

    m = _get(raw, "map", {})
    co = _get(raw, "companies", {})

    _validate_config(m, co)

    # Map dimensions (log2)
    settings["game_creation.map_x"] = str(_log2(int(_get(m, "size_x", 256))))
    settings["game_creation.map_y"] = str(_log2(int(_get(m, "size_y", 256))))

    # Landscape
    settings["game_creation.landscape"] = _LANDSCAPE_MAP.get(_get(m, "landscape", "temperate"), "0")

    # Terrain
    terrain = _get(m, "terrain_type", "hilly")
    settings["difficulty.terrain_type"] = _TERRAIN_MAP.get(terrain, "1")
    if terrain == "custom":
        settings["game_creation.custom_terrain_type"] = str(int(_get(m, "custom_terrain_height", 30)))

    # Variety and smoothness
    settings["game_creation.variety"] = _VARIETY_MAP.get(_get(m, "variety", "none"), "0")
    settings["game_creation.tgen_smoothness"] = _SMOOTHNESS_MAP.get(_get(m, "smoothness", "smooth"), "1")

    # Water
    settings["game_creation.amount_of_rivers"] = _RIVERS_MAP.get(_get(m, "rivers", "medium"), "2")
    sea_level = _get(m, "sea_level", "medium")
    settings["difficulty.quantity_sea_lakes"] = _SEA_LEVEL_MAP.get(sea_level, "2")
    if sea_level == "custom":
        settings["game_creation.custom_sea_level"] = str(int(_get(m, "custom_sea_level", 1)))
    settings["game_creation.water_borders"] = _compute_water_borders(m)

    # Towns
    settings["game_creation.town_name"] = _TOWN_NAMES_MAP.get(_get(m, "town_names", "english"), "0")
    num_towns = _get(m, "number_towns", "normal")
    settings["difficulty.number_towns"] = _TOWNS_MAP.get(num_towns, "2")
    if num_towns == "custom":
        settings["game_creation.custom_town_number"] = str(int(_get(m, "custom_town_number", 1)))

    # Industries
    industry = _get(m, "industry_density", "normal")
    settings["difficulty.industry_density"] = _INDUSTRY_MAP.get(industry, "4")
    if industry == "custom":
        settings["game_creation.custom_industry_number"] = str(int(_get(m, "custom_industry_number", 1)))

    # Start date
    settings["game_creation.starting_year"] = str(int(_get(m, "starting_year", 1950)))

    # AI / company settings
    num_ai = int(_get(co, "num_ai_companies", 2))
    settings["difficulty.max_no_competitors"] = str(num_ai)
    settings["difficulty.competitors_interval"] = str(int(_get(co, "competitors_interval", 0)))
    max_loan = int(_get(co, "max_loan", 300000))
    if max_loan != 300000:
        settings["difficulty.max_loan"] = str(max_loan)

    return settings


# ---------------------------------------------------------------------------
# load(): parse HOCON, return ScenarioConfig
# ---------------------------------------------------------------------------

def load(config_path: Path | str | None = None) -> ScenarioConfig:
    """Load scenario config from a HOCON file. Falls back to defaults on any error."""
    path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH

    if not path.exists():
        logger.info("Scenario config not found at %s -- using defaults", path)
        return ScenarioConfig()

    try:
        from pyhocon import ConfigFactory  # type: ignore[import-untyped]
        raw = ConfigFactory.parse_file(str(path))
        s = raw.get("scenario", raw)
    except ImportError:
        logger.warning("pyhocon not installed -- using default scenario config")
        return ScenarioConfig()
    except Exception:
        logger.exception("Failed to parse scenario config at %s -- using defaults", path)
        return ScenarioConfig()

    # End conditions
    ec_raw = _get(s, "end_conditions", {})
    end_conditions = EndConditionsConfig(
        logic=_get(ec_raw, "logic", "any"),
        time_limit=TimeLimitConfig(
            enabled=_get(ec_raw, "time_limit.enabled", True),
            wall_minutes=float(_get(ec_raw, "time_limit.wall_minutes", 60.0)),
        ),
        game_date_limit=GameDateLimitConfig(
            enabled=_get(ec_raw, "game_date_limit.enabled", False),
            end_year=int(_get(ec_raw, "game_date_limit.end_year", 2000)),
        ),
        revenue_threshold=RevenueThresholdConfig(
            enabled=_get(ec_raw, "revenue_threshold.enabled", False),
            total_revenue=int(_get(ec_raw, "revenue_threshold.total_revenue", 1_000_000)),
        ),
        cargo_threshold=CargoThresholdConfig(
            enabled=_get(ec_raw, "cargo_threshold.enabled", False),
            total_cargo_delivered=int(_get(ec_raw, "cargo_threshold.total_cargo_delivered", 50_000)),
        ),
        max_heartbeats=MaxHeartbeatsConfig(
            enabled=_get(ec_raw, "max_heartbeats.enabled", False),
            count=int(_get(ec_raw, "max_heartbeats.count", 1000)),
        ),
    )

    hb_raw = _get(s, "heartbeat", {})
    rt_raw = _get(s, "runtime", {})

    runtime = RuntimeConfig(
        mode=_get(rt_raw, "mode", "async_realtime"),
        game_speed=int(_get(rt_raw, "game_speed", _get(hb_raw, "game_speed", 1))),
        snapshot_interval_days=int(_get(rt_raw, "snapshot_interval_days", 1)),
    )

    return ScenarioConfig(
        name=_get(s, "name", "default"),
        description=_get(s, "description", ""),
        heartbeat=HeartbeatConfig(
            interval_days=int(_get(hb_raw, "interval_days", 30)),
            action_window_seconds=float(_get(hb_raw, "action_window_seconds", 5.0)),
            game_speed=int(_get(hb_raw, "game_speed", 1)),
        ),
        end_conditions=end_conditions,
        runtime=runtime,
        _raw=s,
    )
