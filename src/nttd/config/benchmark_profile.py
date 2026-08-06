"""The benchmark profile: which worlds a scored run may be played on, and how fast.

OpenTTD exposes enough generation knobs that two scored runs can face worlds with
nothing in common. Left free they do not produce a leaderboard, they produce a
collection of unrelated anecdotes: a run on a flat 128x128 map with many towns is
not the same task as one on a mountainous 1024x1024 map with few, and ranking them
in one table asserts a comparison that was never made.

So a scored scenario is limited to a profile with four parts:

  * LOCKED settings must hold exactly. These are the ones where a difference
    changes the problem without being visible to a reader of the board -- nobody
    scanning a score of 812 can tell it was earned with ``industry_density =
    high``. Pinning them is what makes the number mean anything.

  * ALLOWED settings may differ, within an enumerated set of values, because they
    are recorded as leaderboard columns. A reader can see that one run was 512x512
    mountainous and another 256x256 flat, and discount the comparison themselves.

  * An optional SCENARIO ALLOWLIST, empty by default, for when the board needs a
    fixed slate rather than open admission.

**The rules live in data, not here.** ``config/benchmark/profile.conf`` is the
authority; this module reads it. That is deliberate: which worlds a leaderboard
admits is operator policy that changes without any behaviour changing, so it must be
editable by hand and reviewable as a diff, not buried in a Python literal. The
constants below are a fallback for when the file is missing or unreadable, so a
checkout without it still refuses an obviously non-conforming scenario rather than
silently accepting everything.

A scored scenario need not restate the locked settings: omitting one means inheriting
it, and ``scenario_to_settings`` emits the profile's value. So there is exactly one
copy of the rules and nothing to drift.

Conformance is normally the whole credential. There is deliberately no registry of
blessed scenarios in the default posture: a curated list would have to enumerate
the 25 size/terrain combinations across four tiers before seeds, and would make
a legitimate conforming run look second-class purely because nobody added a row for
it. ``task_id`` -- derived from world content -- is what groups comparable runs.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROFILE_PATH = Path(__file__).resolve().parents[3] / "config" / "benchmark" / "profile.conf"

# Fallback values, used only when profile.conf cannot be read. Kept in step with the
# shipped file by a test, so the two cannot drift unnoticed.
_FALLBACK_LOCKED: dict[str, Any] = {
    "variety": "none",
    "smoothness": "smooth",
    "rivers": "medium",
    "sea_level": "medium",
    "map_edges": "random",
    "starting_year": 2020,
    "town_names": "english",
    "number_towns": "normal",
    "industry_density": "normal",
    "landscape": "temperate",
}

_FALLBACK_ALLOWED: dict[str, tuple[Any, ...]] = {
    "size": (64, 128, 256, 512, 1024),
    "terrain_type": ("very_flat", "flat", "hilly", "mountainous", "alpinist"),
}

# One allowed list governing both map axes, because a scored map must be square.
# Handled apart from the generic membership check: squareness is a relation between
# two settings, which a per-key list of permitted values cannot express.
SIZE_KEY = "size"
SIZE_FIELDS = ("size_x", "size_y")

# Locked settings recorded as result columns anyway. Landscape is locked today and
# expected to open up, and a free-play row should still say which world it was, so
# leaving the column permanently empty would lose information for no gain.
REPORTED_LOCKED = ("landscape",)


# Prefix for the emitted display copies of the allowed dimensions. These are
# projections of settings already carried as game_creation.* and difficulty.*, kept
# in readable form so a leaderboard column reads "mountainous" rather than "3".
# Excluded from task_id: identity comes from the real OpenTTD settings, and must not
# shift because a display copy was reformatted or a dimension was added.
DIMENSION_PREFIX = "_dim_"

_VERSION_LENGTH = 12


class BenchmarkProfile:
    """The loaded admission rules for scored scenarios.

    Attributes:
        locked: Settings that must match exactly.
        allowed: Settings that may vary, mapped to their permitted values.
        scenario_allowlist: Scenario ids permitted to be scored. Empty means any
            conforming scenario may be, which is the default.
        source: Where the rules came from, for diagnostics.
    """

    def __init__(
        self,
        locked: dict[str, Any],
        allowed: dict[str, tuple[Any, ...]],
        scenario_allowlist: tuple[str, ...] = (),
        source: str = "",
    ) -> None:
        self.locked = locked
        self.allowed = allowed
        self.scenario_allowlist = scenario_allowlist
        self.source = source

    @property
    def version(self) -> str:
        """A digest of the rules, recorded in every result.

        Derived rather than declared. A hand-written version number has to be
        remembered, and the one time it is not, two runs admitted under different
        rules appear equally comparable. Hashing the rules themselves means the
        recorded version changes exactly when the rules do.
        """
        payload = json.dumps(
            {
                "locked": {key: str(value) for key, value in sorted(self.locked.items())},
                "allowed": {
                    key: [str(v) for v in values]
                    for key, values in sorted(self.allowed.items())
                },
            },
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:_VERSION_LENGTH]

    @property
    def variable_settings(self) -> frozenset[str]:
        """Which settings may vary. Exactly the allowed keys, because being
        disclosed as a leaderboard column is the condition on which a setting is
        permitted to differ."""
        return frozenset(self.allowed)

    @property
    def reported_settings(self) -> tuple[str, ...]:
        """Scenario fields recorded as result columns, in a stable order.

        The allowed keys, since disclosure is what permits them to vary, with two
        adjustments: ``size`` expands to the two axes a scenario actually writes, and
        the locked settings in REPORTED_LOCKED are included because a row should say
        which world it was even when the value was not the contestant's choice.
        """
        keys: list[str] = []
        for key in sorted(self.allowed):
            keys.extend(SIZE_FIELDS if key == SIZE_KEY else [key])
        for key in REPORTED_LOCKED:
            if key not in keys:
                keys.append(key)
        return tuple(keys)

    def _size_problems(self, map_cfg: Any, get: Any) -> list[str]:
        """Check both map axes against the one size list, and require them equal."""
        permitted = self.allowed.get(SIZE_KEY)
        if not permitted:
            return []

        problems: list[str] = []
        values: dict[str, Any] = {}
        for field in SIZE_FIELDS:
            actual = get(map_cfg, field, None)
            if actual is None:
                continue
            values[field] = actual
            if not any(_matches(actual, candidate) for candidate in permitted):
                rendered = ", ".join(str(value) for value in permitted)
                problems.append(
                    f"map.{field} = {actual!r} is not allowed for a scored run. "
                    f"Choose one of: {rendered}."
                )

        if len(values) == 2 and not _matches(values["size_x"], _as_int(values["size_y"])):
            problems.append(
                f"map.size_x = {values['size_x']!r} and map.size_y = "
                f"{values['size_y']!r} differ: a scored map must be square. Rectangles "
                f"only vary the aspect ratio, so they would multiply the board by 5 "
                f"without adding a distinct problem. Set both to the same value, or "
                f"drop scored = true to play it freely."
            )
        return problems

    def deviations(self, map_cfg: Any, get: Any, scenario_id: str = "") -> list[str]:
        """Return a human-readable problem per profile violation.

        Args:
            map_cfg: The scenario's ``map`` config tree.
            get: A dot-path reader for the tree, so this module does not depend on
                pyhocon or duplicate the traversal in ``scenario_config``.
            scenario_id: The scenario's declared id, checked against the allowlist
                when one is configured.

        Returns:
            One message per violation, empty when the profile holds. Every violation
            rather than the first, so an author can fix a config in one pass.
        """
        problems: list[str] = []

        for key, required in self.locked.items():
            # The default is the required value: a scored scenario that omits the key
            # inherits the profile rather than being refused for silence, and
            # scenario_to_settings emits the same value.
            actual = get(map_cfg, key, required)
            if not _matches(actual, required):
                problems.append(
                    f"map.{key} = {actual!r} is fixed at {required!r} for a scored "
                    f"run. Remove the key to inherit it, or drop scored = true to "
                    f"play it freely."
                )

        problems.extend(self._size_problems(map_cfg, get))

        for key, allowed in self.allowed.items():
            if key == SIZE_KEY:
                continue
            actual = get(map_cfg, key, None)
            if actual is None:
                # Omitted entirely. scenario_to_settings supplies OpenTTD's own
                # default, which is in range, so silence is conformance here too.
                continue
            if not any(_matches(actual, candidate) for candidate in allowed):
                rendered = ", ".join(str(value) for value in allowed)
                problems.append(
                    f"map.{key} = {actual!r} is not allowed for a scored run. "
                    f"Choose one of: {rendered}."
                )

        if self.scenario_allowlist and scenario_id not in self.scenario_allowlist:
            # Quote the list back rather than just refusing: an author who hits a
            # temporary slate restriction needs to know what IS admitted.
            rendered = ", ".join(self.scenario_allowlist)
            problems.append(
                f"scenario id {scenario_id!r} is not on the scored allowlist. "
                f"Currently admitted: {rendered}. Edit "
                f"config/benchmark/profile.conf to change this, or drop "
                f"scored = true to play it freely."
            )

        return problems


def _as_int(value: Any) -> Any:
    """Coerce a config value to int when it looks like one, for numeric comparison."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


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



def load_profile(path: Path | str | None = None) -> BenchmarkProfile:
    """Read the profile from HOCON, falling back to the built-in values.

    A missing or unparseable file falls back rather than raising: refusing every
    scored run because a policy file has a typo would be a worse failure than
    applying the last known-good rules and saying so loudly.
    """
    profile_path = Path(path) if path else PROFILE_PATH
    fallback = BenchmarkProfile(
        locked=dict(_FALLBACK_LOCKED),
        allowed=dict(_FALLBACK_ALLOWED),
        source="built-in fallback",
    )

    if not profile_path.exists():
        logger.warning(
            "Benchmark profile not found at %s -- using built-in rules. Scored runs "
            "are still validated, but the operator cannot adjust them without it.",
            profile_path,
        )
        return fallback

    try:
        from pyhocon import ConfigFactory

        raw = ConfigFactory.parse_file(str(profile_path))
        node = raw.get("profile", raw)

        locked = dict(node.get("locked", {}))
        allowed = {
            key: tuple(value) for key, value in dict(node.get("allowed", {})).items()
        }
        if not locked or not allowed:
            raise ValueError("profile.conf must define both locked and allowed")

        return BenchmarkProfile(
            locked=locked,
            allowed=allowed,
            scenario_allowlist=tuple(str(x) for x in node.get("scenario_allowlist", [])),
            source=str(profile_path),
        )
    except Exception:
        logger.exception(
            "Could not read the benchmark profile at %s -- using built-in rules. "
            "Fix the file: until then, edits to it have no effect.",
            profile_path,
        )
        return fallback


# Loaded once at import. The profile is operator policy that changes between runs of
# the server, not during one, so re-reading per validation would add a file read to
# every session start for no benefit.
_PROFILE = load_profile()


def active_profile() -> BenchmarkProfile:
    """The profile in force. Prefer this over the module-level aliases below."""
    return _PROFILE


# Module-level aliases, kept because callers and tests read them directly and
# because they make the active rules greppable.
LOCKED_SETTINGS: dict[str, Any] = _PROFILE.locked
ALLOWED_RANGES: dict[str, tuple[Any, ...]] = _PROFILE.allowed
VARIABLE_SETTINGS: frozenset[str] = _PROFILE.variable_settings
REPORTED_SETTINGS: tuple[str, ...] = _PROFILE.reported_settings
PROFILE_VERSION: str = _PROFILE.version


def dimensions_from_settings(settings: dict[str, str]) -> dict[str, str]:
    """Extract the readable allowed dimensions from a session's settings.

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


def deviations(map_cfg: Any, get: Any, scenario_id: str = "") -> list[str]:
    """Return profile violations for a scored scenario. See BenchmarkProfile."""
    return _PROFILE.deviations(map_cfg, get, scenario_id)
