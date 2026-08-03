"""The benchmark profile: which worlds a scored run may be played on.

OpenTTD exposes enough generation knobs that two scored runs can face worlds with
nothing in common. Left free they do not produce a leaderboard, they produce a
collection of unrelated anecdotes: a run on a flat 128x128 map with many towns is
not the same task as one on a mountainous 1024x1024 map with few, and ranking them
in one table asserts a comparison that was never made.

So a scored scenario is limited to this profile. Three categories:

  * LOCKED settings must hold exactly. These are the ones where a difference
    changes the problem without being visible to a reader of the board -- nobody
    scanning a score of 812 can tell it was earned with ``industry_density =
    high``. Pinning them is what makes the number mean anything.

  * RANGED settings may differ, within an enumerated set of values, because they
    are recorded as leaderboard columns. A reader can see that one run was 512x512
    mountainous and another 256x256 flat, and discount the comparison themselves.
    Map size, landscape, and terrain are the axes a player most wants to choose,
    and disclosure costs less than prohibition here.

  * Everything else in a ``map`` block is free, because the locked settings already
    fix it or OpenTTD ignores it.

Conformance is the whole credential. There is deliberately no registry of blessed
scenarios: a curated list would have to enumerate roughly 4,700 size/landscape/
terrain/tier combinations before seeds, and would make a legitimate conforming run
look second-class purely because nobody added a row for it. Any scenario that is
scored and within these ranges is comparable to any other run of the same task, and
``task_id`` -- derived from world content -- is what groups those runs.

The ranges are enumerations rather than bounds because every one of these settings
is an enum or a power of two in OpenTTD. An enumeration also refuses
``terrain_type = "custom"``, which would otherwise unlock ``custom_terrain_height``
over 1..255: an unbounded world axis that is not one of the disclosed columns, so
two runs could differ enormously while their leaderboard rows read identically.
"""

from __future__ import annotations

from typing import Any

# Settings a scored scenario must not change. Values are the HOCON spellings an
# author writes, not the OpenTTD integers, so a rejection names what is in the file.
LOCKED_SETTINGS: dict[str, Any] = {
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

# Map dimensions a scored scenario may choose. OpenTTD accepts powers of two from
# 64 to 4096; the top two are excluded because observation is always the full
# entitled game state, and a 2048x2048 map is 16x the tiles of 1024x1024. That
# turns each observation into a payload no contestant can reason over and no
# reviewer can store, which is a different problem from the one being posed.
ALLOWED_MAP_SIZES: tuple[int, ...] = (64, 128, 256, 512, 1024)

# The permitted value sets for the settings that may vary. Enumerated rather than
# bounded so a new OpenTTD enum member is refused until someone decides it belongs.
ALLOWED_RANGES: dict[str, tuple[Any, ...]] = {
    "size_x": ALLOWED_MAP_SIZES,
    "size_y": ALLOWED_MAP_SIZES,
    # All four are genuinely different economies, not cosmetic reskins: cargo
    # chains, town growth requirements, and available industries all differ.
    "landscape": ("temperate", "sub-arctic", "sub-tropical", "toyland"),
    # "custom" is deliberately absent -- see the module docstring.
    "terrain_type": ("very_flat", "flat", "hilly", "mountainous", "alpinist"),
}

# The dimensions recorded as leaderboard columns. Exactly the ranged settings,
# because being disclosed is the condition on which they are allowed to differ.
VARIABLE_SETTINGS: frozenset[str] = frozenset(ALLOWED_RANGES)

# Written into the session settings so the result record can state which profile a
# run was held to. Bump when LOCKED_SETTINGS or ALLOWED_RANGES changes, since
# results either side of such a change are not comparable.
PROFILE_VERSION = "1"

# Prefix for the emitted display copies of the ranged dimensions. These are
# projections of settings already carried as game_creation.* and difficulty.*, kept
# in readable form so a leaderboard column reads "mountainous" rather than "3".
# Excluded from task_id: identity comes from the real OpenTTD settings, and must not
# shift because a display copy was reformatted or a dimension was added here.
DIMENSION_PREFIX = "_dim_"


def dimensions_from_settings(settings: dict[str, str]) -> dict[str, str]:
    """Extract the readable ranged dimensions from a session's settings.

    Reads the ``_dim_*`` keys emitted by ``scenario_to_settings``, so both session
    start and crash recovery derive them the same way rather than one path
    reconstructing them from the OpenTTD integers.

    Includes ``profile_version`` when present, since a reader needs to know which
    ruleset produced the dimensions alongside the dimensions themselves.
    """
    dims = {
        key[len(DIMENSION_PREFIX):]: value
        for key, value in settings.items()
        if key.startswith(DIMENSION_PREFIX)
    }
    profile = settings.get("_profile_version")
    if profile:
        dims["profile_version"] = profile
    return dims


def deviations(map_cfg: Any, get: Any) -> list[str]:
    """Return a human-readable problem per profile violation.

    Checks both categories: a locked setting that does not match, and a ranged
    setting outside its permitted values.

    Args:
        map_cfg: The scenario's ``map`` config tree.
        get: A dot-path reader for the tree, so this module does not depend on
            pyhocon or duplicate the traversal already written in
            ``scenario_config``.

    Returns:
        One message per violation, empty when the profile holds. Returning every
        violation rather than the first lets an author fix a config in one pass.
    """
    problems: list[str] = []

    for key, required in LOCKED_SETTINGS.items():
        # The default is the required value: a scored scenario that omits the key
        # inherits the profile rather than being refused for silence. That is what
        # makes the shared defaults file worth including.
        actual = get(map_cfg, key, required)
        if not _matches(actual, required):
            problems.append(
                f"map.{key} = {actual!r} is fixed at {required!r} for a scored run. "
                f"Include config/benchmark/defaults.conf, or drop scored = true to "
                f"play it freely."
            )

    for key, allowed in ALLOWED_RANGES.items():
        actual = get(map_cfg, key, None)
        if actual is None:
            # Omitted entirely. scenario_to_settings supplies OpenTTD's own default,
            # which is within range, so silence is conformance here too.
            continue
        if not any(_matches(actual, candidate) for candidate in allowed):
            rendered = ", ".join(str(value) for value in allowed)
            problems.append(
                f"map.{key} = {actual!r} is not allowed for a scored run. "
                f"Choose one of: {rendered}."
            )

    return problems


def _matches(actual: Any, expected: Any) -> bool:
    """Compare a config value against an expected one, numerically when relevant.

    HOCON hands back an int for ``256`` and a str for ``"256"``, and an author may
    reasonably write either, so a purely textual comparison would refuse a
    conforming config.
    """
    if isinstance(expected, int) and not isinstance(expected, bool):
        try:
            return int(actual) == expected
        except (TypeError, ValueError):
            return False
    return str(actual) == str(expected)
