"""Checking a submission bundle, and what each verdict is worth.

The checks that need OpenTTD are exercised live rather than here: reloading a savegame
and regenerating a world need the binary, a config directory with the GameScript, and
about 15 seconds. What is unit-tested is everything that decides a verdict from evidence,
which is the part a leaderboard's ingest depends on being predictable.

Verified live against a real bundle while building this:

  default path         -> replayed  (2s: digests, openttd -q, reload, action log)
  --regenerate         -> verified  (14s: 64516 tiles rebuilt from the declared seed)
  edited score         -> unverified (the digest no longer matches)
  edited score + digest-> unverified (the savegame does not support the score)
  swapped seed + digest-> replayed  (the regenerated world is a different world)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from nttd.schemas.verification import CheckOutcome, Verdict, VerificationReport
from nttd.verify import checks, replay
from nttd.verify.validator import _verdict


def _result(**overrides: Any) -> dict[str, Any]:
    """A result row consistent with the action log below."""
    return {
        "company_id": 0,
        "total_actions": 2,
        "successful_actions": 1,
        "start_game_date": 1000,
        "end_game_date": 2000,
        "clean_run": True,
        "map_seed": 1001,
        **overrides,
    }


def _actions() -> list[dict[str, Any]]:
    return [
        {"company_id": 0, "action_type": "set_loan", "status": "success", "game_date": 1100},
        {"company_id": 0, "action_type": "build_road", "status": "failed", "game_date": 1200},
    ]


# ---------------------------------------------------------------------------
# artifact_integrity
# ---------------------------------------------------------------------------


def _bundle_with(tmp_path: Path, contents: dict[str, bytes]) -> tuple[Path, dict[str, Any]]:
    """A bundle whose manifest honestly describes its files."""
    bundle = tmp_path / "submission"
    bundle.mkdir()
    artifacts: dict[str, Any] = {}
    for name, data in contents.items():
        (bundle / name).write_bytes(data)
        artifacts[name] = {
            "sha256": hashlib.sha256(data).hexdigest()[:16], "bytes": len(data),
        }
    manifest = {"manifest_version": 1, "artifacts": artifacts}
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    return bundle, manifest


class TestArtifactIntegrity:
    def test_matching_digests_pass(self, tmp_path: Path) -> None:
        bundle, manifest = _bundle_with(tmp_path, {"a.parquet": b"one", "b.sav": b"two"})
        outcome = checks.artifact_integrity(bundle, manifest)
        assert outcome.passed is True
        assert "2 artifact(s)" in outcome.detail

    def test_an_edited_artifact_fails(self, tmp_path: Path) -> None:
        """The reason the digests exist."""
        bundle, manifest = _bundle_with(tmp_path, {"a.parquet": b"one"})
        (bundle / "a.parquet").write_bytes(b"one, edited")
        outcome = checks.artifact_integrity(bundle, manifest)
        assert outcome.passed is False
        assert "hashes to" in outcome.detail

    def test_a_listed_but_missing_artifact_fails(self, tmp_path: Path) -> None:
        bundle, manifest = _bundle_with(tmp_path, {"a.parquet": b"one"})
        (bundle / "a.parquet").unlink()
        outcome = checks.artifact_integrity(bundle, manifest)
        assert outcome.passed is False
        assert "missing" in outcome.detail

    def test_a_manifest_listing_nothing_fails(self, tmp_path: Path) -> None:
        bundle = tmp_path / "submission"
        bundle.mkdir()
        outcome = checks.artifact_integrity(bundle, {"artifacts": {}})
        assert outcome.passed is False


# ---------------------------------------------------------------------------
# action_log_consistent
# ---------------------------------------------------------------------------


class TestActionLogConsistent:
    def test_a_log_matching_the_result_passes(self) -> None:
        outcome = checks.action_log_consistent(_actions(), _result())
        assert outcome.passed is True

    def test_a_count_that_disagrees_fails(self) -> None:
        outcome = checks.action_log_consistent(_actions(), _result(total_actions=9))
        assert outcome.passed is False
        assert "claims 9" in outcome.detail

    def test_a_success_count_that_disagrees_fails(self) -> None:
        outcome = checks.action_log_consistent(_actions(), _result(successful_actions=2))
        assert outcome.passed is False
        assert "successful" in outcome.detail

    def test_a_reordered_log_fails(self) -> None:
        """Game dates only move forward, so a spliced log tends to show here."""
        reordered = list(reversed(_actions()))
        outcome = checks.action_log_consistent(reordered, _result())
        assert outcome.passed is False
        assert "monotonic" in outcome.detail

    def test_an_action_outside_the_run_window_fails(self) -> None:
        late = _actions()
        late[-1]["game_date"] = 9999
        outcome = checks.action_log_consistent(late, _result())
        assert outcome.passed is False
        assert "outside the run's window" in outcome.detail

    def test_it_counts_only_the_company_being_scored(self) -> None:
        """A multi-company session has one result row per company."""
        mixed = _actions() + [
            {"company_id": 1, "action_type": "set_loan", "status": "success",
             "game_date": 1300},
        ]
        outcome = checks.action_log_consistent(mixed, _result())
        assert outcome.passed is True


# ---------------------------------------------------------------------------
# no_forbidden_capability
# ---------------------------------------------------------------------------


class TestNoForbiddenCapability:
    def test_a_clean_log_passes(self) -> None:
        outcome = checks.no_forbidden_capability(_actions(), _result())
        assert outcome.passed is True

    def test_a_successful_operator_action_fails(self) -> None:
        """The run had powers no human has, so it is not a comparable result."""
        cheating = _actions() + [
            {"company_id": 0, "action_type": "change_bank_balance",
             "status": "success", "game_date": 1400},
        ]
        outcome = checks.no_forbidden_capability(cheating, _result())
        assert outcome.passed is False
        assert "change_bank_balance" in outcome.detail

    def test_a_refused_attempt_is_disclosed_not_fatal(self) -> None:
        """Nothing happened, so the run stands -- but it is not a clean run, and a
        result claiming otherwise is under-reporting."""
        refused = _actions() + [
            {"company_id": 0, "action_type": "set_max_loan",
             "status": "rejected", "game_date": 1400},
        ]
        honest = checks.no_forbidden_capability(refused, _result(clean_run=False))
        assert honest.passed is True
        assert "1 refused and disclosed" in honest.detail

        lying = checks.no_forbidden_capability(refused, _result(clean_run=True))
        assert lying.passed is False
        assert "claims a clean run" in lying.detail


# ---------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------


def _outcomes(**passed: bool | None) -> list[CheckOutcome]:
    names = {
        "integrity": checks.ARTIFACT_INTEGRITY,
        "log": checks.ACTION_LOG_CONSISTENT,
        "capability": checks.NO_FORBIDDEN_CAPABILITY,
        "savegame": replay.SAVEGAME_READABLE,
        "score": replay.SCORE_RECOMPUTED,
        "world": replay.WORLD_REGENERATED,
    }
    return [CheckOutcome(name=names[key], passed=value) for key, value in passed.items()]


class TestVerdict:
    def test_all_passing_with_regeneration_is_verified(self) -> None:
        outcomes = _outcomes(
            integrity=True, log=True, capability=True, savegame=True,
            score=True, world=True,
        )
        assert _verdict(outcomes, regenerate=True) is Verdict.VERIFIED

    def test_without_regeneration_the_best_is_replayed(self) -> None:
        """The cheap default: the score is recomputable, the world is not reconciled."""
        outcomes = _outcomes(
            integrity=True, log=True, capability=True, savegame=True,
            score=True, world=None,
        )
        assert _verdict(outcomes, regenerate=False) is Verdict.REPLAYED

    def test_a_broken_digest_is_unverified(self) -> None:
        """A tampered bundle is not a failed run, it is an unusable submission."""
        outcomes = _outcomes(integrity=False, score=True)
        assert _verdict(outcomes, regenerate=True) is Verdict.UNVERIFIED

    def test_a_score_the_save_does_not_support_is_unverified(self) -> None:
        outcomes = _outcomes(integrity=True, savegame=True, score=False)
        assert _verdict(outcomes, regenerate=True) is Verdict.UNVERIFIED

    def test_an_unreadable_savegame_is_unverified(self) -> None:
        outcomes = _outcomes(integrity=True, savegame=False, score=None)
        assert _verdict(outcomes, regenerate=False) is Verdict.UNVERIFIED

    def test_a_world_that_does_not_match_its_seed_drops_to_replayed(self) -> None:
        """The score still comes from the save, so the run is replayable -- but the
        world is not the one declared, and that is named in the report."""
        outcomes = _outcomes(
            integrity=True, log=True, capability=True, savegame=True,
            score=True, world=False,
        )
        assert _verdict(outcomes, regenerate=True) is Verdict.REPLAYED

    def test_a_failing_action_log_drops_to_replayed(self) -> None:
        outcomes = _outcomes(
            integrity=True, log=False, capability=True, savegame=True,
            score=True, world=True,
        )
        assert _verdict(outcomes, regenerate=True) is Verdict.REPLAYED


class TestTheReportIsAdvisoryByDefault:
    def test_a_locally_produced_verdict_says_so(self) -> None:
        """Whoever ran it could have changed the code that produced it, so the flag
        defaults to advisory rather than having to be remembered."""
        report = VerificationReport(verdict=Verdict.VERIFIED)
        assert report.advisory is True

    def test_it_separates_failures_from_checks_never_run(self) -> None:
        report = VerificationReport(
            verdict=Verdict.REPLAYED,
            checks=_outcomes(integrity=True, score=True, world=None, log=False),
        )
        assert [c.name for c in report.failures] == [checks.ACTION_LOG_CONSISTENT]
        assert [c.name for c in report.skipped] == [replay.WORLD_REGENERATED]


class TestNoVerdictIsEverStored:
    def test_the_report_is_not_written_into_the_bundle(self, tmp_path: Path) -> None:
        """A bundle carrying its own verdict would assert something anyone could
        write, which is the `scored = true` defect in a new place."""
        bundle, manifest = _bundle_with(tmp_path, {"a.parquet": b"one"})
        checks.artifact_integrity(bundle, manifest)

        assert not (bundle / "verification.json").exists()
        text = (bundle / "manifest.json").read_text()
        for word in ("verdict", "verified", "replayed", "unverified"):
            assert word not in text


class TestVerifyingDoesNotTouchTheBundle:
    def test_the_scratch_directory_is_outside_the_bundle(self) -> None:
        """Verifying must not change what it inspects.

        A stray scratch directory inside the bundle would make it differ after being
        checked, and would stop a read-only extract being verifiable at all -- which is
        how a board's ingest will see one.
        """
        import inspect

        from nttd.verify.validator import BundleValidator

        source = inspect.getsource(BundleValidator._server)
        assert "tempfile" not in source, "the scratch dir is passed in, not built here"
        assert "bundle_dir" not in source, "the scratch dir must not live in the bundle"

        for method in (BundleValidator._recompute_score, BundleValidator._regenerate_world):
            body = inspect.getsource(method)
            assert "tempfile.mkdtemp" in body, f"{method.__name__} needs its own scratch"
            assert "shutil.rmtree" in body, f"{method.__name__} must clean up after itself"


class TestReadManifest:
    def test_a_missing_manifest_is_none(self, tmp_path: Path) -> None:
        assert checks.read_manifest(tmp_path) is None

    def test_unparseable_json_is_none_not_a_crash(self, tmp_path: Path) -> None:
        (tmp_path / "manifest.json").write_text("{not json")
        assert checks.read_manifest(tmp_path) is None


@pytest.mark.parametrize("verdict", list(Verdict))
def test_every_verdict_has_a_meaning_in_the_cli(verdict: Verdict) -> None:
    """A verdict a reader cannot interpret is worse than no verdict."""
    from nttd.cli.verify_command import _VERDICT_MEANING, _VERDICT_STYLE

    assert verdict in _VERDICT_MEANING
    assert verdict in _VERDICT_STYLE
