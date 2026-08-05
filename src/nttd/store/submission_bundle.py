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
# tiles.parquet is here because step 1 of verification regenerates the world and
# compares it: the digest alone proves a mismatch, the scan shows where.
_ARTIFACTS: tuple[tuple[str, bool], ...] = (
    ("result.parquet", True),
    ("actions.parquet", False),
    ("snapshots.parquet", False),
    ("events.parquet", False),
    ("tiles.parquet", False),
    ("nttd_scenario.conf", False),
)


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
