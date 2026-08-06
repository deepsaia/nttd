"""Collects a finished session into a self-describing, tamper-evident bundle.

nttd is self-hosted, so a submission cannot mean "we watched it happen". It has to mean
"the artifacts are internally consistent and the score is recomputable". This assembles
the artifacts that make that checkable, and a manifest that says what they are.

**The manifest holds identity and integrity, and nothing else.** It carries the session
and task ids, the world fingerprint, and a digest per artifact. Everything about the run
-- score, provenance, mode, spend -- is in ``result.parquet``, which is sitting in the
same bundle. An earlier version projected forty fields out of that row into nested JSON,
which meant maintaining a test proving the copy had not drifted from the original. The
duplication created the need for the test; removing the duplication removed both.

**The manifest carries no verdict, deliberately.** A bundle that said "verified" would be
making a claim about itself that anyone could write -- the same defect as a scenario
declaring ``scored = true``, in a new place. A bundle carries evidence; whoever needs to
trust it computes the verdict themselves, which for a leaderboard means computing it on
their own infrastructure with their own nttd and GameScript. ``nttd verify`` run locally
is a self-check and predicts that verdict; it does not grant one.

**On signing.** The plan called for a signed manifest. With nobody operating nttd there
is no key authority, so a signature would prove authorship rather than honesty: a
contestant signs their own claim. The load-bearing part is the per-artifact digest,
which makes the bundle tamper-evident *after* the fact, and the map digest, which ties it
to a world anyone can regenerate. Signing belongs to whoever runs a board and wants
submissions attributable.

None of this defends against a contestant who patches their own nttd or GameScript. The
manifest pins a GameScript digest and OpenTTD reports a `Modified` flag, but a determined
forger self-hosting defeats any offline check. The honest posture is
good-faith-with-evidence.
"""

from __future__ import annotations

import json
import logging
import tarfile
from pathlib import Path
from typing import Any

from nttd.config.task_instance import file_digest
from nttd.runtime.final_save import FINAL_SAVE_NAME, SAVE_EXTENSION
from nttd.store.map_digest import map_digest
from nttd.store.result_writer import read_result

logger = logging.getLogger(__name__)

MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
BUNDLE_DIR_NAME = "submission"

# Recorded artifacts a verifier needs, and whether the bundle is useless without them.
#
# The full snapshot series is deliberately absent. No check reads it, and it dominates a
# long run: 2,000 snapshots measured 7.9 MB, so a T4 at one-day intervals is around 14 MB
# against roughly 250 KB for everything verification actually uses. A bundle should be
# the evidence, not the archive. Keep your own snapshots and link to them; the bundle
# carries the end state, which is what a score is computed from.
#
# tiles.parquet stays: no check opens it either, because the world check regenerates its
# own scan and compares digests, but it is what lets a human see *where* two worlds
# differ rather than only that they do.
_ARTIFACTS: tuple[tuple[str, bool], ...] = (
    ("result.parquet", True),
    ("actions.parquet", False),
    ("events.parquet", False),
    ("tiles.parquet", False),
    ("nttd_scenario.conf", False),
)

# The one snapshot the bundle does carry, written from the last row of the series.
FINAL_SNAPSHOT_NAME = "final_snapshot.parquet"

# The contestant company's series, extracted from the snapshots: ten integers a tick
# rather than the whole world as JSON. Roughly 13 bytes a row, so 11 KB for a 200-step
# run and 1.3 MB for the longest plausible real-time one, against 146 MB if the full
# series went in.
#
# It earns its place by making the run-wide metrics checkable. Endpoint figures can be
# recomputed from the savegame, but operating margin over the run, peak credit drawn,
# lowest cash and days to first profit come from the series, and without it they are
# claims rather than evidence. It is also what a trend chart is drawn from.
TRAJECTORY_NAME = "trajectory.parquet"


class SubmissionBundle:
    """Assembles one session's submission."""

    def __init__(self, session_dir: Path | str) -> None:
        self.session_dir = Path(session_dir)

    def build(self, archive: bool = True) -> Path:
        """Write the bundle and return its directory.

        Args:
            archive: Also write a `.tar.gz` beside it, which is what actually gets
                uploaded. The directory stays so a contestant can look inside.

        Raises:
            FileNotFoundError: The session has no result record, so there is nothing
                to submit. Raised rather than producing an empty bundle: a submission
                without a score is not a weaker submission, it is not one.
        """
        rows = read_result(self.session_dir)
        if not rows:
            raise FileNotFoundError(
                f"No result record in {self.session_dir}. It is written when the "
                f"session stops -- run `nttd session stop` first."
            )

        bundle_dir = self.session_dir / BUNDLE_DIR_NAME
        bundle_dir.mkdir(parents=True, exist_ok=True)

        copied = self._copy_artifacts(bundle_dir)
        manifest = self._manifest(rows, copied)
        (bundle_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2) + "\n")

        if archive:
            self._archive(bundle_dir)

        logger.info(
            "Submission bundle written to %s (%d artifacts)", bundle_dir, len(copied),
        )
        return bundle_dir

    @property
    def archive_path(self) -> Path:
        """Where build(archive=True) writes the tarball."""
        return self.session_dir / f"{self.session_dir.name}-submission.tar.gz"

    def _copy_artifacts(self, bundle_dir: Path) -> dict[str, Path]:
        """Copy the recorded artifacts in, returning the ones that were present."""
        copied: dict[str, Path] = {}

        for name, required in _ARTIFACTS:
            source = self.session_dir / name
            if not source.exists():
                if required:
                    raise FileNotFoundError(f"{source} is missing and is required")
                logger.info("%s was not recorded, so it is not in the bundle", name)
                continue
            destination = bundle_dir / name
            destination.write_bytes(source.read_bytes())
            copied[name] = destination

        trajectory = self._write_trajectory(bundle_dir)
        if trajectory:
            copied[trajectory.name] = trajectory

        final_snapshot = self._write_final_snapshot(bundle_dir)
        if final_snapshot is not None:
            copied[final_snapshot.name] = final_snapshot

        save = self.session_dir / "save" / f"{FINAL_SAVE_NAME}{SAVE_EXTENSION}"
        if save.exists():
            destination = bundle_dir / save.name
            destination.write_bytes(save.read_bytes())
            copied[save.name] = destination
        else:
            logger.warning(
                "No final savegame in %s, so the score in this bundle cannot be "
                "recomputed", self.session_dir,
            )

        return copied

    def _write_trajectory(self, bundle_dir: Path) -> Path | None:
        """Extract the contestant's series so the run-wide metrics can be rechecked.

        Written with the same function that computes them, so a verifier reading this
        back and recomputing is comparing like with like rather than reimplementing the
        formulas and hoping they agree.
        """
        rows = self._contestant_trajectory()
        if not rows:
            return None
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq

            destination = bundle_dir / TRAJECTORY_NAME
            pq.write_table(pa.Table.from_pylist(rows), destination, compression="zstd")
        except Exception:
            logger.exception("Could not write a trajectory for %s", self.session_dir)
            return None
        return destination

    def _contestant_trajectory(self) -> list[dict[str, int]]:
        """The scored company's series. A scored run has exactly one contestant."""
        from nttd.analysis import business_metrics
        from nttd.store.result_writer import read_result

        rows = read_result(self.session_dir)
        if not rows:
            return []
        return business_metrics.trajectory_rows(
            self.session_dir, int(rows[0].get("company_id", 0)),
        )

    def _write_final_snapshot(self, bundle_dir: Path) -> Path | None:
        """Write the last recorded snapshot, dropping the rest of the series.

        One row rather than thousands. The end state is what a score is computed from,
        and the intermediate series is analysis material a contestant can keep and link
        to. Named for what it is, so nobody reads a one-row file as a time series.
        """
        source = self.session_dir / "snapshots.parquet"
        if not source.exists():
            return None

        try:
            import pyarrow.parquet as pq

            table = pq.read_table(source)
            if table.num_rows == 0:
                return None
            dates = table.column("game_date").to_pylist()
            last = max(range(len(dates)), key=lambda index: dates[index])
            destination = bundle_dir / FINAL_SNAPSHOT_NAME
            pq.write_table(table.slice(last, 1), destination)
        except Exception:
            logger.exception("Could not extract a final snapshot from %s", source)
            return None

        return destination

    def _manifest(
        self, rows: list[dict[str, Any]], copied: dict[str, Path],
    ) -> dict[str, Any]:
        """Identity and integrity. The run itself is in result.parquet."""
        first = rows[0]
        return {
            "manifest_version": MANIFEST_VERSION,
            "session_id": first.get("session_id", ""),
            # Which problem was played. Everything else about the task -- seed,
            # settings digest, profile -- is in result.parquet.
            "task_id": first.get("task_id", ""),
            # The world fingerprint: regenerate the recorded seed and this must match.
            # Hashed from the terrain rather than from tiles.parquet, so two
            # generations of one seed agree.
            "map_digest": map_digest(self.session_dir / "tiles.parquet") or "",
            "artifacts": {
                name: {
                    "sha256": file_digest(path) or "",
                    "bytes": path.stat().st_size,
                }
                for name, path in sorted(copied.items())
            },
        }

    def _archive(self, bundle_dir: Path) -> None:
        """Tar the bundle for upload, with paths relative to the bundle root."""
        target = self.archive_path
        with tarfile.open(target, "w:gz") as tar:
            for path in sorted(bundle_dir.iterdir()):
                tar.add(path, arcname=path.name)
        logger.info("Submission archive written to %s", target)
