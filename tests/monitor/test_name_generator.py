"""Tests for the one name a run has, and for the company that carries it.

OpenTTD leaves companies as "Unnamed", which makes a leaderboard row unable to say who
played and the company_name column in result.parquet useless. Every contestant company
therefore gets a readable name, and that name comes from the session rather than being
minted separately.

Run with: uv run pytest tests/monitor/test_name_generator.py -v
"""

from __future__ import annotations

import re

from nttd.utils.name_generator import (
    MAX_COMPANY_NAME,
    company_name_for,
    generate_session_id,
    readable_part,
)


def test_the_company_carries_the_session_name() -> None:
    """The defect this replaced.

    A company used to mint its own adjective, noun and timestamp, so a run called
    20260824-132212ist-sly-marsh was played by chief-warden-20260824-132213ist. Two
    identities for one run, a second apart, which is the bug collapsing the session's two
    names into one id was meant to end. The monitor showed one in its sidebar and the other
    in its URL.
    """
    assert company_name_for("20260824-132212ist-sly-marsh", 0) == "sly-marsh"


def test_extra_companies_are_numbered_rather_than_sharing_one_name() -> None:
    """Only one company is scored, but --ai-opponents N creates idle ones."""
    session = "20260824-132212ist-sly-marsh"
    names = [company_name_for(session, cid) for cid in range(4)]
    assert names == ["sly-marsh", "sly-marsh-1", "sly-marsh-2", "sly-marsh-3"]
    assert len(set(names)) == 4


def test_the_company_name_fits_openttd_for_every_id_the_generator_makes() -> None:
    """A refused rename leaves the company "Unnamed", so a row cannot say who played.

    The date is why this holds. A session id runs to 35 characters: a four-letter timezone
    makes the stamp 19, and the longest adjective and noun together are 14. Including the
    date would fit most ids and silently truncate the longest, which is worse than a rule
    that never includes it.
    """
    for _ in range(300):
        session = generate_session_id()
        for company_id in (0, 1, 12):
            name = company_name_for(session, company_id)
            assert len(name) <= MAX_COMPANY_NAME, f"{name} is {len(name)} characters"


def test_a_supplied_session_name_too_long_for_a_company_is_capped_not_refused() -> None:
    """--name accepts up to 128 characters, so the cap is enforced rather than assumed."""
    session = "x" * 128
    name = company_name_for(session, 2)
    assert len(name) == MAX_COMPANY_NAME
    assert name.endswith("-2"), "the number must survive the truncation"


def test_a_company_name_has_no_whitespace_or_quotes() -> None:
    """The name is passed through rcon and JSON, so keep it free of separators."""
    for _ in range(50):
        name = company_name_for(generate_session_id(), 0)
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
