import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from nttd.api.action_routes import router as action_router
from nttd.api.agent_routes import router as agent_router
from nttd.api.control_routes import router as control_router
from nttd.api.dependencies import admin_client, bridge, orchestrator
from nttd.api.observation_routes import router as observation_router
from nttd.api.ws_routes import broadcast_snapshot
from nttd.api.ws_routes import router as ws_router

logger = logging.getLogger(__name__)

ADMIN_HOST = os.environ.get("NTTD_ADMIN_HOST", "127.0.0.1")
ADMIN_PORT = int(os.environ.get("NTTD_ADMIN_PORT", "3977"))
ADMIN_PASSWORD = os.environ.get("NTTD_ADMIN_PASSWORD", "nttd")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    admin_client.host = ADMIN_HOST
    admin_client.port = ADMIN_PORT

    orchestrator.add_observer(broadcast_snapshot)

    ok = await admin_client.connect(password=ADMIN_PASSWORD, name="nttd")
    if ok:
        if admin_client.welcome:
            bridge.apply_welcome(admin_client.welcome)
        await admin_client.subscribe_defaults()
        poll_task = asyncio.create_task(admin_client.poll_loop())
        logger.info("nttd connected to OpenTTD at %s:%d", ADMIN_HOST, ADMIN_PORT)
    else:
        poll_task = None
        logger.warning("nttd running without OpenTTD connection (offline mode)")

    yield

    if poll_task is not None:
        await admin_client.disconnect()
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass
    logger.info("nttd shut down")


app = FastAPI(
    title="nttd",
    description="Agent-agnostic API server for OpenTTD AI simulation",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(control_router)
app.include_router(agent_router)
app.include_router(observation_router)
app.include_router(action_router)
app.include_router(ws_router)


@app.get("/health")
def health() -> dict[str, str]:
    connected = admin_client.connected
    return {"status": "ok", "openttd": "connected" if connected else "disconnected"}
