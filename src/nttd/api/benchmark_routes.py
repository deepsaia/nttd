"""Session-scoped benchmark routes: setup, reset, results, export."""

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import HTTPException
from fastapi.routing import APIRouter

import nttd.api.dependencies as deps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions/{session_id}/benchmark", tags=["benchmark"])

# Per-session benchmark state
_benchmark_starts: dict[str, tuple[int, float]] = {}  # session_id -> (start_date, start_time)


@router.post("/setup")
async def setup_benchmark(session_id: str, num_companies: int = 1) -> dict[str, Any]:
    """Create N AI companies via rcon."""
    runtime = deps.get_runtime(session_id)
    if not runtime.admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")

    await runtime.admin_client.send_rcon(f"setting max_no_competitors {num_companies}")
    await asyncio.sleep(0.2)

    for _ in range(num_companies):
        await runtime.admin_client.send_rcon("start_ai")
        await asyncio.sleep(0.5)

    result = await runtime.admin_client.send_gamescript("get_companies", timeout=10.0)
    companies = result.get("result", []) if result.get("success") else []
    company_ids = [c["id"] for c in companies if isinstance(c, dict) and "id" in c]

    return {"requested": num_companies, "company_ids": company_ids}


@router.post("/reset")
async def reset_benchmark(session_id: str, filename: str | None = None) -> dict[str, Any]:
    """Reset the benchmark: newgame or load a save, clear WorldState, record start."""
    runtime = deps.get_runtime(session_id)
    if not runtime.admin_client.connected:
        raise HTTPException(status_code=503, detail="Not connected to OpenTTD")

    if filename:
        response = await runtime.admin_client.send_rcon(f"load {filename}")
    else:
        response = await runtime.admin_client.send_rcon("newgame")

    # Clear all entity state
    runtime.world.companies.clear()
    runtime.world.towns.clear()
    runtime.world.industries.clear()
    runtime.world.stations.clear()
    runtime.world.vehicles.clear()

    start_date = runtime.world.game.game_date
    _benchmark_starts[session_id] = (start_date, time.time())

    return {"reset": True, "start_date": start_date, "response": response}


@router.get("/results")
async def get_benchmark_results(session_id: str) -> dict[str, Any]:
    """Return per-company performance metrics and elapsed time."""
    runtime = deps.get_runtime(session_id)
    start_date, start_time = _benchmark_starts.get(session_id, (0, 0.0))

    wall_elapsed = time.time() - start_time if start_time else 0.0
    game_days_elapsed = runtime.world.game.game_date - start_date

    all_results = runtime.action_tracker.get_recent(10000)
    actions_by_company: dict[int, list[Any]] = {}
    for result in all_results:
        envelope = runtime.action_tracker.get_envelope(result.action_id)
        cid = envelope.company_id if envelope else -1
        actions_by_company.setdefault(cid, []).append(result)

    companies_out = []
    for company in runtime.world.companies.values():
        company_actions = actions_by_company.get(company.id, [])
        total = len(company_actions)
        success = sum(1 for r in company_actions if r.status == "success")
        companies_out.append({
            "id": company.id,
            "name": company.name,
            "balance": company.money,
            "loan": company.loan,
            "income": company.income,
            "company_value": company.value,
            "vehicles": sum(1 for v in runtime.world.vehicles.values() if v.company_id == company.id),
            "stations": sum(1 for s in runtime.world.stations.values() if s.company_id == company.id),
            "actions_submitted": total,
            "success_rate": round(success / total, 3) if total else 0.0,
        })

    return {
        "companies": companies_out,
        "game_days_elapsed": game_days_elapsed,
        "wall_time_elapsed_s": round(wall_elapsed, 1),
        "start_date": start_date,
        "current_date": runtime.world.game.game_date,
    }


@router.post("/export")
async def export_benchmark_results(session_id: str, output_path: str = "benchmark.json") -> dict[str, Any]:
    """Write benchmark results as JSON to output_path."""
    results = await get_benchmark_results(session_id)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    logger.info("Benchmark results exported to %s", output_path)
    return {"exported": True, "path": output_path}
