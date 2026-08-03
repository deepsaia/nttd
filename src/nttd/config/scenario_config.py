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

# difficulty.terrain_type indexes GenworldMaxHeight (OpenTTD src/settings_type.h):
# VeryFlat=0, Flat=1, Hilly=2, Mountainous=3, Alpinist=4, Custom=5.
#
# nttd previously mapped flat=0/hilly=1/mountainous=2/alpinist=3/custom=4, which
# was off by one against every value: "hilly" generated Flat terrain. Verified
# empirically against OpenTTD 15.3 by sampling tile heights -- mean height rises
# 1.42, 2.42, 4.52, 6.26 for values 0..3.
#
# NOTE: correcting this changes the terrain of every previously generated map, so
# results produced before this fix are not comparable with results after it.
_TERRAIN_MAP: dict[str, str] = {
    "very_flat": "0", "flat": "1", "hilly": "2",
    "mountainous": "3", "alpinist": "4", "custom": "5",
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

# Snapshot class names an unscored scenario may give an agent. A scored run always
# observes fully, so this only guards the per-agent observation_mode in agents[].
# Kept in sync with _BUILTIN_PRESETS in state/snapshot_class.py by a test, rather
# than imported, so config validation does not depend on runtime state.
_KNOWN_OBSERVATION_MODES: frozenset[str] = frozenset({
    "minimal", "compact", "agent", "mas_rail", "standard", "full",
})

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
    """Bound a run in steps rather than wall time.

    This is the natural bound for stepped mode, where deliberation is unbounded
    and wall time therefore says nothing about how much of the game was played.
    """

    enabled: bool = False
    count: int = 1000


@dataclass
class BankruptcyConfig:
    """End the run when a scored company goes bankrupt or is removed."""

    enabled: bool = False


@dataclass
class EndConditionsConfig:
    logic: str = "any"
    time_limit: TimeLimitConfig = field(default_factory=TimeLimitConfig)
    game_date_limit: GameDateLimitConfig = field(default_factory=GameDateLimitConfig)
    revenue_threshold: RevenueThresholdConfig = field(default_factory=RevenueThresholdConfig)
    cargo_threshold: CargoThresholdConfig = field(default_factory=CargoThresholdConfig)
    max_heartbeats: MaxHeartbeatsConfig = field(default_factory=MaxHeartbeatsConfig)
    bankruptcy: BankruptcyConfig = field(default_factory=BankruptcyConfig)


@dataclass
class RuntimeConfig:
    """Runtime settings.

    ``game_speed`` is retained for config compatibility but has NO effect:
    OpenTTD 15.3 has no runtime speed control, and the economy clock is fixed at
    1 wall-minute per economy month.

    ``timekeeping_units`` and ``minutes_per_calendar_year`` are the real pacing
    knobs, and they apply at map generation only. They move the CALENDAR clock
    (vehicle and house introduction dates, inflation), not the economy. In
    "calendar" mode minutes_per_calendar_year is clamped to 12; "wallclock" opens
    the range to 0..10080, so a long calendar year effectively freezes the tech
    tree -- useful for making every contestant in a tier face the same available
    vehicles.
    """

    mode: str = "async_realtime"
    game_speed: int = 1
    snapshot_interval_days: int = 1
    timekeeping_units: str = "calendar"
    minutes_per_calendar_year: int = 12


@dataclass
class ScenarioConfig:
    """Top-level scenario config. Map/company settings live in _raw (ConfigTree).

    ``id`` and ``version`` identify the task instance independently of the file
    path, so a result stays traceable to the exact problem it was scored on.
    ``id`` defaults to ``name``; bump ``version`` on any change that should
    invalidate comparison with earlier results.
    """

    name: str = "default"
    description: str = ""
    id: str = ""
    version: str = "1"
    # When true, the session refuses game-mutating operator operations for its
    # whole life, for every caller. This is what protects a benchmark result: a
    # self-hosting contestant holds every credential, so session state is the only
    # boundary that means anything. Off by default, since scenario authoring and
    # debugging need the full surface.
    scored: bool = False
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


class ScenarioConfigError(ValueError):
    """A scenario config is invalid and must not be used for a scored run."""


def _report(strict: bool, problems: list[str], message: str, *args: Any) -> None:
    """Record a config problem: collect it in strict mode, log it otherwise.

    In lenient mode the caller falls back to a default, so the log says so. In
    strict mode nothing falls back -- the collected problems become an error.
    """
    formatted = message % args
    if strict:
        problems.append(formatted)
    else:
        # Deliberately vague about the remedy: an unknown enum falls back to a
        # default, while an out-of-range fairness value is clamped by
        # config/fairness.py. Naming one would be wrong for the other.
        logger.warning("%s (value not used as given)", formatted)


def _validate_config(
    m: Any, co: Any, strict: bool = False, rt: Any = None, fair: Any = None,
    agents: Any = None,
) -> None:
    """Validate map, company, and runtime config values.

    Checks for: unknown enum values, out-of-range numbers, conflicting combos.

    Args:
        m: The ``map`` config tree.
        co: The ``companies`` config tree.
        strict: When True, collect every problem and raise ScenarioConfigError
            instead of falling back to defaults. Scored runs use strict mode so
            an ill-specified task instance is refused rather than silently
            substituted -- a typo must not quietly produce a different world.
        rt: The ``runtime`` config tree, if present.
        fair: The ``fairness`` config tree, if present.
        agents: The ``agents`` list, if present.

    Raises:
        ScenarioConfigError: In strict mode, if any problem was found.
    """
    problems: list[str] = []

    # --- Enum validation ---
    _enum_checks: list[tuple[str, dict[str, str], Any]] = [
        ("landscape", _LANDSCAPE_MAP, _get(m, "landscape", "temperate")),
        ("terrain_type", _TERRAIN_MAP, _get(m, "terrain_type", "flat")),
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
            _report(
                strict, problems,
                "Unknown %s value %r. Valid: %s",
                field_name, value, ", ".join(valid_map.keys()),
            )

    # --- Map dimensions: must be powers of 2, range 64..4096 ---
    for dim in ("size_x", "size_y"):
        val = int(_get(m, dim, 256))
        if val < 64 or val > 4096:
            _report(strict, problems, "map.%s = %d is outside OpenTTD range [64, 4096]", dim, val)
        elif val & (val - 1) != 0:
            _report(
                strict, problems,
                "map.%s = %d is not a power of 2 -- OpenTTD requires powers of 2", dim, val,
            )

    # --- Custom terrain height: 1..255 ---
    terrain = _get(m, "terrain_type", "flat")
    if terrain == "custom":
        h = int(_get(m, "custom_terrain_height", 30))
        if h < 1 or h > 255:
            _report(strict, problems, "custom_terrain_height = %d is outside range [1, 255]", h)

    # --- Custom sea level: 1..90 ---
    sea = _get(m, "sea_level", "medium")
    if sea == "custom":
        sl = int(_get(m, "custom_sea_level", 1))
        if sl < 1 or sl > 90:
            _report(strict, problems, "custom_sea_level = %d is outside range [1, 90]", sl)

    # --- Custom town/industry numbers: must be >= 1 ---
    towns = _get(m, "number_towns", "normal")
    if towns == "custom":
        tn = int(_get(m, "custom_town_number", 1))
        if tn < 1:
            _report(strict, problems, "custom_town_number = %d must be >= 1", tn)

    industry = _get(m, "industry_density", "normal")
    if industry == "custom":
        ind = int(_get(m, "custom_industry_number", 1))
        if ind < 1:
            _report(strict, problems, "custom_industry_number = %d must be >= 1", ind)

    # --- Water borders: individual flags ignored unless map_edges = "manual" ---
    edges = _get(m, "map_edges", "random")
    has_individual = any(
        _get(m, f"water_borders_{d}", 0) for d in ("ne", "se", "sw", "nw")
    )
    if edges != "manual" and has_individual:
        _report(
            strict, problems,
            "water_borders_ne/se/sw/nw are set but map_edges = %r (not 'manual') -- "
            "individual border flags will be ignored",
            edges,
        )

    # --- Starting year: OpenTTD range ---
    year = int(_get(m, "starting_year", 1960))
    if year < 0 or year > 5000000:
        _report(strict, problems, "starting_year = %d is outside reasonable range", year)

    # --- AI companies: 0..14 ---
    num_ai = int(_get(co, "num_ai_companies", 2))
    if num_ai < 0 or num_ai > 14:
        _report(strict, problems, "num_ai_companies = %d is outside range [0, 14]", num_ai)

    # --- Max loan: must be positive ---
    max_loan = int(_get(co, "max_loan", 300000))
    if max_loan < 0:
        _report(strict, problems, "max_loan = %d must be non-negative", max_loan)

    # --- Timekeeping: units enum, and the mode-dependent range on the year ---
    if rt is not None:
        units = str(_get(rt, "timekeeping_units", "calendar"))
        if units not in ("calendar", "wallclock"):
            _report(
                strict, problems,
                "Unknown timekeeping_units value %r. Valid: calendar, wallclock", units,
            )
        minutes = int(_get(rt, "minutes_per_calendar_year", 12))
        # OpenTTD clamps this to exactly 12 in calendar mode; wallclock allows 0..10080.
        if units == "wallclock":
            if minutes < 0 or minutes > 10080:
                _report(
                    strict, problems,
                    "minutes_per_calendar_year = %d is outside the wallclock range [0, 10080]",
                    minutes,
                )
        elif minutes != 12:
            _report(
                strict, problems,
                "minutes_per_calendar_year = %d requires timekeeping_units = 'wallclock' "
                "(calendar mode is fixed at 12)", minutes,
            )

    # --- Fairness limits: ranges that keep a run comparable -----------------
    if fair is not None:
        # A floor below ~0.5s is not a pacing limit, it is a busy loop. The measured
        # slowest decide time is ~11s, so the upper bounds are generous.
        #
        # The cast happens inside the loop: doing it while building the checks made a
        # non-numeric value escape as a raw ValueError, which the CLI does not catch
        # because it expects ScenarioConfigError.
        checks = (
            ("poll_interval", float, 10.0, 0.5, 600.0),
            ("max_actions_per_cycle", int, 15, 1, 200),
            ("max_history_cycles", int, 10, 0, 1000),
            ("llm_timeout_seconds", float, 120.0, 1.0, 3600.0),
        )
        for name, cast, default, low, high in checks:
            raw = _get(fair, name, default)
            try:
                value = cast(raw)
            except (TypeError, ValueError):
                _report(
                    strict, problems,
                    "fairness.%s = %r is not a %s", name, raw, cast.__name__,
                )
                continue
            if not low <= value <= high:
                _report(
                    strict, problems,
                    "fairness.%s = %s is outside range [%s, %s]", name, value, low, high,
                )

        # observation_mode is not a fairness knob: a scored run always receives the
        # complete entitled game state and leaves filtering to the agent. Refuse it
        # here so an author is told rather than quietly overruled at runtime.
        if _get(fair, "observation_mode", None) is not None:
            _report(
                strict, problems,
                "fairness.observation_mode is not configurable: a scored run always "
                "observes fully and the agent filters. Remove the key.",
            )

    # --- Per-agent observation_mode: must name a real snapshot class ---------
    for i, agent in enumerate(agents or []):
        mode = _get(agent, "observation_mode", None) or _get(agent, "snapshot_class", None)
        if mode is not None and str(mode) not in _KNOWN_OBSERVATION_MODES:
            _report(
                strict, problems,
                "agents[%d].observation_mode = %r is not a known snapshot class. Valid: %s",
                i, mode, ", ".join(sorted(_KNOWN_OBSERVATION_MODES)),
            )

    if problems:
        raise ScenarioConfigError(
            f"{len(problems)} problem(s) in scenario config (strict mode): "
            + "; ".join(problems)
        )


def scenario_to_settings(cfg: ScenarioConfig, strict: bool = False) -> dict[str, str]:
    """Convert a ScenarioConfig to OpenTTD INI settings dict.

    Map and company values are read from the raw pyhocon ConfigTree.
    Returns key-value pairs baked into the per-session openttd.cfg.

    Args:
        cfg: The loaded scenario config.
        strict: Refuse an ill-specified config instead of substituting defaults.
            Use for scored runs -- see ``_validate_config``.

    Raises:
        ScenarioConfigError: In strict mode, if the config has no parsed tree or
            any value fails validation.
    """
    settings: dict[str, str] = {}
    raw = cfg._raw

    # If no raw config (defaults only), produce minimal settings
    if raw is None:
        if strict:
            raise ScenarioConfigError(
                "Scenario config has no parsed tree -- the file was missing or "
                "unparseable, so a scored run would silently use defaults"
            )
        return settings

    m = _get(raw, "map", {})
    co = _get(raw, "companies", {})

    _validate_config(
        m, co, strict=strict, rt=_get(raw, "runtime", {}),
        fair=_get(raw, "fairness", None), agents=_get(raw, "agents", None),
    )

    # Map dimensions (log2)
    settings["game_creation.map_x"] = str(_log2(int(_get(m, "size_x", 256))))
    settings["game_creation.map_y"] = str(_log2(int(_get(m, "size_y", 256))))

    # Landscape
    settings["game_creation.landscape"] = _LANDSCAPE_MAP.get(_get(m, "landscape", "temperate"), "0")

    # Terrain
    terrain = _get(m, "terrain_type", "flat")
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
    settings["game_creation.starting_year"] = str(int(_get(m, "starting_year", 1960)))

    # Map generation seed.
    #
    # This is written to the cfg for the record, but OpenTTD 15.3 does NOT pin
    # generation from the cfg key alone -- two servers sharing this value still
    # generate different maps. Reproducibility requires the -G flag at spawn,
    # which SessionRuntime.start_server reads from the _map_seed key below.
    seed = _get(m, "seed", None)
    if seed is not None:
        settings["game_creation.generation_seed"] = str(int(seed))
        settings["_map_seed"] = str(int(seed))

    # AI / company settings
    num_ai = int(_get(co, "num_ai_companies", 2))
    settings["difficulty.max_no_competitors"] = str(num_ai)
    settings["difficulty.competitors_interval"] = str(int(_get(co, "competitors_interval", 0)))
    max_loan = int(_get(co, "max_loan", 300000))
    if max_loan != 300000:
        settings["difficulty.max_loan"] = str(max_loan)

    # Fairness limits. Operator-owned, because they decide how much a contestant
    # may do: declared on AgentConfig they would let each contestant set their own
    # budget. Enforced only for a scored session -- see config/fairness.py.
    fair = _get(raw, "fairness", {})
    if fair:
        settings["_fair_poll_interval"] = str(float(_get(fair, "poll_interval", 10.0)))
        settings["_fair_max_actions"] = str(int(_get(fair, "max_actions_per_cycle", 15)))
        settings["_fair_max_history"] = str(int(_get(fair, "max_history_cycles", 10)))
        settings["_fair_llm_timeout"] = str(float(_get(fair, "llm_timeout_seconds", 120.0)))

    # Timekeeping. These are the only real pacing knobs and they apply at map
    # generation only -- see RuntimeConfig. They move the calendar clock, not the
    # economy clock, so they change when vehicles become available rather than how
    # fast cargo and money move.
    rt = _get(raw, "runtime", {})
    timekeeping = str(_get(rt, "timekeeping_units", "calendar"))
    settings["economy.timekeeping_units"] = "1" if timekeeping == "wallclock" else "0"
    settings["economy.minutes_per_calendar_year"] = str(
        int(_get(rt, "minutes_per_calendar_year", 12))
    )

    # Scenario identity. Carried through so the session can compute a task_id
    # without re-reading the config file.
    scenario_name = str(_get(raw, "name", "default"))
    settings["_scenario_id"] = str(_get(raw, "id", scenario_name))
    settings["_scenario_version"] = str(_get(raw, "version", "1"))
    if _get(raw, "scored", False):
        settings["_scored"] = "1"

    # nttd-internal runtime metadata (prefixed with _)
    settings["_runtime_mode"] = str(_get(rt, "mode", "async_realtime"))
    snapshot_interval = int(_get(rt, "snapshot_interval_days", 1))
    if snapshot_interval != 1:
        settings["_snapshot_interval_days"] = str(snapshot_interval)
    settings["_screenshot_interval_seconds"] = str(int(_get(rt, "screenshot_interval_seconds", 0)))
    settings["_screenshot_type"] = str(_get(rt, "screenshot_type", "minimap"))
    settings["_save_interval_seconds"] = str(int(_get(rt, "save_interval_seconds", 0)))

    # End conditions -- stored in settings so they can be applied at session start
    ec = _get(raw, "end_conditions", {})
    if ec:
        settings["_ec_logic"] = str(_get(ec, "logic", "any"))
        tl = _get(ec, "time_limit", {})
        if _get(tl, "enabled", False):
            settings["_ec_wall_minutes"] = str(float(_get(tl, "wall_minutes", 15)))
        gd = _get(ec, "game_date_limit", {})
        if _get(gd, "enabled", False):
            settings["_ec_end_year"] = str(int(_get(gd, "end_year", 2000)))
        rv = _get(ec, "revenue_threshold", {})
        if _get(rv, "enabled", False):
            settings["_ec_revenue"] = str(int(_get(rv, "total_revenue", 1000000)))
        ct = _get(ec, "cargo_threshold", {})
        if _get(ct, "enabled", False):
            settings["_ec_cargo"] = str(int(_get(ct, "total_cargo_delivered", 50000)))
        mh = _get(ec, "max_heartbeats", {})
        if _get(mh, "enabled", False):
            settings["_ec_max_heartbeats"] = str(int(_get(mh, "count", 1000)))
        bk = _get(ec, "bankruptcy", {})
        if _get(bk, "enabled", False):
            settings["_ec_bankruptcy"] = "1"

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
        bankruptcy=BankruptcyConfig(
            enabled=_get(ec_raw, "bankruptcy.enabled", False),
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
        timekeeping_units=str(_get(rt_raw, "timekeeping_units", "calendar")),
        minutes_per_calendar_year=int(_get(rt_raw, "minutes_per_calendar_year", 12)),
    )

    scenario_name = _get(s, "name", "default")
    return ScenarioConfig(
        name=scenario_name,
        description=_get(s, "description", ""),
        # id falls back to name so existing scenarios keep a stable identity
        # without every file needing an explicit id.
        id=str(_get(s, "id", scenario_name)),
        version=str(_get(s, "version", "1")),
        scored=bool(_get(s, "scored", False)),
        heartbeat=HeartbeatConfig(
            interval_days=int(_get(hb_raw, "interval_days", 30)),
            action_window_seconds=float(_get(hb_raw, "action_window_seconds", 5.0)),
            game_speed=int(_get(hb_raw, "game_speed", 1)),
        ),
        end_conditions=end_conditions,
        runtime=runtime,
        _raw=s,
    )
