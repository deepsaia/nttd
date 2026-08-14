"""The verification checks that need OpenTTD: reload the save, regenerate the world.

These are what make a self-hosted submission checkable at all. Everything else confirms
the bundle is internally consistent; these two confirm it corresponds to a real game.

Both run against a **validator-supplied** config directory, so the GameScript that reads
the score is the one the verifier trusts rather than the one the contestant shipped.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from nttd.analysis.score import SCORE_VERSION, score_company
from nttd.schemas.company import Company
from nttd.schemas.verification import CheckOutcome
from nttd.store.map_digest import map_digest
from nttd.store.terrain_scan import scan_terrain
from nttd.store.tile_writer import TileWriter
from nttd.verify.headless_openttd import HeadlessOpenTTD

logger = logging.getLogger(__name__)

SAVEGAME_READABLE = "savegame_readable"
SCORE_RECOMPUTED = "score_recomputed"
WORLD_REGENERATED = "world_regenerated"

_INSPECT_TIMEOUT_SECONDS = 30.0
_TERRAIN_TIMEOUT_SECONDS = 120.0


async def savegame_readable(openttd_binary: str, savegame: Path) -> CheckOutcome:
    """``openttd -q`` can read the save, and reports whether content was modified.

    Cheap and worth doing before spawning a server: measured exit 0 on a complete save
    and exit 1 on one truncated to 40%, on an empty file, and on a missing one.
    """
    if not savegame.exists():
        return CheckOutcome(
            name=SAVEGAME_READABLE, passed=False,
            detail="no final.sav in the bundle, so the score cannot be recomputed",
        )

    try:
        process = await asyncio.create_subprocess_exec(
            openttd_binary, "-q", str(savegame),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(
            process.communicate(), timeout=_INSPECT_TIMEOUT_SECONDS,
        )
    except (OSError, TimeoutError, asyncio.TimeoutError) as exc:
        return CheckOutcome(
            name=SAVEGAME_READABLE, passed=False,
            detail=f"could not run openttd -q: {exc}",
        )

    report = stdout.decode(errors="replace")
    if process.returncode != 0:
        return CheckOutcome(
            name=SAVEGAME_READABLE, passed=False,
            detail=f"openttd -q rejected the savegame (exit {process.returncode})",
        )

    modified = _field(report, "Modified")
    version = _field(report, "Savegame ver")
    # Reported rather than failed on. A Modified flag means the content set differed,
    # which is worth a reader's attention but is not by itself a forged save.
    return CheckOutcome(
        name=SAVEGAME_READABLE, passed=True,
        detail=f"savegame version {version or '?'}, Modified={modified or '?'}",
    )


async def score_recomputed(
    server: HeadlessOpenTTD, result_rows: list[dict[str, Any]],
) -> CheckOutcome:
    """Reload the save and check the recorded scores are the ones it produces.

    This is the check the ``replayed`` verdict rests on: whatever else a bundle claims,
    the savegame either supports its scores or it does not.
    """
    reply = await server.query("get_companies")
    if not reply.get("success"):
        return CheckOutcome(
            name=SCORE_RECOMPUTED, passed=False,
            detail=f"the reloaded save did not answer get_companies: {reply.get('error')}",
        )

    recomputed = {}
    for raw in reply.get("result") or []:
        try:
            company = Company(**raw)
        except Exception:
            logger.debug("Skipping an unparseable company from the reloaded save")
            continue
        recomputed[company.id] = score_company(company)

    problems: list[str] = []
    checked = 0
    for row in result_rows:
        company_id = row.get("company_id")
        score = recomputed.get(company_id)
        if score is None:
            problems.append(f"company {company_id} is absent from the reloaded save")
            continue
        # A bundle scored under an older definition cannot be compared against this one. The
        # tiebreak changed meaning at v3, from the quarter in progress to the run total, so a
        # v2 result reads as a mismatch of thousands against zero. That is a version skew and
        # not a claim the entrant made falsely, and reporting it as fraud would be wrong.
        recorded_version = row.get("score_version")
        if recorded_version and recorded_version != SCORE_VERSION:
            problems.append(
                f"company {company_id}: scored under {recorded_version}, this verifier is "
                f"{SCORE_VERSION}; rescore the bundle rather than comparing across versions"
            )
            continue
        checked += 1
        if score.primary != row.get("primary_score"):
            problems.append(
                f"company {company_id}: save gives {score.primary}, "
                f"result claims {row.get('primary_score')}"
            )
        if score.tiebreak != row.get("tiebreak_cargo"):
            problems.append(
                f"company {company_id}: save gives {score.tiebreak} cargo, "
                f"result claims {row.get('tiebreak_cargo')}"
            )

    if problems:
        return CheckOutcome(
            name=SCORE_RECOMPUTED, passed=False, detail="; ".join(problems),
        )
    return CheckOutcome(
        name=SCORE_RECOMPUTED, passed=True,
        detail=f"{checked} company score(s) recomputed from the savegame and matched",
    )


async def world_regenerated(
    server: HeadlessOpenTTD, claimed_digest: str, scratch_dir: Path,
) -> CheckOutcome:
    """Scan the regenerated world's terrain and compare it to the bundle's digest.

    This is what separates ``verified`` from ``replayed``: without it, a contestant could
    play a hand-picked world and declare a hard seed, and every other check would pass.
    """
    if not claimed_digest:
        return CheckOutcome(
            name=WORLD_REGENERATED, passed=False,
            detail="the bundle declares no map digest, so there is nothing to compare",
        )

    # Through the same scan the session capture uses, so the two cannot read the map
    # differently. They did: this asked for one unbounded band and read the reply as a
    # list, long after the handler was bounded and started answering with a table. It got
    # a table, hashed nothing, and reported that every submission regenerated to an empty
    # world.
    async def ask(action: str, params: dict[str, Any]) -> dict[str, Any]:
        return await server.query(action, params, timeout=_TERRAIN_TIMEOUT_SECONDS)

    rows = await scan_terrain(ask)
    if rows is None:
        return CheckOutcome(
            name=WORLD_REGENERATED, passed=False,
            detail="the regenerated world did not answer get_map_terrain",
        )
    writer = TileWriter("verify", data_dir=str(scratch_dir))
    written = writer.write_full_scan(rows)
    if not written:
        return CheckOutcome(
            name=WORLD_REGENERATED, passed=False,
            detail="the regenerated world produced no terrain to hash",
        )

    actual = map_digest(scratch_dir / "verify" / "tiles.parquet")
    if actual != claimed_digest:
        return CheckOutcome(
            name=WORLD_REGENERATED, passed=False,
            detail=(
                f"regenerating the declared seed gives {actual}, but the bundle "
                f"claims {claimed_digest} -- this is not the world that was played"
            ),
        )
    return CheckOutcome(
        name=WORLD_REGENERATED, passed=True,
        detail=f"{written} tiles regenerated from the declared seed, digest {actual}",
    )


def _field(report: str, label: str) -> str:
    """Pull one value out of ``openttd -q`` output, which is `Label: value` lines."""
    for line in report.splitlines():
        if line.startswith(label):
            return line.split(":", 1)[1].strip()
    return ""
