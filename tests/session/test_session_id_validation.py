"""A session id names one directory under the sessions root, and nothing else.

Every path to session data is the sessions root joined with a caller's string, and 34 HTTP
routes take that string as a path parameter. `Path("logs/sessions") / "../../etc"` is a path
to /etc. The directory is read, written, and in `session_repo.delete_session` removed whole.

What was already true, and is worth recording so nobody relaxes it by accident: ids are minted
by the server as `ses_<date>_<time>_<8 hex>`, never chosen by the caller, and the delete route
refuses unless a real session record is already at the path. So this closes a hole that needed
another mistake to be reachable, rather than one standing open. The check belongs at the join
regardless: it is the one line every one of those routes goes through.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nttd.store import parquet_reader, session_paths
from nttd.store.session_paths import InvalidSessionIdError, session_dir, validate_session_id

# Shapes that exist. The first is what the server mints, the second what the tests use, and
# the third the generated session name, in case one is ever used as an id.
_REAL = [
    "ses_20260813_160834_afc142c3",
    "ses_001",
    "fuzzy-sprout-13aug2026-162006ist",
    "a.b",
    "a..b",  # not "..": a legal directory name that cannot climb anywhere
]

_ESCAPES = [
    "../../etc",
    "..",
    ".",
    "/etc/passwd",
    "a/b",
    "a\\b",  # Windows separator, since the check must not assume a platform
    "",
    " ",
    "sp ace",
    "nul\x00byte",
    "x" * 129,
]


@pytest.mark.parametrize("session_id", _REAL)
def test_a_real_session_id_is_accepted(session_id: str) -> None:
    """The check is worthless if it rejects the ids nttd itself creates."""
    assert validate_session_id(session_id) == session_id
    assert session_dir(session_id).name == session_id


@pytest.mark.parametrize("session_id", _ESCAPES)
def test_an_id_that_could_escape_is_refused(session_id: str) -> None:
    with pytest.raises(InvalidSessionIdError):
        session_dir(session_id)


@pytest.mark.parametrize("session_id", _REAL)
def test_an_accepted_id_stays_directly_under_the_root(session_id: str) -> None:
    """The property the character set buys: one path component, so the parent is the root.

    Asserted on the path rather than the string because that is what callers use.
    """
    assert session_dir(session_id).parent == session_paths.sessions_dir()


def test_the_readers_that_join_the_root_themselves_are_covered() -> None:
    """analysis.loader and store.parquet_reader build the same join with an overridable root,
    so they cannot call session_dir and had to repeat the check. If either is refactored to
    drop it, this fails.
    """
    from nttd.analysis import loader

    with pytest.raises(InvalidSessionIdError):
        loader.load_session("../../etc", sessions_dir=Path("/tmp"))
    with pytest.raises(InvalidSessionIdError):
        parquet_reader.read_table("../../etc", "actions", sessions_dir=Path("/tmp"))


def test_a_missing_session_is_still_a_plain_not_found(tmp_path: Path) -> None:
    """A valid id for a session that does not exist must keep reporting what it always did.
    Turning every unknown session into an invalid-id error would be a worse bug than the one
    being fixed, because it is the common case.
    """
    from nttd.analysis import loader

    with pytest.raises(FileNotFoundError):
        loader.load_session("ses_does_not_exist", sessions_dir=tmp_path)
    assert parquet_reader.read_table("ses_does_not_exist", "actions", sessions_dir=tmp_path) is None
