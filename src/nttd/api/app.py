import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI

import nttd.api.dependencies as deps
from nttd.api.action_routes import router as action_router
from nttd.api.admin_routes import router as admin_router
from nttd.api.agent_routes import router as agent_router
from nttd.api.analysis_routes import router as analysis_router
from nttd.api.benchmark_routes import router as benchmark_router
from nttd.api.control_routes import router as control_router
from nttd.api.gameloop_routes import router as gameloop_router
from nttd.api.metrics_routes import router as metrics_router
from nttd.api.observation_routes import router as observation_router
from nttd.api.snapshot_routes import router as snapshot_router
from nttd.api.ws_routes import router as ws_router
from nttd.runtime.session_manager import SessionManager

logger = logging.getLogger(__name__)

ADMIN_PASSWORD = os.environ.get("NTTD_ADMIN_PASSWORD", "nttd")
OPENTTD_BINARY = os.environ.get(
    "NTTD_OPENTTD_BINARY",
    "/Applications/OpenTTD.app/Contents/MacOS/openttd",
)
BASE_CONFIG_DIR = Path(os.environ.get("NTTD_BASE_CONFIG", "ottd_config"))
SESSIONS_DIR = Path(os.environ.get("NTTD_SESSIONS_DIR", "logs/sessions"))
PORT_RANGE_START = int(os.environ.get("NTTD_PORT_RANGE_START", "4000"))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # Configure repository paths
    from nttd.db.repositories import session_repo
    session_repo.set_sessions_dir(SESSIONS_DIR)

    # Initialize session manager
    deps.session_manager = SessionManager(
        openttd_binary=OPENTTD_BINARY,
        base_config_dir=BASE_CONFIG_DIR,
        sessions_dir=SESSIONS_DIR,
        admin_password=ADMIN_PASSWORD,
        port_range_start=PORT_RANGE_START,
    )

    # Recover any sessions that were running before nttd restarted
    await deps.session_manager.recover_orphans()
    logger.info(
        "nttd started (binary=%s, base_config=%s, sessions_dir=%s, ports=%d+)",
        OPENTTD_BINARY, BASE_CONFIG_DIR, SESSIONS_DIR, PORT_RANGE_START,
    )

    yield

    # Shut down all running sessions (triggered by uvicorn on SIGINT/SIGTERM)
    logger.info("Shutting down nttd...")
    if deps.session_manager:
        await deps.session_manager.shutdown_all()
    logger.info("nttd shut down")


app = FastAPI(
    title="nttd",
    description="Agent-agnostic API server for OpenTTD AI simulation",
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(control_router)
app.include_router(admin_router)
app.include_router(agent_router)
app.include_router(observation_router)
app.include_router(action_router)
app.include_router(metrics_router)
app.include_router(ws_router)
app.include_router(benchmark_router)
app.include_router(gameloop_router)
app.include_router(snapshot_router)
app.include_router(analysis_router)


@app.get("/health")
def health() -> dict[str, Any]:
    mgr = deps.session_manager
    if mgr is None:
        return {"status": "starting"}
    running = mgr.list_running()
    return {
        "status": "ok",
        "active_sessions": len(running),
        "sessions": running,
    }
