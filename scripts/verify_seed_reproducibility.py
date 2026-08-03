"""Verify seed reproducibility through nttd's real session code path.

scripts/experiment_seed_determinism.py established that `-G` works and the cfg
key alone does not. This checks that nttd's OWN plumbing -- scenario config ->
scenario_to_settings -> SessionManager -> SessionRuntime.start_server -- actually
delivers a reproducible map, rather than testing OpenTTD directly.

Spawns two sessions from the same seeded scenario and one from a different seed,
then compares world digests.

Usage:
    uv run python -m scripts.verify_seed_reproducibility
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nttd.config.scenario_config import load, scenario_to_settings  # noqa: E402
from nttd.db.repositories import session_repo  # noqa: E402
from nttd.runtime.session_manager import SessionManager  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("verify")
logger.setLevel(logging.INFO)

REPO_ROOT = Path(__file__).parent.parent
SCRATCH = REPO_ROOT / ".experiment_runs" / "seed_verify"
OPENTTD_BINARY = "/Applications/OpenTTD.app/Contents/MacOS/openttd"

_SCENARIO = """
scenario {{
  name = "seed-verify"
  map {{
    size_x = 256
    size_y = 256
    landscape = "temperate"
    number_towns = "normal"
    industry_density = "normal"
    starting_year = 1960
    seed = {seed}
  }}
  companies {{ num_ai_companies = 0 }}
  runtime {{ mode = "async_realtime" }}
  end_conditions {{ time_limit {{ enabled = false }} }}
}}
"""


async def _digest_world(manager: SessionManager, session_id: str) -> dict[str, Any]:
    """Read the generated world from a running session and digest it."""
    runtime = manager.get_runtime(session_id)
    if runtime is None:
        raise RuntimeError(f"{session_id}: no runtime")
    c = runtime.admin_client

    for _ in range(40):
        if (await c.send_gamescript("ping", timeout=5.0)).get("success"):
            break
        await asyncio.sleep(0.5)

    towns = (await c.send_gamescript("get_towns", timeout=30.0)).get("result") or []
    inds = (await c.send_gamescript("get_industries", timeout=30.0)).get("result") or []

    def digest(rows: Any, keys: tuple[str, ...]) -> str | None:
        if not isinstance(rows, list):
            return None
        norm = sorted(tuple(str(r.get(k)) for k in keys) for r in rows if isinstance(r, dict))
        return hashlib.sha256(json.dumps(norm).encode()).hexdigest()[:16]

    return {
        "map_seed_on_runtime": runtime.map_seed,
        "town_count": len(towns) if isinstance(towns, list) else None,
        "industry_count": len(inds) if isinstance(inds, list) else None,
        "towns_sha": digest(towns, ("name", "x", "y")),
        "industries_sha": digest(inds, ("type_name", "x", "y")),
    }


async def _run_one(label: str, seed: int, port_start: int) -> dict[str, Any]:
    """Start one session from a seeded scenario and digest its world."""
    conf = SCRATCH / f"{label}.conf"
    conf.write_text(_SCENARIO.format(seed=seed))
    settings = scenario_to_settings(load(conf))

    # session_repo keeps a module-global sessions dir, so the manager and the
    # repo must agree on it or the session record and its artifacts diverge.
    sessions_dir = SCRATCH / "sessions"
    session_repo.set_sessions_dir(sessions_dir)
    manager = SessionManager(
        openttd_binary=OPENTTD_BINARY,
        base_config_dir=REPO_ROOT / "ottd_config",
        sessions_dir=sessions_dir,
        admin_password="nttd",
        port_range_start=port_start,
    )
    session_id = f"ses_{label}"
    await session_repo.create_session(session_id, name=label)
    try:
        await manager.start_session(session_id, settings=settings, agent_companies=1)
        return await _digest_world(manager, session_id)
    finally:
        try:
            await manager.stop_session(session_id, end_reason="verify_done")
        except Exception:
            logger.exception("%s: stop failed", label)


async def main() -> None:
    shutil.rmtree(SCRATCH, ignore_errors=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)

    out: dict[str, Any] = {}
    out["a_seed_1001"] = await _run_one("a_1001", 1001, 5300)
    out["b_seed_1001"] = await _run_one("b_1001", 1001, 5320)
    out["c_seed_2002"] = await _run_one("c_2002", 2002, 5340)

    a, b, c = out["a_seed_1001"], out["b_seed_1001"], out["c_seed_2002"]
    out["same_seed_reproducible"] = (
        a["towns_sha"] == b["towns_sha"] and a["industries_sha"] == b["industries_sha"]
    )
    out["different_seed_differs"] = a["towns_sha"] != c["towns_sha"]
    out["verdict"] = (
        "PASS -- nttd's own path is reproducible"
        if out["same_seed_reproducible"] and out["different_seed_differs"]
        else "FAIL"
    )

    (SCRATCH / "results.json").write_text(json.dumps(out, indent=2, default=str))
    print("\n" + json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
