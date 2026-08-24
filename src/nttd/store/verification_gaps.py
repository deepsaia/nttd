"""What would stop somebody else checking a run.

One implementation because two consumers need the same answer: ``nttd result`` prints
these so a contestant sees them before submitting, and a submission bundle records them
so a reader of the bundle sees the same list without re-deriving it. Two copies would
drift, and the copy that drifted would be the one claiming a run was verifiable.

These are gaps, not failures. A run with gaps still happened and still has a score; the
gaps say how much of it a third party can confirm.
"""

from __future__ import annotations

from typing import Any

# Sentinel written when a session ran without a pinned seed.
_NO_SEED = -1


def verification_gaps(rows: list[dict[str, Any]]) -> list[str]:
    """Return one message per gap, in descending order of how much it costs.

    Args:
        rows: The result rows for one session, as ``read_result`` returns them.
    """
    if not rows:
        return ["no result record -- the session wrote nothing to score"]

    first = rows[0]
    gaps: list[str] = []

    if not first.get("scored_session"):
        gaps.append(
            "session was not scored -- operator powers were available throughout, "
            "so the run is not a benchmark result"
        )
    if not first.get("clean_run"):
        gaps.append(
            f"{first.get('blocked_attempts')} operator operation(s) attempted and "
            f"refused ({first.get('blocked_operations')}) -- nothing took effect, but "
            f"the run is not clean"
        )
    if not first.get("final_save_digest"):
        gaps.append(
            "no final savegame -- the score cannot be recomputed by anyone else, so "
            "it is self-reported. This is the single largest gap a submission can have"
        )
    if int(first.get("map_seed", _NO_SEED)) < 0:
        gaps.append("no map seed -- the world cannot be regenerated")
    if not first.get("task_id"):
        gaps.append("no task_id -- the run is not tied to a task instance")
    if first.get("nttd_git_dirty"):
        gaps.append(
            "uncommitted changes -- the recorded revision does not reproduce this run"
        )
    if not first.get("gamescript_digest"):
        gaps.append("GameScript not pinned")
    if not any(row.get("spend_is_reported") for row in rows):
        gaps.append(
            "no spend reported -- model, tokens, and cost are absent because nttd "
            "cannot observe them. Have your runner POST /report to include them"
        )
    elif not any(row.get("cost_is_reported") for row in rows):
        # Reported tokens with no price is its own state, and saying "no spend reported"
        # over it would be wrong twice: the tokens ARE there, and the reason the cost is
        # not is usually a model missing from the runner's price table rather than a
        # runner that never reported.
        gaps.append(
            "tokens reported without a price -- what the run used is recorded, what it "
            "cost is not, so the board's cost column stays blank"
        )

    return gaps
