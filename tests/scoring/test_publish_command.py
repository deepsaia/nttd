"""Filing a bundle is the last step a contestant owns, and the only one that leaves the machine.

`nttd publish` opens a pull request adding one bundle to the board's dataset. It deliberately
does NOT verify or judge: that runs on the board's own infrastructure, and shipping the judge
inside the thing being judged would invite "I ran the board locally and it said verified".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer

from nttd.cli import publish_command
from nttd.store.submission_bundle import MANIFEST_NAME


def _bundle(tmp_path: Path) -> Path:
    directory = tmp_path / "submission"
    directory.mkdir()
    (directory / MANIFEST_NAME).write_text(json.dumps({"session_id": "x"}))
    (directory / "final.sav").write_bytes(b"save")
    return directory


def test_a_directory_without_a_manifest_is_refused(tmp_path: Path) -> None:
    """Assembling a bundle by hand is the mistake this catches: `nttd package` builds one."""
    (tmp_path / "not-a-bundle").mkdir()
    with pytest.raises(typer.Exit):
        publish_command.publish(bundle=tmp_path / "not-a-bundle", entrant="ada", dry_run=True)


def test_an_entrant_is_read_from_the_token_rather_than_asked_for(monkeypatch) -> None:
    """It is not a label, and treating it as one is how a submission gets rejected.

    The board's ingest checks the diff against the account that OPENED the pull request and
    refuses anything outside `submissions/<that account>/`. So an entrant that is not the
    HuggingFace username is not a cosmetic mismatch: the whole submission bounces. Reading it
    from the token is what makes it right by construction.
    """
    monkeypatch.setattr(publish_command, "_whoami_name", lambda token: "ada-from-hub")
    assert publish_command._entrant(None, "hf_sometoken") == "ada-from-hub"


def test_a_named_entrant_wins_over_the_token() -> None:
    """One account may file under an organisation it can write to."""
    assert publish_command._entrant("some-org", "hf_sometoken") == "some-org"


def test_an_entrant_with_no_token_falls_back_rather_than_refusing(monkeypatch) -> None:
    """Reached only by --dry-run, which does not read the token.

    A dry run exists to show the shape of what would be filed, and refusing to show it for
    want of a credential nothing is going to use defeats the point.
    """
    assert publish_command._entrant(None, None) == publish_command.UNKNOWN_ENTRANT


def test_an_unreadable_token_falls_back_rather_than_crashing(monkeypatch) -> None:
    """The hub being unreachable must not look like a bug in the bundle."""
    def explode(token: str) -> str:
        raise OSError("no network")

    monkeypatch.setattr(publish_command, "_whoami_name", explode)
    assert publish_command._entrant(None, "hf_sometoken") == publish_command.UNKNOWN_ENTRANT


def test_a_dry_run_uploads_nothing(tmp_path: Path, monkeypatch) -> None:
    def explode(*args: object, **kwargs: object) -> str:
        raise AssertionError("a dry run must not upload")

    monkeypatch.setattr(publish_command, "_upload", explode)
    publish_command.publish(bundle=_bundle(tmp_path), entrant="ada", dry_run=True)


def test_a_missing_token_is_reported_before_anything_is_sent(
    tmp_path: Path, monkeypatch
) -> None:
    """The token is the contestant's own, because the pull request is theirs."""
    monkeypatch.delenv(publish_command.TOKEN_VAR, raising=False)
    monkeypatch.setattr(
        publish_command, "_upload", lambda *a, **k: pytest.fail("sent without a token")
    )
    with pytest.raises(typer.Exit):
        publish_command.publish(bundle=_bundle(tmp_path), entrant="ada")


def test_bundle_and_session_are_not_both_accepted(tmp_path: Path) -> None:
    with pytest.raises(typer.Exit):
        publish_command.publish(
            bundle=_bundle(tmp_path), session="20260815-132431ist-quiet-pickle", entrant="ada"
        )


def test_the_board_is_not_judged_from_here() -> None:
    """A guard on the boundary, not on behaviour.

    Verification and verdicts belong to the board's repository. If this module ever grows a
    verdict, the trust boundary has moved and that should be a deliberate decision rather
    than something that arrives with a convenience flag.
    """
    source = Path(publish_command.__file__).read_text()
    for word in ("verified", "replayed", "verdict ="):
        assert word not in source.split('"""', 2)[2], word
