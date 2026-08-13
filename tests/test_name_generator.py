"""Tests for generated company names.

OpenTTD leaves companies as "Unnamed", which makes a leaderboard row unable to say
who played and the company_name column in result.parquet useless. Every contestant
company therefore gets a readable name.

Run with: uv run pytest tests/test_name_generator.py -v
"""

from __future__ import annotations

import re

from nttd.utils.name_generator import MAX_COMPANY_NAME, generate_company_name, generate_session_name

# One shape for a session and a company alike: <adj>-<noun>-<date>-<time><tz>.
_COMPANY_PATTERN = re.compile(r"^[a-z]+-[a-z]+-\d{2}[a-z]{3}\d{4}-\d{6}[a-z]+$")


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


def test_session_name_still_carries_a_timestamp() -> None:
    """Guards against the company generator disturbing the session format."""
    name = generate_session_name()
    # Two words then the stamp, which is the documented format and what the function has
    # always produced: <adj>-<noun>-13aug2026-125834ist. The pattern asked for three words
    # and so could never match: measured at 0 of 20 generated names. It was asserting the
    # company format, which does have a third part, against the session generator.
    assert re.match(r"^[a-z]+-[a-z]+-\d{2}[a-z]{3}\d{4}-\d{6}[a-z]+$", name), name
