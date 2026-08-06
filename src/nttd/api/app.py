import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI

import nttd.api.dependencies as deps
from nttd.api.action_routes import operator_router as action_operator_router
from nttd.api.action_routes import participant_router as action_participant_router
from nttd.api.action_routes import router as action_router
from nttd.api.actions_routes import router as actions_router
from nttd.api.admin_routes import router as admin_router
from nttd.api.agent_routes import router as agent_router
from nttd.api.analysis_routes import router as analysis_router
from nttd.api.benchmark_routes import router as benchmark_router
from nttd.api.control_routes import operator_router as control_operator_router
from nttd.api.control_routes import participant_router as control_participant_router
from nttd.api.control_routes import public_router as control_public_router
from nttd.api.control_routes import router as control_router
from nttd.api.metrics_routes import router as metrics_router
from nttd.api.observation_routes import router as observation_router
from nttd.api.snapshot_routes import router as snapshot_router
from nttd.api.tiers import TIER_DESCRIPTIONS, Tier
from nttd.api.ws_routes import router as ws_router
from nttd.runtime.session_manager import SessionManager
from nttd.store import session_paths

logger = logging.getLogger(__name__)

ADMIN_PASSWORD = os.environ.get("NTTD_ADMIN_PASSWORD", "nttd")
OPENTTD_BINARY = os.environ.get(
    "NTTD_OPENTTD_BINARY",
    "/Applications/OpenTTD.app/Contents/MacOS/openttd",
)
BASE_CONFIG_DIR = Path(os.environ.get("NTTD_BASE_CONFIG", "ottd_config"))
SESSIONS_DIR = session_paths.sessions_dir()
PORT_RANGE_START = int(os.environ.get("NTTD_PORT_RANGE_START", "4000"))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

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
    # Documenting the tiers here is the point of splitting them: an agent reading
    # /docs or the OpenAPI schema can see which surface it is meant to use.
    openapi_tags=[
        {"name": tier.tag, "description": TIER_DESCRIPTIONS[tier]}
        for tier in (Tier.PARTICIPANT, Tier.PUBLIC, Tier.OPERATOR)
    ],
)

# --- Trust-tiered surface (preferred) -------------------------------------
#
# Routes are grouped by how dangerous they are and mounted under a tier prefix, so
# the boundary is structural and visible in /docs rather than a convention. See
# nttd.api.tiers -- these are namespacing and accident-avoidance, not an auth
# boundary: what actually protects a scored run is session state.

app.include_router(control_operator_router, prefix=Tier.OPERATOR.prefix, tags=[Tier.OPERATOR.tag])
app.include_router(admin_router, prefix=Tier.OPERATOR.prefix, tags=[Tier.OPERATOR.tag])
app.include_router(agent_router, prefix=Tier.OPERATOR.prefix, tags=[Tier.OPERATOR.tag])
app.include_router(snapshot_router, prefix=Tier.OPERATOR.prefix, tags=[Tier.OPERATOR.tag])
app.include_router(benchmark_router, prefix=Tier.OPERATOR.prefix, tags=[Tier.OPERATOR.tag])

app.include_router(
    action_operator_router, prefix=Tier.OPERATOR.prefix, tags=[Tier.OPERATOR.tag],
)

app.include_router(
    control_participant_router, prefix=Tier.PARTICIPANT.prefix, tags=[Tier.PARTICIPANT.tag],
)
app.include_router(
    action_participant_router, prefix=Tier.PARTICIPANT.prefix, tags=[Tier.PARTICIPANT.tag],
)
app.include_router(observation_router, prefix=Tier.PARTICIPANT.prefix, tags=[Tier.PARTICIPANT.tag])

app.include_router(control_public_router, prefix=Tier.PUBLIC.prefix, tags=[Tier.PUBLIC.tag])
app.include_router(metrics_router, prefix=Tier.PUBLIC.prefix, tags=[Tier.PUBLIC.tag])
app.include_router(analysis_router, prefix=Tier.PUBLIC.prefix, tags=[Tier.PUBLIC.tag])
# Public rather than participant: the manifest describes the build, not a session, so it
# answers before one exists. That is when an agent most needs it.
app.include_router(actions_router, prefix=Tier.PUBLIC.prefix, tags=[Tier.PUBLIC.tag])

# --- Legacy unprefixed paths ----------------------------------------------
#
# Kept so existing scenarios, the examples, the admin console, and the CLI keep
# working. Deprecated: new callers should use the tier prefixes above.

app.include_router(control_router, deprecated=True)
app.include_router(admin_router, deprecated=True)
app.include_router(agent_router, deprecated=True)
app.include_router(observation_router, deprecated=True)
app.include_router(action_router, deprecated=True)
app.include_router(metrics_router, deprecated=True)
app.include_router(benchmark_router, deprecated=True)
app.include_router(snapshot_router, deprecated=True)
app.include_router(analysis_router, deprecated=True)

# WebSockets are mounted once: the OpenAPI/deprecation machinery does not apply.
app.include_router(ws_router)


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
