"""The verification checks that need nothing but the bundle.

Cheap, deterministic, and worth running first: if the artifacts do not describe each
other consistently there is no point spawning OpenTTD to recompute a score they do not
support.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from nttd.actions.gate import OPERATOR_ACTIONS
from nttd.schemas.verification import CheckOutcome

logger = logging.getLogger(__name__)

ARTIFACT_INTEGRITY = "artifact_integrity"
ACTION_LOG_CONSISTENT = "action_log_consistent"
NO_FORBIDDEN_CAPABILITY = "no_forbidden_capability"

# Matches the truncation `file_digest` uses, so digests are comparable.
_DIGEST_LENGTH = 16


def artifact_integrity(bundle_dir: Path, manifest: dict[str, Any]) -> CheckOutcome:
    """Every artifact the manifest lists is present and hashes to what it claims.

    This is what makes the bundle tamper-evident. Editing a score upward after the fact
    changes result.parquet's digest, and the manifest still carries the old one.
    """
    artifacts = manifest.get("artifacts") or {}
    if not artifacts:
        return CheckOutcome(
            name=ARTIFACT_INTEGRITY, passed=False,
            detail="the manifest lists no artifacts",
        )

    problems: list[str] = []
    for name, meta in sorted(artifacts.items()):
        path = bundle_dir / name
        if not path.exists():
            problems.append(f"{name} is listed but missing")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()[:_DIGEST_LENGTH]
        if actual != meta.get("sha256"):
            problems.append(f"{name} hashes to {actual}, manifest claims {meta.get('sha256')}")
        elif path.stat().st_size != meta.get("bytes"):
            problems.append(f"{name} is {path.stat().st_size} bytes, manifest claims {meta.get('bytes')}")

    if problems:
        return CheckOutcome(
            name=ARTIFACT_INTEGRITY, passed=False, detail="; ".join(problems),
        )
    return CheckOutcome(
        name=ARTIFACT_INTEGRITY, passed=True,
        detail=f"{len(artifacts)} artifact(s) match their digests",
    )


def action_log_consistent(
    actions: list[dict[str, Any]], result: dict[str, Any],
) -> CheckOutcome:
    """The action log describes the run the result claims.

    Three things a fabricated or spliced log tends to get wrong: the action counts, the
    ordering of game dates, and actions dated outside the run's own window.
    """
    problems: list[str] = []

    recorded_total = int(result.get("total_actions") or 0)
    recorded_success = int(result.get("successful_actions") or 0)
    company_id = result.get("company_id")

    mine = [a for a in actions if a.get("company_id") == company_id]
    counted = len(mine)
    counted_success = sum(1 for a in mine if a.get("status") == "success")

    if counted != recorded_total:
        problems.append(
            f"result claims {recorded_total} action(s) for company {company_id} "
            f"but the log holds {counted}"
        )
    if counted_success != recorded_success:
        problems.append(
            f"result claims {recorded_success} successful but the log holds {counted_success}"
        )

    dates = [a.get("game_date") for a in actions if a.get("game_date") is not None]
    if dates != sorted(dates):
        problems.append("game dates are not monotonic, so the log has been reordered")

    start = result.get("start_game_date")
    end = result.get("end_game_date")
    if dates and start is not None and end is not None and end >= start:
        outside = [d for d in dates if d < start or d > end]
        if outside:
            problems.append(
                f"{len(outside)} action(s) fall outside the run's window "
                f"[{start}, {end}], earliest {min(outside)}"
            )

    if problems:
        return CheckOutcome(
            name=ACTION_LOG_CONSISTENT, passed=False, detail="; ".join(problems),
        )
    return CheckOutcome(
        name=ACTION_LOG_CONSISTENT, passed=True,
        detail=f"{counted} action(s), {counted_success} successful, dates in order",
    )


def no_forbidden_capability(
    actions: list[dict[str, Any]], result: dict[str, Any],
) -> CheckOutcome:
    """No operator-tier action succeeded, and the clean-run flag matches the log.

    A refused attempt does not void a run -- nothing happened -- so what matters is that
    none *succeeded*, and that the result's own accounting of refusals agrees with the
    log rather than under-reporting it.
    """
    problems: list[str] = []

    succeeded = sorted({
        str(a.get("action_type")) for a in actions
        if a.get("action_type") in OPERATOR_ACTIONS and a.get("status") == "success"
    })
    if succeeded:
        problems.append(
            f"operator action(s) succeeded: {', '.join(succeeded)} -- this run had "
            f"powers no human has"
        )

    refused = [
        a for a in actions
        if a.get("status") in ("rejected", "blocked")
        and a.get("action_type") in OPERATOR_ACTIONS
    ]
    claims_clean = bool(result.get("clean_run"))
    if refused and claims_clean:
        problems.append(
            f"result claims a clean run but the log holds {len(refused)} refused "
            f"operator attempt(s)"
        )

    if problems:
        return CheckOutcome(
            name=NO_FORBIDDEN_CAPABILITY, passed=False, detail="; ".join(problems),
        )
    return CheckOutcome(
        name=NO_FORBIDDEN_CAPABILITY, passed=True,
        detail=(
            "no operator action succeeded"
            + (f"; {len(refused)} refused and disclosed" if refused else "")
        ),
    )


def read_manifest(bundle_dir: Path) -> dict[str, Any] | None:
    """Read a bundle's manifest, or None if it is absent or unreadable."""
    path = bundle_dir / "manifest.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        logger.exception("Could not parse %s", path)
        return None
