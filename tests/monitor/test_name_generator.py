"""Tests for generated company names.

OpenTTD leaves companies as "Unnamed", which makes a leaderboard row unable to say
who played and the company_name column in result.parquet useless. Every contestant
company therefore gets a readable name.

Run with: uv run pytest tests/test_name_generator.py -v
"""

from __future__ import annotations

import re

from nttd.utils.name_generator import (
    MAX_COMPANY_NAME,
    generate_company_name,
    generate_session_id,
    readable_part,
)

# One shape for a session and a company alike: <adj>-<noun>-<date>-<time><tz>.
_COMPANY_PATTERN = re.compile(r"^[a-z]+-[a-z]+-\d{8}-\d{6}[a-z]+$")


def test_company_name_matches_the_session_name_shape() -> None:
    """A company used to end in four hex characters, which made it look like a different
    kind of thing from a session and said nothing about when the run happened.
    """
    for _ in range(50):
        name = generate_company_name()
        assert _COMPANY_PATTERN.match(name), f"unexpected shape: {name}"


def test_company_names_are_distinct_in_practice() -> None:
    """The timestamp keeps names apart when the adjective/noun pair repeats."""
    names = {generate_company_name() for _ in range(200)}
    assert len(names) > 190, "too many collisions for a leaderboard identifier"


def test_company_name_is_short_enough_for_openttd() -> None:
    """OpenTTD rejects an over-long company name, and a refused rename leaves the company
    called "Unnamed", so a leaderboard row cannot say who played.

    The timestamp is 19 of the 31 characters available, and the longest adjective and noun
    together are 14, which would give 35. generate_company_name draws from the pairs that
    fit rather than freely, which is why this holds.
    """
    for _ in range(200):
        name = generate_company_name()
        assert len(name) <= MAX_COMPANY_NAME, f"{name} is {len(name)} characters"


def test_company_name_has_no_whitespace_or_quotes() -> None:
    """The name is passed through rcon and JSON, so keep it free of separators."""
    for _ in range(50):
        name = generate_company_name()
        assert " " not in name
        assert '"' not in name and "'" not in name


def test_a_session_id_leads_with_the_date_and_ends_with_the_words() -> None:
    """One identity per session, and it sorts.

    A session used to be minted as ses_20260815_073254_060e426f on disk and shown as
    dandy-willow-20260815-073255ist in the monitor: two names for one run, generated a
    moment apart, so their timestamps disagreed by a second. The id is now both.

    Date first so a directory listing is in time order, words last so there is something
    to say out loud, and the timezone attached to the time it qualifies rather than
    trailing the whole name.
    """
    session_id = generate_session_id()
    assert re.match(r"^\d{8}-\d{6}[a-z]+-[a-z]+-[a-z]+$", session_id), session_id


def test_the_words_can_be_read_back_out_for_a_heading() -> None:
    session_id = generate_session_id()
    words = readable_part(session_id)
    assert words == "-".join(session_id.split("-")[2:])
    assert not any(char.isdigit() for char in words)


def test_an_id_without_a_word_pair_is_returned_whole() -> None:
    """The eight published reference runs carry the old shape, and a heading that showed
    a mangled guess would be worse than showing the id."""
    assert readable_part("ses_20260815_071144_a6c94052") == "ses_20260815_071144_a6c94052"


def test_names_sort_chronologically_as_plain_strings() -> None:
    """The date is yyyymmdd so a lexical sort is also a chronological one.

    It used to be 13aug2026, which sorts august before february and december before january.
    The monitor's ordering does not depend on this, since it reads the timestamp out of the
    session id, but anything that sorts names, a directory listing or a leaderboard column,
    now agrees with time instead of contradicting it.
    """
    names = [
        f"alpha-acorn-{stamp}"
        for stamp in ("20260101-090000ist", "20260213-090000ist",
                      "20260813-193558ist", "20261201-000001ist")
    ]
    assert sorted(names) == names
