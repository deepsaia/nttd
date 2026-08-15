"""Every action now says what comes back, derived from the handler that builds it.

Nothing described a reply before this. All 131 actions documented their parameters and not
one documented its result, so an agent had to guess a field name and read a null as an
absent feature. Three working replies were misread that way in a single session:

    find_station_spot   orientation looked for as `direction`, actually `valid_directions`
    get_company_finance balance looked for as `money`,          actually `balance`
    get_vehicle_info    load looked for as `cargo_load`,        actually a `cargo` list

The names are extracted from the GameScript rather than written by hand, so they cannot
drift the way the prose in #108 did.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.conftest import REPO_ROOT

_MANIFEST = REPO_ROOT / "config" / "actions" / "manifest.json"


@pytest.fixture(scope="module")
def actions() -> dict[str, Any]:
    return json.loads(_MANIFEST.read_text())["actions"]


def test_almost_every_action_says_what_it_returns(actions: dict[str, Any]) -> None:
    """ping is the one exception: it answers that the script is alive and nothing more."""
    silent = sorted(name for name, entry in actions.items() if "returns" not in entry)
    assert silent == ["ping"]


@pytest.mark.parametrize(
    ("action", "field"),
    [
        ("get_company_finance", "balance"),
        ("get_station_info", "platform_axis"),
        ("get_station_info", "entry_tiles"),
        ("get_vehicle_info", "cargo"),
        ("connect_rail", "gaps"),
        ("connect_rail", "status"),
    ],
)
def test_the_fields_a_reply_actually_carries_are_published(
    actions: dict[str, Any], action: str, field: str,
) -> None:
    """Each of these was read live off a running game during the session that found this."""
    assert field in actions[action]["returns"]["fields"]


def test_a_field_that_is_a_list_of_tables_publishes_the_inner_keys(
    actions: dict[str, Any],
) -> None:
    """The outer name alone is no help. valid_directions, the orientation fact this whole
    thread was about, lives one level down inside `spots`."""
    returns = actions["find_station_spot"]["returns"]
    assert "spots" in returns["fields"]
    assert "valid_directions" in returns["nested"]["spots"]


def test_a_list_shaped_reply_is_marked_as_one(actions: dict[str, Any]) -> None:
    """get_towns answers with a bare list, not an object wrapping one."""
    assert actions["get_towns"]["returns"]["shape"] == "list"
    assert actions["get_company_finance"]["returns"]["shape"] == "object"


def test_no_published_return_field_is_empty_or_duplicated(actions: dict[str, Any]) -> None:
    for name, entry in actions.items():
        fields = entry.get("returns", {}).get("fields")
        if not fields:
            continue
        assert all(field.strip() for field in fields), name
        assert len(set(fields)) == len(fields), name
