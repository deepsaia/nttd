"""The counts the prose quotes are the counts the manifest has.

Hand-written docs kept claiming a surface that had moved. Found stale, all at once:
cli_guide said "129 actions, 345 parameters" and "44 observations ... 76 actions" against a
real 132, 393, 46 and 77; mcp_guide had "the 120 actions"; the README had "All 129 actions".
None of it was wrong when written, which is the problem: a number in prose has no way to
notice that the thing it counts has changed.

The generated files never had this defect, because they are rewritten from the GameScript and
CI fails when they drift. This gives the hand-written ones the same protection, for the one
fact they both state.

Only counts are checked. Prose that describes what an action means still needs a human, and
should: a plausible description inferred from a parameter name is worse than a missing one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nttd.config.action_manifest import MANIFEST_PATH
from nttd.constants import KNOWN_ACTIONS, OPERATOR_ACTIONS, READ_ONLY_GS_ACTIONS

_ROOT = Path(__file__).resolve().parents[1]

# Each sentence that claims the size of the whole surface, as the phrase it has to contain.
# A new claim belongs here; a reworded one needs its template updated with it.
_TOTAL_CLAIMS = (
    ("docs/cli_guide.md", "{total} actions, "),
    ("docs/mcp_guide.md", "Where the {total} actions are"),
    ("README.md", "All {total} actions"),
)


def _manifest_actions() -> dict:
    return json.loads(MANIFEST_PATH.read_text())["actions"]


def test_the_three_tiers_account_for_every_action() -> None:
    """132 = 46 + 77 + 9. The tiers are asserted disjoint elsewhere; this is that they are
    also complete, so "observations plus actions plus operator powers" is the whole surface
    and the docs can safely describe it that way.
    """
    total = len(READ_ONLY_GS_ACTIONS) + len(KNOWN_ACTIONS) + len(OPERATOR_ACTIONS)
    assert total == len(_manifest_actions())


@pytest.mark.parametrize(("doc", "template"), _TOTAL_CLAIMS)
def test_the_document_states_the_real_total(doc: str, template: str) -> None:
    """Each sentence that claims the size of the whole surface says the real number.

    Asserted as an exact phrase rather than by scanning every "<n> actions" in the file. The
    scan was tried first and was worse than useless: it flagged "15 actions per 10s", which is
    a rate limit, "a hand-written table of 14 actions", which is history, and "77 actions that
    change it", which is a correct subset. A check that fires on correct prose gets deleted,
    and then nothing checks anything.
    """
    expected = template.format(total=len(_manifest_actions()))
    text = (_ROOT / doc).read_text()
    assert expected in text, (
        f"{doc} no longer contains {expected!r}. Either the count went stale, or the sentence "
        f"was reworded and the template here needs updating with it."
    )


def test_the_cli_guide_splits_the_surface_correctly() -> None:
    """The one place that states all three tier sizes in a sentence, so all three can rot
    together and only this notices.
    """
    text = (_ROOT / "docs" / "cli_guide.md").read_text()
    assert f"{len(READ_ONLY_GS_ACTIONS)} observations" in text
    assert f"{len(KNOWN_ACTIONS)} actions that change it" in text
    assert f"{len(OPERATOR_ACTIONS)} operator powers" in text


def test_the_cli_guide_states_the_real_parameter_count() -> None:
    parameters = sum(len(a.get("parameters", {})) for a in _manifest_actions().values())
    text = (_ROOT / "docs" / "cli_guide.md").read_text()
    assert f"{parameters} parameters" in text
