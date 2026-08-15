"""The two reporting faults that made connect_rail fail whenever it succeeded.

connect_rail builds a line and then says whether the line is whole. Both halves of that
sentence were wrong at once, and they compounded into a command that could not report a
good result at all:

1. The gap check asked AreTilesConnected about the FIRST segment by passing that tile as
   its own predecessor. That asks whether a train can enter a tile from itself, which is
   always false, so every route ever built reported a gap it did not have and every call
   came back "partial".

2. Because nothing was ever "complete", the partial-reason builder ran on every call. It
   read failed[0] with no length check. A route whose segments all built cleanly has an
   EMPTY failed list, so the index threw, the dispatcher's catch swallowed it, and the
   caller was told "the index '0' does not exist".

Together: a messy build returned a result, a clean build raised. Measured on a clear
corridor, connect_rail answered with that index error and no result at all, while the
track it had just laid sat there unreported.

These read the GameScript source because the logic lives in Squirrel. They assert the
guards are present, which is what the regression removed.
"""

from __future__ import annotations

from tests.conftest import REPO_ROOT

GAMESCRIPT = REPO_ROOT / "ottd_config" / "game" / "nttd-gs" / "main.nut"


def _function_body(name: str) -> str:
    """The source of one Squirrel function, from its header to the next one."""
    source = GAMESCRIPT.read_text()
    start = source.index(f"function {name}(")
    rest = source[start + 1 :]
    end = rest.find("\n  function ")
    return rest if end == -1 else rest[:end]


def test_the_partial_reason_checks_the_list_before_indexing_it() -> None:
    """The crash itself: failed[0] on a clean build, where failed is empty."""
    body = _function_body("_PartialError")
    guard = body.index("failed.len() > 0")
    index = body.index("failed[0]")
    assert guard < index, "failed[0] must be reached only after a length check"


def test_a_clean_build_with_gaps_still_gets_a_reason() -> None:
    """The case that used to raise has to produce a sentence instead."""
    body = _function_body("_PartialError")
    assert "gaps" in body
    assert "gaps.len() > 0" in body


def test_the_gap_check_never_uses_a_tile_as_its_own_predecessor() -> None:
    """AreTilesConnected asks about the middle of a triple, so the first segment has no
    honest answer and is skipped rather than guessed at."""
    body = _function_body("_RouteGaps")
    assert "i < 2" in body, "the first rail segment must be skipped, not fabricated"
    assert "path[i - 2].tile, a, b" in body


def test_the_road_gap_check_stays_pairwise() -> None:
    """Road connectivity is a two tile question and was never affected by any of this."""
    body = _function_body("_RouteGaps")
    assert "GSRoad.AreRoadTilesConnected(a, b)" in body
