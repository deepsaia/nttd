"""Loads and exposes the scenario HOCON config as typed dataclasses.

If pyhocon is not installed or the config file is missing, returns safe defaults
so the server can start without a config file present.
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent.parent / "config" / "scenario.conf"


@dataclass
class MapConfig:
    size_x: int = 256
    size_y: int = 256
    landscape: str = "temperate"
    terrain_type: int = 1
    starting_year: int = 1950
    number_towns: int = 2
    industry_density: int = 4


@dataclass
class CompaniesConfig:
    num_ai_companies: int = 2
    max_loan: int = 300000


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
class ScenarioConfig:
    name: str = "default"
    description: str = ""
    map: MapConfig = field(default_factory=MapConfig)
    companies: CompaniesConfig = field(default_factory=CompaniesConfig)
    heartbeat: HeartbeatConfig = field(default_factory=HeartbeatConfig)
    end_conditions: EndConditionsConfig = field(default_factory=EndConditionsConfig)


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


def load(config_path: Path | str | None = None) -> ScenarioConfig:
    """Load scenario config from a HOCON file. Falls back to defaults on any error."""
    path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH

    if not path.exists():
        logger.info("Scenario config not found at %s — using defaults", path)
        return ScenarioConfig()

    try:
        from pyhocon import ConfigFactory  # type: ignore[import-untyped]
        raw = ConfigFactory.parse_file(str(path))
        s = raw.get("scenario", raw)
    except ImportError:
        logger.warning("pyhocon not installed — using default scenario config. Install with: pip install pyhocon")
        return ScenarioConfig()
    except Exception:
        logger.exception("Failed to parse scenario config at %s — using defaults", path)
        return ScenarioConfig()

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
    map_raw = _get(s, "map", {})
    co_raw = _get(s, "companies", {})

    return ScenarioConfig(
        name=_get(s, "name", "default"),
        description=_get(s, "description", ""),
        map=MapConfig(
            size_x=int(_get(map_raw, "size_x", 256)),
            size_y=int(_get(map_raw, "size_y", 256)),
            landscape=_get(map_raw, "landscape", "temperate"),
            terrain_type=int(_get(map_raw, "terrain_type", 1)),
            starting_year=int(_get(map_raw, "starting_year", 1950)),
            number_towns=int(_get(map_raw, "number_towns", 2)),
            industry_density=int(_get(map_raw, "industry_density", 4)),
        ),
        companies=CompaniesConfig(
            num_ai_companies=int(_get(co_raw, "num_ai_companies", 2)),
            max_loan=int(_get(co_raw, "max_loan", 300000)),
        ),
        heartbeat=HeartbeatConfig(
            interval_days=int(_get(hb_raw, "interval_days", 30)),
            action_window_seconds=float(_get(hb_raw, "action_window_seconds", 5.0)),
            game_speed=int(_get(hb_raw, "game_speed", 1)),
        ),
        end_conditions=end_conditions,
    )
