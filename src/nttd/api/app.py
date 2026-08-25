import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import nttd.api.dependencies as deps
from nttd import resources
from nttd.api.action_routes import operator_router as action_operator_router
from nttd.api.action_routes import participant_router as action_participant_router
from nttd.api.actions_routes import router as actions_router
from nttd.api.admin_routes import router as admin_router
from nttd.api.agent_routes import router as agent_router
from nttd.api.analysis_routes import router as analysis_router
from nttd.api.benchmark_routes import router as benchmark_router
from nttd.api.control_routes import operator_router as control_operator_router
from nttd.api.control_routes import participant_router as control_participant_router
from nttd.api.control_routes import public_router as control_public_router
from nttd.api.observation_routes import router as observation_router
from nttd.api.snapshot_routes import router as snapshot_router
from nttd.api.tiers import TIER_DESCRIPTIONS, Tier
from nttd.api.ws_routes import router as ws_router
from nttd.runtime.session_manager import SessionManager
from nttd.store import session_paths
from nttd.version import version

logger = logging.getLogger(__name__)

ADMIN_PASSWORD = os.environ.get("NTTD_ADMIN_PASSWORD", "nttd")
OPENTTD_BINARY = os.environ.get(
    "NTTD_OPENTTD_BINARY",
    "/Applications/OpenTTD.app/Contents/MacOS/openttd",
)
# Resolved from the package rather than the working directory. The default was the
# relative string "ottd_config", so it found the GameScript only when the server was
# started from the repository root, and an installed nttd never found it at all.
BASE_CONFIG_DIR = Path(os.environ.get("NTTD_BASE_CONFIG") or resources.gamescript_dir())
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
    # Read from installed metadata, which derives from the release tag. It was written here
    # as "0.2.0" while pyproject said 0.1.0 and the newest release was 0.0.2: three numbers,
    # no two agreeing, and the one an agent reads from /openapi.json was the furthest off.
    version=version(),
    lifespan=lifespan,
    # Documenting the tiers here is the point of splitting them: an agent reading
    # /docs or the OpenAPI schema can see which surface it is meant to use.
    openapi_tags=[
        {"name": tier.tag, "description": TIER_DESCRIPTIONS[tier]}
        for tier in (Tier.PARTICIPANT, Tier.PUBLIC, Tier.OPERATOR)
    ],
)


@app.exception_handler(session_paths.InvalidSessionIdError)
async def _reject_invalid_session_id(
    request: Request, exc: session_paths.InvalidSessionIdError,
) -> JSONResponse:
    """Answer 400 rather than 500 when a session id could not name one session directory.

    Registered once, for the same reason the check itself lives in one module: 34 routes take
    a session id as a path parameter, and catching it per route is a thing to forget. Without
    this the rejection is an uncaught ValueError, which FastAPI reports as a server error with
    a traceback, blaming nttd for the caller's argument.
    """
    return JSONResponse(status_code=400, content={"detail": str(exc)})


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
app.include_router(analysis_router, prefix=Tier.PUBLIC.prefix, tags=[Tier.PUBLIC.tag])
# Public rather than participant: the manifest describes the build, not a session, so it
# answers before one exists. That is when an agent most needs it.
app.include_router(actions_router, prefix=Tier.PUBLIC.prefix, tags=[Tier.PUBLIC.tag])

# The untiered mounts that used to sit here are gone. Every router above was included a
# second time without a tier prefix, giving 73 duplicate paths and 85 operations marked
# deprecated in the schema.
#
# Not an auth bypass: the same router objects were mounted twice, so the handlers and their
# checks were identical. The harm was that the whole surface had two names, and the second one
# kept a stale client working well enough to hide that it was stale. That is how nttd-workbench
# drifted: its old client posted to /sessions/{id}/actions/submit, which still resolved, so a
# runner half worked instead of failing on its first request. A 404 on the first call is worth
# more than a run that half works.
#
# Nothing shipped depends on them. nttd-workbench and the MCP client build /v1/participant
# paths, the CLI prints tiered URLs, the monitor's sentry posts to /v1/operator, and the
# admin console that did use them was removed.

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
