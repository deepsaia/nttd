"""Can a self-hosted run be validated offline, without us hosting the session?

Contestants run nttd themselves, so we never own the world. Validation therefore
has to work on submitted artifacts. This measures what is actually verifiable.

Test 1 -- Savegame as evidence. Produce a savegame via rcon, then inspect it with
    `openttd -q` (offline, no server) and by loading it into a fresh headless
    server and re-reading the score from the GameScript. If the score can be
    recomputed from the save, the save is the authoritative artifact and the
    submitted score is checkable rather than trusted.

Test 2 -- Map determinism. Generate the same seed twice in separate processes and
    compare the resulting worlds. If identical, seed+settings pins the task
    instance, so a contestant cannot quietly play an easier map than claimed.

Usage:
    uv run python -m scripts.experiment_replay_validation
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scripts.experiment_pause_and_time import (  # noqa: E402
    OPENTTD_BINARY,
    SCRATCH,
    Server,
    _game_date,
    _spawn,
    _teardown,
)

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("experiment")
logger.setLevel(logging.INFO)

_DELTAS = [(1, 0), (0, 1), (-1, 0), (0, -1)]


async def _world_fingerprint(server: Server) -> dict[str, Any]:
    """Summarise the generated world so two runs can be compared."""
    c = server.client
    towns = (await c.send_gamescript("get_towns", timeout=30.0)).get("result") or []
    inds = (await c.send_gamescript("get_industries", timeout=30.0)).get("result") or []
    msize = (await c.send_gamescript("get_map_size", timeout=15.0)).get("result") or {}

    def digest(rows: list[Any], keys: tuple[str, ...]) -> str:
        norm = sorted(
            tuple(str(r.get(k)) for k in keys) for r in rows if isinstance(r, dict)
        )
        return hashlib.sha256(json.dumps(norm).encode()).hexdigest()[:16]

    return {
        "map_size": msize,
        "town_count": len(towns) if isinstance(towns, list) else None,
        "industry_count": len(inds) if isinstance(inds, list) else None,
        "towns_sha": digest(towns, ("name", "x", "y")) if isinstance(towns, list) else None,
        "industries_sha": digest(inds, ("type_name", "x", "y")) if isinstance(inds, list) else None,
        "first_towns": [
            {k: t.get(k) for k in ("name", "x", "y", "population")}
            for t in (towns[:3] if isinstance(towns, list) else [])
        ],
    }


async def _company_score(server: Server) -> dict[str, Any]:
    """Read the authoritative per-company score fields from the GS."""
    r = await server.client.send_gamescript("get_companies", timeout=15.0)
    rows = r.get("result") or []
    return {
        "companies": [
            {k: c.get(k) for k in
             ("id", "name", "performance_rating", "company_value", "money", "loan", "q0_cargo")}
            for c in rows if isinstance(c, dict)
        ]
    }


async def _build_something(server: Server) -> dict[str, Any]:
    """Create observable state so a savegame has something to verify."""
    c = server.client
    towns = [t for t in ((await c.send_gamescript("get_towns", timeout=25.0)).get("result") or [])
             if isinstance(t, dict)]
    built = []
    for town in towns[:8]:
        res = (await c.send_gamescript(
            "scan_town_area", {"town_id": town["id"], "radius": 8}, timeout=30.0
        )).get("result")
        if not isinstance(res, dict):
            continue
        buildable = {(t["x"], t["y"]) for t in res.get("buildable", []) if "x" in t}
        roads = {(t["x"], t["y"]) for t in res.get("roads", []) if "x" in t}
        target = None
        for (bx, by) in sorted(buildable):
            for idx, (dx, dy) in enumerate(_DELTAS):
                if (bx + dx, by + dy) in roads:
                    target = {"x": bx, "y": by, "direction": idx}
                    break
            if target:
                break
        if not target:
            continue
        r = await c.send_gamescript(
            "build_road_stop", {"company_id": 0, **target}, timeout=25.0
        )
        if r.get("success"):
            built.append(target)
        if len(built) >= 2:
            break
    return {"stops_built": built}


async def test_savegame_as_evidence(game_port: int) -> dict[str, Any]:
    """Save a played world, inspect the file offline, then reload and re-score it."""
    out: dict[str, Any] = {}
    server = await _spawn("replay_src", {"construction.command_pause_level": "3"}, game_port)
    save_name = "verify_me"
    try:
        c = server.client
        await c.send_rcon("unpause")
        await asyncio.sleep(2.0)
        await c.send_gamescript("set_loan", {"company_id": 0, "amount": 200000}, timeout=15.0)
        out["build"] = await _build_something(server)
        await asyncio.sleep(3.0)

        out["score_at_save"] = await _company_score(server)
        out["date_at_save"] = (await _game_date(server)).get("date")

        rcon_out = await c.send_rcon(f"save {save_name}")
        out["rcon_save_output"] = [x.strip() for x in rcon_out if x.strip()]
        await asyncio.sleep(3.0)
    finally:
        await _teardown(server)

    # Locate the produced savegame.
    save_dir = SCRATCH / "replay_src" / "save"
    candidates = list(save_dir.rglob("*.sav")) if save_dir.exists() else []
    out["save_files"] = [str(p.relative_to(SCRATCH)) for p in candidates]
    if not candidates:
        out["error"] = f"no .sav produced under {save_dir}"
        return out
    save_path = candidates[0]
    out["save_bytes"] = save_path.stat().st_size
    out["save_sha256"] = hashlib.sha256(save_path.read_bytes()).hexdigest()[:32]

    # OFFLINE inspection: no server, no network.
    proc = subprocess.run(
        [OPENTTD_BINARY, "-q", str(save_path)],
        capture_output=True, text=True, timeout=90,
    )
    out["offline_q_inspection"] = {
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip()[:600],
        "stderr": proc.stderr.strip()[:300],
    }

    # RELOAD into a fresh server and re-read the score from the GS.
    verifier = await _spawn("replay_verify", {"construction.command_pause_level": "3"}, game_port + 20)
    try:
        dst = SCRATCH / "replay_verify" / "save"
        dst.mkdir(parents=True, exist_ok=True)
        (dst / save_path.name).write_bytes(save_path.read_bytes())

        load_out = await verifier.client.send_rcon(f"load {save_path.name}")
        out["rcon_load_output"] = [x.strip() for x in load_out if x.strip()]
        await asyncio.sleep(6.0)

        ping = await verifier.client.send_gamescript("ping", timeout=15.0)
        out["gs_alive_after_load"] = bool(ping.get("success"))
        out["score_after_reload"] = await _company_score(verifier)
        out["date_after_reload"] = (await _game_date(verifier)).get("date")
        stations = await verifier.client.send_gamescript(
            "get_stations", {"company_id": 0}, timeout=20.0
        )
        slist = stations.get("result")
        out["stations_after_reload"] = len(slist) if isinstance(slist, list) else None

        a = out.get("score_at_save", {}).get("companies") or []
        b = out.get("score_after_reload", {}).get("companies") or []
        out["score_reproduced"] = bool(a) and bool(b) and (
            a[0].get("company_value") == b[0].get("company_value")
        )
    finally:
        await _teardown(verifier)
    return out


async def test_seed_determinism(seed: int, game_port: int) -> dict[str, Any]:
    """Generate the same seed twice in separate processes and compare worlds."""
    out: dict[str, Any] = {"seed": seed}
    prints = []
    for i in range(2):
        server = await _spawn(
            f"seed_{seed}_{i}",
            {"game_creation.generation_seed": str(seed)},
            game_port + i * 10,
        )
        try:
            prints.append(await _world_fingerprint(server))
        finally:
            await _teardown(server)
    out["run_a"], out["run_b"] = prints
    out["identical"] = (
        prints[0]["towns_sha"] == prints[1]["towns_sha"]
        and prints[0]["industries_sha"] == prints[1]["industries_sha"]
    )

    # Control: a different seed must produce a different world.
    server = await _spawn(
        f"seed_{seed + 1}_ctl",
        {"game_creation.generation_seed": str(seed + 1)},
        game_port + 30,
    )
    try:
        other = await _world_fingerprint(server)
    finally:
        await _teardown(server)
    out["different_seed"] = other
    out["control_differs"] = other["towns_sha"] != prints[0]["towns_sha"]
    return out


async def main() -> None:
    SCRATCH.mkdir(exist_ok=True)
    results: dict[str, Any] = {}

    logger.info("TEST 1 -- savegame as verifiable evidence")
    try:
        results["savegame_evidence"] = await test_savegame_as_evidence(5000)
    except Exception as exc:
        logger.exception("savegame test failed")
        results["savegame_evidence"] = {"fatal_error": repr(exc)}

    logger.info("TEST 2 -- seed determinism across processes")
    try:
        results["seed_determinism"] = await test_seed_determinism(1001, 5050)
    except Exception as exc:
        logger.exception("seed test failed")
        results["seed_determinism"] = {"fatal_error": repr(exc)}

    (SCRATCH / "results_replay.json").write_text(json.dumps(results, indent=2, default=str))
    print("\n" + json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
