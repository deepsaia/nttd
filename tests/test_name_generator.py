"""Tests for generated company names.

OpenTTD leaves companies as "Unnamed", which makes a leaderboard row unable to say
who played and the company_name column in result.parquet useless. Every contestant
company therefore gets a readable name.

Run with: uv run pytest tests/test_name_generator.py -v
"""

from __future__ import annotations

import re

from nttd.utils.name_generator import generate_company_name, generate_session_name

_COMPANY_PATTERN = re.compile(r"^[a-z]+-[a-z]+-[0-9a-f]{4}$")


def test_company_name_matches_adjective_noun_hex() -> None:
    for _ in range(50):
        name = generate_company_name()
        assert _COMPANY_PATTERN.match(name), f"unexpected shape: {name}"


def test_company_names_are_distinct_in_practice() -> None:
    """The hex suffix keeps names apart when the adjective/noun pair repeats."""
    names = {generate_company_name() for _ in range(200)}
    assert len(names) > 190, "too many collisions for a leaderboard identifier"


def test_company_name_is_short_enough_for_openttd() -> None:
    """OpenTTD rejects an over-long company name, which would fail the rename."""
    for _ in range(50):
        assert len(generate_company_name()) <= 30


def test_company_name_has_no_whitespace_or_quotes() -> None:
    """The name is passed through rcon and JSON, so keep it free of separators."""
    for _ in range(50):
        name = generate_company_name()
        assert " " not in name
        assert '"' not in name and "'" not in name


def test_session_name_still_carries_a_timestamp() -> None:
    """Guards against the company generator disturbing the session format."""
    name = generate_session_name()
    assert re.match(r"^[a-z]+-[a-z]+-[a-z]+-\d{2}[a-z]{3}\d{4}-\d{6}[a-z]+$", name), name
