"""Find out how to actually pin OpenTTD map generation to a seed.

Setting game_creation.generation_seed in the per-session openttd.cfg does NOT
reproduce a world: two servers with the same cfg seed generated different maps.
OpenTTD also accepts `-G <seed>` on the command line. This tests both routes and
reports which (if either) makes generation deterministic.

Determinism here is the precondition for the ghost-race format: every contestant
must face the same world, and a submitted run must be re-generatable from its
declared task instance.

Usage:
    uv run python -m scripts.experiment_seed_determinism
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nttd.bridge.admin_client import AdminClient  # noqa: E402
from nttd.runtime.config_builder import build_session_config  # noqa: E402
from scripts.experiment_pause_and_time import (  # noqa: E402
    _SMALL_MAP_SETTINGS,
    ADMIN_PASSWORD,
    BASE_CONFIG,
    OPENTTD_BINARY,
    SCRATCH,
)

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("experiment")
logger.setLevel(logging.INFO)


async def _launch_and_fingerprint(
    name: str,
    game_port: int,
    settings: dict[str, str],
    extra_argv: list[str],
) -> dict[str, Any]:
    """Spawn a server with the given cfg settings and argv, return a world digest."""
    session_dir = SCRATCH / name
    if session_dir.exists():
        shutil.rmtree(session_dir)
    admin_port = game_port + 1

    merged = dict(_SMALL_MAP_SETTINGS)
    merged.update(settings)
    build_session_config(
        base_config_dir=BASE_CONFIG,
        session_dir=session_dir,
        game_port=game_port,
        admin_port=admin_port,
        admin_password=ADMIN_PASSWORD,
        settings=merged,
        agent_companies=1,
    )

    argv = [OPENTTD_BINARY, "-D", "-c", str(session_dir / "openttd.cfg"), *extra_argv]
    logger.info("[%s] %s", name, " ".join(argv[1:]))
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )

    client = AdminClient(host="127.0.0.1", port=admin_port)
    deadline = time.time() + 40.0
    while time.time() < deadline:
        if await client.connect(password=ADMIN_PASSWORD, name=f"seed_{name}"):
            break
        await asyncio.sleep(0.5)
    else:
        process.kill()
        raise RuntimeError(f"[{name}] admin port never came up")

    poll = asyncio.create_task(client.poll_loop(), name=f"poll_{name}")
    await client.subscribe_defaults()
    for _ in range(40):
        if (await client.send_gamescript("ping", timeout=5.0)).get("success"):
            break
        await asyncio.sleep(0.5)

    try:
        towns = (await client.send_gamescript("get_towns", timeout=30.0)).get("result") or []
        inds = (await client.send_gamescript("get_industries", timeout=30.0)).get("result") or []

        def digest(rows: list[Any], keys: tuple[str, ...]) -> str | None:
            if not isinstance(rows, list):
                return None
            norm = sorted(
                tuple(str(r.get(k)) for k in keys) for r in rows if isinstance(r, dict)
            )
            return hashlib.sha256(json.dumps(norm).encode()).hexdigest()[:16]

        return {
            "town_count": len(towns) if isinstance(towns, list) else None,
            "industry_count": len(inds) if isinstance(inds, list) else None,
            "towns_sha": digest(towns, ("name", "x", "y")),
            "industries_sha": digest(inds, ("type_name", "x", "y")),
            "first_town": (
                {k: towns[0].get(k) for k in ("name", "x", "y")}
                if isinstance(towns, list) and towns else None
            ),
        }
    finally:
        try:
            await client.disconnect()
        except Exception:
            logger.debug("[%s] disconnect failed", name)
        poll.cancel()
        try:
            process.terminate()
            await asyncio.wait_for(process.wait(), timeout=8.0)
        except Exception:
            process.kill()


async def main() -> None:
    SCRATCH.mkdir(exist_ok=True)
    seed = 4242
    results: dict[str, Any] = {"seed": seed}

    # Route A: cfg key only (what nttd would do today).
    a1 = await _launch_and_fingerprint(
        "sd_cfg_a", 5100, {"game_creation.generation_seed": str(seed)}, []
    )
    a2 = await _launch_and_fingerprint(
        "sd_cfg_b", 5110, {"game_creation.generation_seed": str(seed)}, []
    )
    results["cfg_only"] = {
        "run_a": a1, "run_b": a2,
        "identical": a1["towns_sha"] == a2["towns_sha"]
        and a1["industries_sha"] == a2["industries_sha"],
    }

    # Route B: -G on the command line.
    b1 = await _launch_and_fingerprint("sd_argv_a", 5120, {}, ["-G", str(seed)])
    b2 = await _launch_and_fingerprint("sd_argv_b", 5130, {}, ["-G", str(seed)])
    results["argv_G"] = {
        "run_a": b1, "run_b": b2,
        "identical": b1["towns_sha"] == b2["towns_sha"]
        and b1["industries_sha"] == b2["industries_sha"],
    }

    # Route C: -G plus the cfg key, both set.
    c1 = await _launch_and_fingerprint(
        "sd_both_a", 5140, {"game_creation.generation_seed": str(seed)}, ["-G", str(seed)]
    )
    c2 = await _launch_and_fingerprint(
        "sd_both_b", 5150, {"game_creation.generation_seed": str(seed)}, ["-G", str(seed)]
    )
    results["cfg_and_argv"] = {
        "run_a": c1, "run_b": c2,
        "identical": c1["towns_sha"] == c2["towns_sha"]
        and c1["industries_sha"] == c2["industries_sha"],
    }

    # Control: a different seed via the winning route must differ.
    ctl = await _launch_and_fingerprint("sd_ctl", 5160, {}, ["-G", str(seed + 7)])
    results["control_different_seed"] = ctl
    results["control_differs_from_argv"] = ctl["towns_sha"] != b1["towns_sha"]

    winners = [k for k in ("argv_G", "cfg_and_argv", "cfg_only") if results[k]["identical"]]
    results["verdict"] = (
        f"deterministic via: {', '.join(winners)}" if winners
        else "NO route produced a reproducible map"
    )

    (SCRATCH / "results_seed.json").write_text(json.dumps(results, indent=2, default=str))
    print("\n" + json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
