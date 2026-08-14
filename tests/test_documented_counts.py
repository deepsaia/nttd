"""The hand-written docs do not quote counts of the action surface, so they cannot go stale.

They used to. Found stale, all at once: cli_guide said "129 actions, 345 parameters" and
"44 observations ... 76 actions" against a real 132, 393, 46 and 77; mcp_guide had "the 120
actions"; the README had "All 129 actions". None of it was wrong when written, which is the
problem: a number in prose has no way to notice that the thing it counts has changed.

The first attempt at a fix was a guard that asserted each quoted number matched the manifest.
It worked, and it was still the wrong shape: every action added meant a doc edit in three
files to satisfy a test, and the number carried no information a reader could not get from
`nttd actions` or the generated listing. So the counts came out of the prose instead, and
this file holds the line that they stay out.

The generated files under docs/actions/ still state exact figures, which is correct: they are
rewritten from the GameScript and CI fails when they drift.

What is still worth asserting is that the three tiers partition the surface, because the docs
describe it that way in words.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from nttd.config.action_manifest import MANIFEST_PATH
from nttd.constants import KNOWN_ACTIONS, OPERATOR_ACTIONS, READ_ONLY_GS_ACTIONS

_ROOT = Path(__file__).resolve().parents[1]

# The hand-written docs that describe the action surface in prose.
_HAND_WRITTEN = ("docs/cli_guide.md", "docs/mcp_guide.md", "README.md")

# A claim about how big the surface is. Deliberately narrow: an earlier version scanned for
# every "<n> actions" and was worse than useless, flagging "15 actions per 10s", which is a
# rate limit, and "a hand-written table of 14 actions", which is history. This matches only
# the shapes that assert a total.
_COUNT_CLAIM = re.compile(
    r"(?:All |the |Where the )\d+ actions\b"
    r"|\b\d+ actions, \d+ parameters"
    r"|\b\d+ observations that read\b"
    r"|\b\d+ operator powers\b",
)


def _manifest_actions() -> dict:
    return json.loads(MANIFEST_PATH.read_text())["actions"]


def test_the_three_tiers_account_for_every_action() -> None:
    """The tiers are asserted disjoint elsewhere; this is that they are also complete, so
    "observations plus actions plus operator powers" is the whole surface and the docs can
    safely describe it that way in words.
    """
    total = len(READ_ONLY_GS_ACTIONS) + len(KNOWN_ACTIONS) + len(OPERATOR_ACTIONS)
    assert total == len(_manifest_actions())


@pytest.mark.parametrize("doc", _HAND_WRITTEN)
def test_a_hand_written_doc_quotes_no_action_count(doc: str) -> None:
    """Adding an action must not require editing prose in three files to satisfy a test."""
    text = (_ROOT / doc).read_text()
    found = _COUNT_CLAIM.findall(text)
    assert found == [], (
        f"{doc} states the size of the action surface: {found}. Counts in hand-written prose "
        f"go stale on the next action added. Point at `nttd actions` or "
        f"docs/actions/index.md, which are generated, instead."
    )


def test_the_generated_listing_is_where_the_real_count_lives() -> None:
    """The claim removed from the prose has to be answerable somewhere, and this is where."""
    index = (_ROOT / "docs" / "actions" / "index.md").read_text()
    for name in sorted(_manifest_actions())[:5]:
        assert f"`{name}(" in index, f"{name} missing from the generated index"
