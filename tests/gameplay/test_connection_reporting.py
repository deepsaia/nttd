"""Partial build errors must handle both failed commands and disconnected track.

Connectivity itself is exercised by the live topology tests.
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
