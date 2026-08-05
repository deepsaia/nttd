"""Checks a submission bundle and returns a verdict.

Runs in two places, from this one implementation:

  * on a contestant's machine via ``nttd verify``, where the verdict is **advisory**.
    Whoever ran it could have edited the code that produced it, so it predicts what a
    board will say rather than granting anything.
  * in a leaderboard's ingest, on infrastructure the contestant does not control, from a
    pinned nttd. That verdict is the one that appears on a board.

Sharing the code is the point rather than a compromise: a contestant should be able to
predict the verdict instead of being surprised by it. The protection is not that the
checks are secret -- a self-hoster can read them -- it is that the *execution* happens
somewhere they cannot reach, with the verifier's own GameScript reading the score.

Cheap checks first. If the artifacts do not describe each other consistently, there is no
point spawning OpenTTD to recompute a score they do not support.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from nttd.config.scenario_config import load, scenario_to_settings
from nttd.runtime.final_save import FINAL_SAVE_NAME, SAVE_EXTENSION
from nttd.schemas.verification import CheckOutcome, Verdict, VerificationReport
from nttd.store.result_writer import read_result
from nttd.verify import checks, replay
from nttd.verify.headless_openttd import HeadlessOpenTTD

logger = logging.getLogger(__name__)

# Ports for the throwaway server. High and fixed: verification is not concurrent with
# itself, and a session's own range starts at 4000.
VERIFY_GAME_PORT = 4890
VERIFY_ADMIN_PORT = 4891


class BundleValidator:
    """Runs the checks over one bundle and reduces them to a verdict."""

    def __init__(
        self,
        bundle_dir: Path | str,
        openttd_binary: str,
        base_config_dir: Path | str = "ottd_config",
    ) -> None:
        self.bundle_dir = Path(bundle_dir)
        self._binary = openttd_binary
        self._base_config_dir = Path(base_config_dir)

    async def verify(self, regenerate: bool = False) -> VerificationReport:
        """Check the bundle.

        Args:
            regenerate: Also regenerate the world from the declared seed and compare
                terrain. This is the only route to ``verified``, and it costs a map
                generation plus a full tile scan, so it is opt-in rather than default.
        """
        manifest = checks.read_manifest(self.bundle_dir)
        if manifest is None:
            return VerificationReport(
                verdict=Verdict.UNVERIFIED,
                checks=[CheckOutcome(
                    name=checks.ARTIFACT_INTEGRITY, passed=False,
                    detail=f"no readable manifest.json in {self.bundle_dir}",
                )],
            )

        outcomes: list[CheckOutcome] = [
            checks.artifact_integrity(self.bundle_dir, manifest),
        ]

        rows = read_result(self.bundle_dir)
        if not rows:
            outcomes.append(CheckOutcome(
                name=checks.ACTION_LOG_CONSISTENT, passed=False,
                detail="no result record in the bundle, so there is nothing to check",
            ))
            return self._report(manifest, outcomes, regenerate)

        actions = self._actions()
        outcomes.append(checks.action_log_consistent(actions, rows[0]))
        outcomes.append(checks.no_forbidden_capability(actions, rows[0]))

        savegame = self.bundle_dir / f"{FINAL_SAVE_NAME}{SAVE_EXTENSION}"
        outcomes.append(await replay.savegame_readable(self._binary, savegame))

        if outcomes[-1].passed:
            outcomes.append(await self._recompute_score(savegame, rows))
        else:
            outcomes.append(CheckOutcome(
                name=replay.SCORE_RECOMPUTED,
                detail="skipped: the savegame could not be read",
            ))

        if regenerate:
            outcomes.append(await self._regenerate_world(manifest, rows[0]))
        else:
            outcomes.append(CheckOutcome(
                name=replay.WORLD_REGENERATED,
                detail="not requested: pass --regenerate to earn a verified verdict",
            ))

        return self._report(manifest, outcomes, regenerate)

    def _actions(self) -> list[dict[str, Any]]:
        """Read the bundled action log, or an empty list if it was not recorded."""
        path = self.bundle_dir / "actions.parquet"
        if not path.exists():
            return []
        try:
            import pyarrow.parquet as pq

            return pq.read_table(path).to_pylist()
        except Exception:
            logger.exception("Could not read %s", path)
            return []

    async def _recompute_score(
        self, savegame: Path, rows: list[dict[str, Any]],
    ) -> CheckOutcome:
        """Reload the savegame on a throwaway server and rescore it."""
        scratch = Path(tempfile.mkdtemp(prefix="nttd-verify-reload-"))
        server = self._server(scratch)
        try:
            if not await server.start(savegame=savegame):
                return CheckOutcome(
                    name=replay.SCORE_RECOMPUTED, passed=False,
                    detail="could not reload the savegame with a responding GameScript",
                )
            return await replay.score_recomputed(server, rows)
        finally:
            await server.stop()
            shutil.rmtree(scratch, ignore_errors=True)

    async def _regenerate_world(
        self, manifest: dict[str, Any], result: dict[str, Any],
    ) -> CheckOutcome:
        """Generate the declared seed afresh and compare its terrain."""
        seed = result.get("map_seed")
        if seed is None or int(seed) < 0:
            return CheckOutcome(
                name=replay.WORLD_REGENERATED, passed=False,
                detail="the run pinned no seed, so its world cannot be regenerated",
            )

        settings = self._settings()
        if settings is None:
            return CheckOutcome(
                name=replay.WORLD_REGENERATED, passed=False,
                detail="no readable nttd_scenario.conf, so the world cannot be rebuilt",
            )

        scratch = Path(tempfile.mkdtemp(prefix="nttd-verify-world-"))
        server = self._server(scratch)
        try:
            if not await server.start(settings=settings, map_seed=int(seed)):
                return CheckOutcome(
                    name=replay.WORLD_REGENERATED, passed=False,
                    detail="could not generate the declared seed with a responding GameScript",
                )
            return await replay.world_regenerated(
                server, manifest.get("map_digest", ""), scratch,
            )
        finally:
            await server.stop()
            shutil.rmtree(scratch, ignore_errors=True)

    def _settings(self) -> dict[str, str] | None:
        """Resolve the bundled scenario into OpenTTD settings."""
        scenario = self.bundle_dir / "nttd_scenario.conf"
        if not scenario.exists():
            return None
        try:
            return scenario_to_settings(load(scenario), strict=False)
        except Exception:
            logger.exception("Could not resolve %s", scenario)
            return None

    def _server(self, scratch: Path) -> HeadlessOpenTTD:
        """A throwaway server outside the bundle.

        Outside deliberately: verifying must not change what it inspects, or a bundle
        would differ after being checked. It also means a read-only extract can be
        verified, which is how a board's ingest will see one.
        """
        return HeadlessOpenTTD(
            openttd_binary=self._binary,
            base_config_dir=self._base_config_dir,
            work_dir=scratch / "work",
            game_port=VERIFY_GAME_PORT,
            admin_port=VERIFY_ADMIN_PORT,
        )

    def _report(
        self,
        manifest: dict[str, Any],
        outcomes: list[CheckOutcome],
        regenerate: bool,
    ) -> VerificationReport:
        """Reduce the outcomes to a verdict."""
        return VerificationReport(
            verdict=_verdict(outcomes, regenerate),
            session_id=manifest.get("session_id", ""),
            task_id=manifest.get("task_id", ""),
            checks=outcomes,
        )


def _verdict(outcomes: list[CheckOutcome], regenerate: bool) -> Verdict:
    """Decide the verdict from the checks that ran.

    ``unverified`` is for a bundle that cannot be checked, which includes one whose
    artifacts do not match their digests: a tampered bundle is not a failed run, it is
    an unusable submission.
    """
    by_name = {outcome.name: outcome for outcome in outcomes}

    if by_name.get(checks.ARTIFACT_INTEGRITY, CheckOutcome(name="")).passed is not True:
        return Verdict.UNVERIFIED
    if by_name.get(replay.SCORE_RECOMPUTED, CheckOutcome(name="")).passed is not True:
        return Verdict.UNVERIFIED

    if any(outcome.passed is False for outcome in outcomes):
        # Something that ran did not pass. The score is still recomputable, so the run
        # is replayed rather than unusable, and the failure is named in the report.
        return Verdict.REPLAYED

    if not regenerate:
        return Verdict.REPLAYED
    return Verdict.VERIFIED
