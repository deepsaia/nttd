"""Loads and exposes the scenario HOCON config as typed dataclasses.

Map/company settings are read directly from the pyhocon ConfigTree --
no dataclasses needed since they're only used to produce OpenTTD INI values.
Runtime, heartbeat, and end-condition configs use dataclasses because they're
passed around as typed objects in the orchestrator and end-condition checker.

If pyhocon is not installed or the config file is missing, returns safe defaults
so the server can start without a config file present.
"""
import functools
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nttd import resources
from nttd.config.benchmark_profile import (
    DIMENSION_PREFIX,
    LOCKED_SETTINGS,
    PROFILE_VERSION,
    REPORTED_SETTINGS,
)
from nttd.config.benchmark_profile import deviations as profile_deviations

logger = logging.getLogger(__name__)

# A shipped benchmark example rather than a free-play file. The gameloop-era
# configs it used to point at named per-agent models and an observation_mode, so
# the default was a scenario nttd could no longer honour.
# The world a scenario inherits when it says nothing. Named once because the emitted
# OpenTTD setting and the recorded dimension must agree: the dimension loop read the
# raw tree while the setting applied a default, so a free-play scenario that omitted
# landscape generated a temperate world and then recorded no landscape at all.
_MAP_DEFAULTS: dict[str, Any] = {
    "size_x": 256,
    "size_y": 256,
    "landscape": "temperate",
    "terrain_type": "flat",
}

_DEFAULT_CONFIG_PATH = resources.scenario_config("t2_256_flat_1001_realtime.conf")

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

# Runtime modes the orchestrator can actually start. Kept here rather than
# imported from schemas.game so config validation does not depend on runtime
# state; a test asserts the two agree.
_KNOWN_RUNTIME_MODES: frozenset[str] = frozenset({
    "async_realtime", "heartbeat", "stepped",
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

    ``id`` identifies the task independently of the file path, so a result stays
    traceable to the exact problem it was scored on. It defaults to ``name``.

    There is no scenario version. It was a number an author had to remember to bump,
    and it duplicated work ``settings_digest`` already does: any edit that should
    invalidate a comparison changes the settings, which changes the digest, which
    changes the task_id. A version that only distinguishes two scenarios with
    identical settings distinguishes nothing.
    """

    name: str = "default"
    description: str = ""
    id: str = ""
    # Computed from the world by resolve_scored, never read from the file as a fact.
    # When true the session refuses game-mutating operator operations for its whole
    # life, for every caller: a self-hosting contestant holds every credential, so
    # session state is the only boundary that means anything.
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


def _compute_water_borders(map_cfg: Any, edges: str = "") -> str:
    """Compute OpenTTD water_borders bitmask from the map config tree.

    ``edges`` may be passed in when the caller has already resolved it against the
    benchmark profile, so a scored run that omits map_edges gets the profile value
    rather than this function's own default.
    """
    edges = edges or _get(map_cfg, "map_edges", "random")
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
    scored: bool = False, scenario_id: str = "", ec: Any = None,
    conformance: list[str] | None = None,
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
        ec: The ``end_conditions`` config tree, if present. Needed because
            which bounds make sense depends on the runtime mode.
        fair: The ``fairness`` config tree, if present.
        scored: Whether the scenario is scored, which additionally holds the map
            to the benchmark profile.

    Raises:
        ScenarioConfigError: In strict mode, if any problem was found.
    """
    problems: list[str] = []

    # --- Benchmark profile: a scored world may not be arbitrary ---------------
    # Reported only when the author ASSERTED scored = true over a world that breaks
    # the profile. A scenario that merely does not conform is free play, not an error:
    # scoredness is computed from the world, so silence is an answer rather than a
    # mistake. See resolve_scored.
    for problem in conformance or []:
        _report(strict, problems, "%s", problem)

    # --- Enum validation ---
    _enum_checks: list[tuple[str, dict[str, str], Any]] = [
        ("landscape", _LANDSCAPE_MAP, _get(m, "landscape", _MAP_DEFAULTS["landscape"])),
        ("terrain_type", _TERRAIN_MAP, _get(m, "terrain_type", _MAP_DEFAULTS["terrain_type"])),
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
    terrain = _get(m, "terrain_type", _MAP_DEFAULTS["terrain_type"])
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

    # --- Runtime mode, and what may bound a run in it ------------------------
    if rt is not None:
        mode = str(_get(rt, "mode", "async_realtime"))
        if mode not in _KNOWN_RUNTIME_MODES:
            _report(
                strict, problems,
                "Unknown runtime.mode value %r. Valid: %s",
                mode, ", ".join(sorted(_KNOWN_RUNTIME_MODES)),
            )
        # A stepped run pauses between steps so a policy may deliberate for as long
        # as it likes. Wall time therefore measures how slow the contestant's
        # hardware is, not how much of the game was played, and ending on it would
        # cut off a slow policy mid-run. max_heartbeats is the bound that means
        # something when the clock only moves on request.
        # Default True, matching TimeLimitConfig: a scenario that omits time_limit
        # still loads with it ENABLED at 60 minutes. Reading it as False here meant a
        # stepped scenario that simply said nothing passed validation and then ran
        # under a wall clock anyway.
        elif mode == "stepped" and ec is not None and _get(ec, "time_limit.enabled", True):
            _report(
                strict, problems,
                "runtime.mode = 'stepped' with end_conditions.time_limit enabled: a "
                "stepped run pauses between steps, so wall time measures the "
                "contestant's hardware rather than the run. Bound it with "
                "end_conditions.max_heartbeats instead.",
            )

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

    # --- fairness: not a scenario concern --------------------------------------
    # These decide how much a contestant may do, so they belong to the operator, not
    # to whoever wrote the scenario. They live in config/benchmark/profile.conf.
    # Refused rather than ignored, so an author is told rather than silently overruled.
    if fair is not None:
        _report(
            strict, problems,
            "scenario fairness { ... } is not read: how much a contestant may do is "
            "operator policy, set in config/benchmark/profile.conf. Remove the block.",
        )

    if problems:
        raise ScenarioConfigError(
            f"{len(problems)} problem(s) in scenario config (strict mode): "
            + "; ".join(problems)
        )


def _locked_aware_get(map_cfg: Any, scored: bool, key: str, fallback: Any) -> Any:
    """Read a map setting, preferring the profile's locked value for a scored run.

    Module level rather than nested in scenario_to_settings, and bound with
    functools.partial at the call site.

    Validation treats an omitted locked setting as conformance, so without this the
    two disagreed: a scored scenario that left out starting_year passed validation and
    then generated a 1960 world while its record claimed profile conformance.
    """
    if scored and key in LOCKED_SETTINGS:
        return _get(map_cfg, key, LOCKED_SETTINGS[key])
    return _get(map_cfg, key, fallback)


def resolve_scored(raw: Any, map_cfg: Any, scenario_id: str) -> tuple[bool, list[str]]:
    """Decide whether a run is scoreable by checking the world, not by reading a flag.

    ``scored = true`` is an assertion an author can make about their own config, which
    makes it worth nothing on its own: anyone can write it above a world the profile
    would never admit. So conformance is computed from the config and the flag can only
    ever narrow the answer:

      * absent    -- scored if and only if the world conforms to the profile.
      * ``false`` -- never scored. An opt-out, always honoured, for when you want to
        play a conforming world with operator powers available.
      * ``true``  -- an assertion of conformance. Honoured when it holds, and refused
        when it does not, because an author who wrote it clearly meant to produce a
        benchmark run and needs to hear that the world is wrong rather than get a
        quietly unscored one.

    Returns:
        ``(scored, problems)``. ``problems`` holds the profile deviations, non-empty
        only when the author asserted ``scored = true`` over a world that breaks them,
        so the caller can report them; a scenario that simply does not conform is free
        play rather than an error.
    """
    deviations = profile_deviations(map_cfg, _get, scenario_id)
    conforms = not deviations
    declared = _get(raw, "scored", None)

    if declared is not None and not bool(declared):
        return False, []
    if declared is not None and bool(declared) and not conforms:
        return False, deviations
    return conforms, []


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

    # Resolved before validation because the allowlist is checked against it. Falls
    # back to name, matching how _scenario_id is emitted below.
    scenario_name = str(_get(raw, "name", "default"))
    scenario_id = str(_get(raw, "id", scenario_name))

    # Computed from the world, not read from a flag. See resolve_scored.
    scored, conformance = resolve_scored(raw, m, scenario_id)
    _validate_config(
        m, co, strict=strict, rt=_get(raw, "runtime", {}),
        fair=_get(raw, "fairness", None),
        scored=scored, scenario_id=scenario_id,
        ec=_get(raw, "end_conditions", None),
        conformance=conformance,
    )

    # For a scored run, an omitted locked setting takes the profile's value rather
    # than this module's own default. Validation already treats omission as
    # conformance, so without this the two disagreed: a scored scenario that left
    # out starting_year passed validation and then generated a 1960 world while its
    # record claimed profile conformance.
    _map = functools.partial(_locked_aware_get, m, scored)

    # Map dimensions (log2)
    settings["game_creation.map_x"] = str(_log2(int(_get(m, "size_x", _MAP_DEFAULTS["size_x"]))))
    settings["game_creation.map_y"] = str(_log2(int(_get(m, "size_y", _MAP_DEFAULTS["size_y"]))))

    # Landscape
    settings["game_creation.landscape"] = _LANDSCAPE_MAP.get(_get(m, "landscape", _MAP_DEFAULTS["landscape"]), "0")

    # Terrain
    terrain = _get(m, "terrain_type", _MAP_DEFAULTS["terrain_type"])
    settings["difficulty.terrain_type"] = _TERRAIN_MAP.get(terrain, "1")
    if terrain == "custom":
        settings["game_creation.custom_terrain_type"] = str(int(_get(m, "custom_terrain_height", 30)))

    # Variety and smoothness
    settings["game_creation.variety"] = _VARIETY_MAP.get(_map("variety", "none"), "0")
    settings["game_creation.tgen_smoothness"] = _SMOOTHNESS_MAP.get(
        _map("smoothness", "smooth"), "1",
    )

    # Water
    settings["game_creation.amount_of_rivers"] = _RIVERS_MAP.get(_map("rivers", "medium"), "2")
    sea_level = _map("sea_level", "medium")
    settings["difficulty.quantity_sea_lakes"] = _SEA_LEVEL_MAP.get(sea_level, "2")
    if sea_level == "custom":
        settings["game_creation.custom_sea_level"] = str(int(_get(m, "custom_sea_level", 1)))
    settings["game_creation.water_borders"] = _compute_water_borders(
        m, _map("map_edges", "random"),
    )

    # Towns
    settings["game_creation.town_name"] = _TOWN_NAMES_MAP.get(
        _map("town_names", "english"), "0",
    )
    num_towns = _map("number_towns", "normal")
    settings["difficulty.number_towns"] = _TOWNS_MAP.get(num_towns, "2")
    if num_towns == "custom":
        settings["game_creation.custom_town_number"] = str(int(_get(m, "custom_town_number", 1)))

    # Industries
    industry = _map("industry_density", "normal")
    settings["difficulty.industry_density"] = _INDUSTRY_MAP.get(industry, "4")
    if industry == "custom":
        settings["game_creation.custom_industry_number"] = str(int(_get(m, "custom_industry_number", 1)))

    # Start date
    settings["game_creation.starting_year"] = str(int(_map("starting_year", 1960)))

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
    # without re-reading the config file. Resolved above, before validation, because
    # the profile's optional allowlist is checked against it.
    settings["_scenario_id"] = scenario_id
    if scored:
        settings["_scored"] = "1"
        # Which profile admitted the run. Recorded rather than assumed, so a result
        # stays readable after the rules in config/benchmark/profile.conf change:
        # two runs under different profile versions are not comparable, and the
        # record says so.
        settings["_profile_version"] = PROFILE_VERSION

    # The dimensions a scored scenario is allowed to vary, emitted so the result
    # record can carry them as leaderboard columns -- they are what lets a reader
    # judge whether two runs are comparable, which is the whole reason they are
    # permitted to differ rather than locked.
    #
    # A distinct "_dim_" prefix rather than "_map_", for two reasons: "_map_seed" is
    # a load-bearing key that SessionRuntime reads for the -G flag, and these are
    # display projections of settings already emitted as game_creation.* and
    # difficulty.*. The projection is excluded from task_id, since an identity hash
    # must not depend on the format of a display copy.
    for key in REPORTED_SETTINGS:
        # _map, not _get: a scored scenario that inherits a locked setting must still
        # record it. Reading the raw tree left the column empty for exactly the
        # scenarios that were most conformant, so a T3 example that omitted landscape
        # reported no landscape at all.
        value = _map(key, _MAP_DEFAULTS.get(key))
        if value is not None:
            settings[f"{DIMENSION_PREFIX}{key}"] = str(value)

    # nttd-internal runtime metadata (prefixed with _)
    settings["_runtime_mode"] = str(_get(rt, "mode", "async_realtime"))
    snapshot_interval = int(_get(rt, "snapshot_interval_days", 1))
    if snapshot_interval != 1:
        settings["_snapshot_interval_days"] = str(snapshot_interval)
    # Game-days per step. Carried through because the orchestrator otherwise keeps
    # its 30-day default: a scenario asking for 15 silently got 30, so every step
    # covered twice the intended world and the run hit its horizon in half the
    # steps. The scenario owns the step size, so it has to reach the runtime.
    hb = _get(raw, "heartbeat", {})
    settings["_heartbeat_interval_days"] = str(int(_get(hb, "interval_days", 30)))
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
    """Load scenario config from a HOCON file.

    Defaults when NO path is given, which is the ordinary way to start a free-play session.
    Raises when a path IS given and cannot be read, because the two cases want opposite
    treatment and were being handled the same way.

    Falling back silently on a named path is the worst outcome available. A mistyped path
    produced a session that announced itself as created from that file and was in fact a
    60 minute async_realtime run on a RANDOM seed: unscored, unreproducible, and
    indistinguishable at a glance from the benchmark that was asked for. Measured with
    --config /tmp/definitely_not_here.conf, which reported "Seed: random (not
    reproducible)" under the path it had just failed to open.
    """
    if config_path is None:
        path = _DEFAULT_CONFIG_PATH
        if not path.exists():
            logger.info("No scenario config at %s -- using defaults", path)
            return ScenarioConfig()
    else:
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(
                f"scenario config not found: {path}. A named config that cannot be read is "
                f"refused rather than replaced with defaults, because the defaults are a "
                f"random seed and a different runtime mode."
            )

    try:
        from pyhocon import ConfigFactory  # type: ignore[import-untyped]
        raw = ConfigFactory.parse_file(str(path))
        s = raw.get("scenario", raw)
    except ImportError:
        logger.warning("pyhocon not installed -- using default scenario config")
        return ScenarioConfig()
    except Exception as failure:
        if config_path is not None:
            raise ValueError(
                f"scenario config at {path} could not be parsed: {failure}"
            ) from failure
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
        # Computed, not read: the same rule scenario_to_settings applies, so the
        # dataclass and the emitted settings cannot disagree about whether a run is
        # scoreable. See resolve_scored.
        scored=resolve_scored(
            s, _get(s, "map", {}), str(_get(s, "id", scenario_name)),
        )[0],
        heartbeat=HeartbeatConfig(
            interval_days=int(_get(hb_raw, "interval_days", 30)),
            action_window_seconds=float(_get(hb_raw, "action_window_seconds", 5.0)),
            game_speed=int(_get(hb_raw, "game_speed", 1)),
        ),
        end_conditions=end_conditions,
        runtime=runtime,
        _raw=s,
    )
