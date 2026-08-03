"""The benchmark profile: which world settings a scored run may choose.

OpenTTD exposes enough generation knobs that two scored runs can face worlds with
nothing in common. Left free they do not produce a leaderboard, they produce a
collection of unrelated anecdotes: a run on a flat 128x128 map with many towns is
not the same task as one on a mountainous 1024x1024 map with few, and ranking them
in one table asserts a comparison that was never made.

So a scored scenario is limited to this profile. Two categories, and the
distinction matters:

  * LOCKED settings must hold exactly. They are the ones where a difference
    changes the problem without being visible to a reader of the board -- nobody
    scanning a score of 812 can tell it was earned with ``industry_density =
    high``. Pinning them is what makes the number mean anything.

  * VARIABLE settings may differ between scored scenarios, because they are
    recorded as leaderboard columns. A reader can see that one run was 512x512
    mountainous and another 256x256 flat, and discount the comparison themselves.
    Map size, landscape, and terrain are the axes a player most wants to choose,
    and disclosure costs less than prohibition here.

Free play is not restricted at all. A scenario without ``scored = true`` may set
anything: scenario authoring, debugging, and ordinary play have no comparability
to protect.

The water_borders_* flags are absent deliberately. OpenTTD ignores them unless
``map_edges = "manual"``, so locking ``map_edges = "random"`` already fixes the
edges, and listing the four flags as well would imply they do something.
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

# Settings a scored scenario may vary, because each is a leaderboard column.
# Keeping this list explicit rather than deriving it as "everything else" means a
# newly added map key defaults to being refused rather than silently permitted.
VARIABLE_SETTINGS: frozenset[str] = frozenset({
    "size_x", "size_y", "landscape", "terrain_type",
})

# Written into the session settings so the result record can state which profile a
# run was held to. Bump when LOCKED_SETTINGS changes, since results either side of
# such a change are not comparable.
PROFILE_VERSION = "1"


def deviations(map_cfg: Any, get: Any) -> list[str]:
    """Return a human-readable problem per locked setting that does not match.

    Args:
        map_cfg: The scenario's ``map`` config tree.
        get: A dot-path reader for the tree, so this module does not depend on
            pyhocon or duplicate the traversal already written in
            ``scenario_config``.

    Returns:
        One message per deviation, empty when the profile holds. Returning every
        deviation rather than the first lets an author fix a config in one pass.
    """
    problems: list[str] = []
    for key, required in LOCKED_SETTINGS.items():
        # The default is the required value: a scored scenario that omits the key
        # inherits the profile rather than being refused for silence. That is what
        # makes the shared defaults file worth including.
        actual = get(map_cfg, key, required)
        if isinstance(required, int) and not isinstance(required, bool):
            try:
                matches = int(actual) == required
            except (TypeError, ValueError):
                matches = False
        else:
            matches = str(actual) == str(required)
        if not matches:
            problems.append(
                f"map.{key} = {actual!r} is fixed at {required!r} for a scored run. "
                f"Include config/benchmark/defaults.conf, or drop scored = true to "
                f"play it freely."
            )
    return problems
