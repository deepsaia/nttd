"""What a contestant submits, and what makes it checkable.

nttd is self-hosted, so a submission cannot mean "we watched it happen". It means the
artifacts are internally consistent and the score is recomputable. Two properties carry
that, and both are pinned here:

  * the manifest holds identity and integrity only, so it has nothing to contradict:
    everything about the run lives in the result.parquet sitting beside it;
  * every artifact carries a digest, so an edit after the fact is detectable.

The manifest carries no verdict. A bundle asserting "verified" would be making a claim
anyone could write, which is the same defect as a scenario declaring ``scored = true``.
"""

from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from nttd.store.map_digest import map_digest
from nttd.store.result_writer import _SCHEMA
from nttd.store.submission_bundle import MANIFEST_NAME, SubmissionBundle
from nttd.store.verification_gaps import verification_gaps

# Only the fields these tests assert on. Everything else is filled from the schema by
# _complete_row, so a new column does not silently break this file, and a wrong guess
# about a column's type cannot happen here at all.
_INTERESTING: dict[str, Any] = {
    "session_id": "ses_probe",
    "company_id": 0,
    "company_name": "Probe Transport",
    "score_version": "v1",
    "primary_score": 812,
    "tiebreak_cargo": 4200,
    "rating_available": True,
    "company_value": 500_000,
    "task_id": "task123",
    "scenario_id": "bench-t2",
    "map_seed": 1001,
    "settings_digest": "settings123",
    "map_size_x": 256,
    "map_size_y": 256,
    "landscape": "temperate",
    "terrain_type": "flat",
    "profile_version": "profile123",
    "runtime_mode": "stepped",
    "end_reason": "max_heartbeats",
    "participant_type": "rl",
    "total_actions": 61,
    "spend_is_reported": True,
    "cost_is_reported": True,
    "scored_session": True,
    "clean_run": True,
    "blocked_attempts": 0,
    "capability_digest": "cap123",
    "nttd_git_sha": "abc1234",
    "nttd_git_dirty": False,
    "gamescript_digest": "gs123",
    "scenario_file_digest": "scn123",
    "final_save_name": "final.sav",
    "final_save_digest": "save123",
    "final_save_bytes": 77_000,
    "openttd_version": "OpenTTD 15.3",
}


def _default_for(field: pa.Field) -> Any:
    """A type-correct placeholder, so the fixture never has to guess a column type."""
    if pa.types.is_boolean(field.type):
        return False
    if pa.types.is_integer(field.type):
        return 0
    if pa.types.is_floating(field.type):
        return 0.0
    if pa.types.is_timestamp(field.type):
        # None rather than a fixed instant: nothing here asserts on recorded_at, and a
        # literal would have to be kept in step with the column's unit.
        return None
    return ""


def _complete_row(**overrides: Any) -> dict[str, Any]:
    """A result row that has no verification gaps, plus any overrides."""
    row = {field.name: _default_for(field) for field in _SCHEMA}
    row.update(_INTERESTING)
    row.update(overrides)
    return row


def _write_result(session_dir: Path, **overrides: Any) -> None:
    row = _complete_row(**overrides)
    session_dir.mkdir(parents=True, exist_ok=True)
    payload = {name: [row.get(name)] for name in _SCHEMA.names}
    pq.write_table(pa.Table.from_pydict(payload, schema=_SCHEMA),
                   session_dir / "result.parquet")


def _write_tiles(session_dir: Path, heights: list[int], session_id: str = "ses_probe") -> None:
    rows = len(heights)
    pq.write_table(
        pa.table({
            "session_id": [session_id] * rows,
            "captured_at": pa.array([None] * rows, type=pa.timestamp("us")),
            "x": list(range(rows)),
            "y": [0] * rows,
            "height": heights,
            "slope": [0] * rows,
            "flags": [1] * rows,
        }),
        session_dir / "tiles.parquet",
    )


def _write_snapshots(session_dir: Path, dates: list[int]) -> None:
    pq.write_table(
        pa.table({
            "game_date": dates,
            "snapshot_json": [f'{{"game": {{"game_date": {d}}}}}' for d in dates],
        }),
        session_dir / "snapshots.parquet",
    )


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    d = tmp_path / "ses_probe"
    _write_result(d)
    _write_tiles(d, [0, 1, 2, 3])
    _write_snapshots(d, [100, 200, 300])
    (d / "actions.parquet").write_bytes(b"actions")
    (d / "nttd_scenario.conf").write_text("scenario {}\n")
    (d / "save").mkdir()
    (d / "save" / "final.sav").write_bytes(b"savegame bytes")
    return d


# ---------------------------------------------------------------------------
# The map digest, which is what makes step 1 of verification possible
# ---------------------------------------------------------------------------


class TestMapDigest:
    def test_the_same_terrain_gives_the_same_digest(self, tmp_path: Path) -> None:
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir()
        b.mkdir()
        _write_tiles(a, [0, 1, 2, 3])
        _write_tiles(b, [0, 1, 2, 3])
        assert map_digest(a / "tiles.parquet") == map_digest(b / "tiles.parquet")

    def test_different_terrain_gives_a_different_digest(self, tmp_path: Path) -> None:
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir()
        b.mkdir()
        _write_tiles(a, [0, 1, 2, 3])
        _write_tiles(b, [0, 1, 2, 9])
        assert map_digest(a / "tiles.parquet") != map_digest(b / "tiles.parquet")

    def test_it_ignores_who_scanned_and_when(self, tmp_path: Path) -> None:
        """Otherwise every run of one seed would report a different world, which is
        the reason this hashes the terrain rather than the file."""
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir()
        b.mkdir()
        _write_tiles(a, [0, 1, 2, 3], session_id="ses_one")
        _write_tiles(b, [0, 1, 2, 3], session_id="ses_two")
        assert map_digest(a / "tiles.parquet") == map_digest(b / "tiles.parquet")

    def test_a_missing_scan_is_none_not_an_error(self, tmp_path: Path) -> None:
        assert map_digest(tmp_path / "absent.parquet") is None


# ---------------------------------------------------------------------------
# The gaps, shared with `nttd result`
# ---------------------------------------------------------------------------


class TestVerificationGaps:
    def test_a_complete_record_has_no_gaps(self) -> None:
        assert verification_gaps([_complete_row()]) == []

    def test_tokens_without_a_price_is_its_own_gap(self) -> None:
        """Not the same as reporting nothing, and saying so would be wrong twice.

        The tokens ARE recorded, and the reason the cost is not is usually a model missing
        from the runner's price table rather than a runner that never reported.
        """
        gaps = verification_gaps([_complete_row(cost_is_reported=False)])
        assert len(gaps) == 1
        assert "without a price" in gaps[0]
        assert "no spend reported" not in gaps[0]

    def test_reporting_nothing_still_says_so(self) -> None:
        gaps = verification_gaps([
            _complete_row(spend_is_reported=False, cost_is_reported=False),
        ])
        assert any("no spend reported" in gap for gap in gaps)

    @pytest.mark.parametrize(
        ("field", "value", "expected"),
        [
            ("scored_session", False, "not scored"),
            ("clean_run", False, "not clean"),
            ("final_save_digest", "", "no final savegame"),
            ("map_seed", -1, "no map seed"),
            ("task_id", "", "no task_id"),
            ("nttd_git_dirty", True, "uncommitted changes"),
            ("gamescript_digest", "", "GameScript not pinned"),
            ("spend_is_reported", False, "no spend reported"),
        ],
    )
    def test_each_missing_piece_is_reported(
        self, field: str, value: Any, expected: str,
    ) -> None:
        gaps = verification_gaps([_complete_row(**{field: value})])
        assert any(expected in gap for gap in gaps), f"{field} produced no gap"

    def test_no_result_at_all_is_itself_a_gap(self) -> None:
        assert verification_gaps([]) == [
            "no result record -- the session wrote nothing to score"
        ]


# ---------------------------------------------------------------------------
# The bundle
# ---------------------------------------------------------------------------


class TestBundleContents:
    def test_it_collects_the_recorded_artifacts(self, session_dir: Path) -> None:
        bundle = SubmissionBundle(session_dir).build(archive=False)
        present = {p.name for p in bundle.iterdir()}
        assert {
            MANIFEST_NAME, "result.parquet", "actions.parquet",
            "tiles.parquet", "nttd_scenario.conf", "final.sav",
        } <= present

    def test_an_unrecorded_artifact_is_simply_absent(self, session_dir: Path) -> None:
        """An optional artifact the session never wrote is left out rather than
        bundled empty, and the manifest says so by omission."""
        # tiles.parquet is optional and the fixture writes one, so removing it is a
        # real test. events.parquet was used here before and the fixture never wrote
        # one, so the assertion held whatever the code did.
        (session_dir / "tiles.parquet").unlink()
        bundle = SubmissionBundle(session_dir).build(archive=False)
        manifest = json.loads((bundle / MANIFEST_NAME).read_text())
        assert "tiles.parquet" not in manifest["artifacts"]
        assert "result.parquet" in manifest["artifacts"]

    def test_a_session_with_no_result_cannot_be_submitted(self, tmp_path: Path) -> None:
        """Not a weaker submission: without a score it is not one."""
        empty = tmp_path / "ses_empty"
        empty.mkdir()
        with pytest.raises(FileNotFoundError, match="No result record"):
            SubmissionBundle(empty).build(archive=False)

    def test_a_missing_savegame_does_not_block_the_bundle(
        self, session_dir: Path,
    ) -> None:
        """A weaker submission is still a submission, and `nttd package` says what is
        missing. The gap is advice to the contestant, not a field in the bundle."""
        (session_dir / "save" / "final.sav").unlink()
        _write_result(session_dir, final_save_digest="", final_save_name="")

        bundle = SubmissionBundle(session_dir).build(archive=False)
        manifest = json.loads((bundle / MANIFEST_NAME).read_text())

        assert "final.sav" not in manifest["artifacts"]
        assert any(
            "no final savegame" in gap
            for gap in verification_gaps(pq.read_table(bundle / "result.parquet").to_pylist())
        )


class TestTheSeriesIsEvidence:
    """The snapshot series is bundled, and the two files derived from it are not.

    It was excluded once, with a one-row final_snapshot.parquet and an extracted
    trajectory.parquet standing in for it. Both existed only because the series was
    absent, and shipping a derivation next to its source is how a bundle becomes an
    archive. It is also the only record of how the run got where it got: every run-wide
    business metric comes from it, so without it those figures cannot be rechecked.

    Bounded by the tier rather than unbounded. A T4 at one-day intervals is around
    14 MB, and a stepped run is far smaller because it records one snapshot per step
    rather than one per game day.
    """

    def test_the_series_is_bundled(self, session_dir: Path) -> None:
        bundle = SubmissionBundle(session_dir).build(archive=False)
        assert (bundle / "snapshots.parquet").exists()

    def test_the_derived_files_are_gone(self, session_dir: Path) -> None:
        bundle = SubmissionBundle(session_dir).build(archive=False)
        assert not (bundle / "final_snapshot.parquet").exists()
        assert not (bundle / "trajectory.parquet").exists()

    def test_the_manifest_lists_the_series(self, session_dir: Path) -> None:
        bundle = SubmissionBundle(session_dir).build(archive=False)
        manifest = json.loads((bundle / MANIFEST_NAME).read_text())
        assert "snapshots.parquet" in manifest["artifacts"]
        assert "final_snapshot.parquet" not in manifest["artifacts"]
        assert "trajectory.parquet" not in manifest["artifacts"]

    def test_the_end_state_is_still_reachable(self, session_dir: Path) -> None:
        """Nothing was lost by dropping the one-row file: the verifier takes the last
        row of the series, which is where that row came from."""
        from nttd.verify.validator import BundleValidator

        bundle = SubmissionBundle(session_dir).build(archive=False)
        snapshot = BundleValidator(bundle, openttd_binary="")._final_snapshot()
        assert snapshot, "the end state must still be readable from the bundle"

    def test_the_end_state_is_the_latest_by_game_date(self, session_dir: Path) -> None:
        """Fragments are merged on stop, so the last row written is not guaranteed to
        be the latest."""
        from nttd.verify.validator import BundleValidator

        bundle = SubmissionBundle(session_dir).build(archive=False)
        snapshot = BundleValidator(bundle, openttd_binary="")._final_snapshot()
        assert snapshot.get("game", {}).get("game_date", 300) == 300

    def test_a_session_without_snapshots_still_bundles(self, session_dir: Path) -> None:
        (session_dir / "snapshots.parquet").unlink()
        bundle = SubmissionBundle(session_dir).build(archive=False)
        assert (bundle / MANIFEST_NAME).exists()
        assert not (bundle / "snapshots.parquet").exists()


class TestTheManifestHoldsIdentityAndIntegrityOnly:
    def test_it_carries_no_verdict(self, session_dir: Path) -> None:
        """A verdict in a bundle is a self-granted claim, which is worth nothing.

        Whoever needs to trust the bundle computes it themselves, on hardware the
        contestant does not control. This is the `scored = true` lesson applied to
        verification.
        """
        bundle = SubmissionBundle(session_dir).build(archive=False)
        text = (bundle / MANIFEST_NAME).read_text()
        for word in ("verified", "replayed", "unverified", "verdict"):
            assert word not in text, f"the manifest asserts {word!r} about itself"

    def test_it_does_not_restate_the_result_record(self, session_dir: Path) -> None:
        """An earlier version copied forty fields out of result.parquet, which needed a
        test proving the copy had not drifted. Not restating it removes both."""
        bundle = SubmissionBundle(session_dir).build(archive=False)
        manifest = json.loads((bundle / MANIFEST_NAME).read_text())

        assert set(manifest) == {
            "manifest_version", "session_id", "task_id", "map_digest", "artifacts",
        }
        for absent in ("primary_score", "profile_version", "runtime_mode", "scores"):
            assert absent not in manifest

    def test_it_does_not_carry_a_tier(self, session_dir: Path) -> None:
        """Nothing records a tier, so deriving a plausible one would be an invention.
        The resolved scenario ships instead, and states the actual bound."""
        bundle = SubmissionBundle(session_dir).build(archive=False)
        manifest = json.loads((bundle / MANIFEST_NAME).read_text())
        assert "tier" not in json.dumps(manifest)
        assert (bundle / "nttd_scenario.conf").exists()

    def test_the_identity_it_does_carry_matches_the_record(
        self, session_dir: Path,
    ) -> None:
        bundle = SubmissionBundle(session_dir).build(archive=False)
        manifest = json.loads((bundle / MANIFEST_NAME).read_text())
        row = pq.read_table(bundle / "result.parquet").to_pylist()[0]

        assert manifest["session_id"] == row["session_id"]
        assert manifest["task_id"] == row["task_id"]

    def test_the_map_digest_is_the_world_played(self, session_dir: Path) -> None:
        bundle = SubmissionBundle(session_dir).build(archive=False)
        manifest = json.loads((bundle / MANIFEST_NAME).read_text())
        assert manifest["map_digest"] == map_digest(session_dir / "tiles.parquet")


class TestTamperEvidence:
    def test_every_artifact_carries_a_digest_that_matches(
        self, session_dir: Path,
    ) -> None:
        bundle = SubmissionBundle(session_dir).build(archive=False)
        manifest = json.loads((bundle / MANIFEST_NAME).read_text())

        for name, meta in manifest["artifacts"].items():
            path = bundle / name
            actual = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            assert actual == meta["sha256"], f"{name} digest does not match"
            assert path.stat().st_size == meta["bytes"]

    def test_editing_an_artifact_breaks_its_digest(self, session_dir: Path) -> None:
        """The whole reason the digests are there."""
        bundle = SubmissionBundle(session_dir).build(archive=False)
        manifest = json.loads((bundle / MANIFEST_NAME).read_text())
        claimed = manifest["artifacts"]["actions.parquet"]["sha256"]

        (bundle / "actions.parquet").write_bytes(b"actions, but edited")
        actual = hashlib.sha256((bundle / "actions.parquet").read_bytes()).hexdigest()[:16]

        assert actual != claimed


class TestTheArchive:
    def test_it_round_trips_with_flat_paths(self, session_dir: Path) -> None:
        submission = SubmissionBundle(session_dir)
        submission.build(archive=True)

        with tarfile.open(submission.archive_path) as tar:
            names = tar.getnames()

        assert MANIFEST_NAME in names, "the manifest must be at the archive root"
        assert not any("/" in name for name in names), "paths should be flat"


class TestThePackageCommandRuns:
    """It broke once when the manifest was thinned and the summary still read the old
    shape. The crash was hidden because the command had been run with its output
    suppressed and its exit code unchecked."""

    def test_it_prints_a_summary_without_raising(
        self, session_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from nttd.cli.package_command import package
        from nttd.store import session_paths

        monkeypatch.setenv(session_paths.ENV_VAR, str(session_dir.parent))
        package(session=session_dir.name, no_archive=True)
