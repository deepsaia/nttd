import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from nttd.api.action_routes import router as action_router
from nttd.api.admin_routes import router as admin_router
from nttd.api.agent_routes import router as agent_router
from nttd.api.benchmark_routes import router as benchmark_router
from nttd.api.control_routes import router as control_router
from nttd.api.dependencies import action_tracker, admin_client, bridge, event_logger, orchestrator
from nttd.api.metrics_routes import router as metrics_router
from nttd.api.observation_routes import _metrics
from nttd.api.observation_routes import router as observation_router
from nttd.api.ws_routes import broadcast_snapshot
from nttd.api.ws_routes import router as ws_router
from nttd.db.engine import close_engine, init_engine
from nttd.db.migrations import apply_migrations

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("NTTD_DB_PATH", "nttd.db")
ADMIN_HOST = os.environ.get("NTTD_ADMIN_HOST", "127.0.0.1")
ADMIN_PORT = int(os.environ.get("NTTD_ADMIN_PORT", "3977"))
ADMIN_PASSWORD = os.environ.get("NTTD_ADMIN_PASSWORD", "nttd")
USE_TENSORBOARD = os.environ.get("NTTD_TENSORBOARD", "").lower() in ("1", "true", "yes")


async def _post_connect() -> None:
    """Called after every (re)connect to resubscribe and sync initial state."""
    if admin_client.welcome:
        bridge.apply_welcome(admin_client.welcome)
    await admin_client.subscribe_defaults()
    logger.info("nttd subscriptions registered")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    # Initialize database
    await init_engine(DB_PATH)
    await apply_migrations()

    # Wire event logger into orchestrator and action routes
    if USE_TENSORBOARD:
        from nttd.logging.event_logger import EventLogger  # noqa: PLC0415
        tb_logger = EventLogger(use_tensorboard=True)
        orchestrator.event_logger = tb_logger
    else:
        orchestrator.event_logger = event_logger

    orchestrator.action_tracker = action_tracker
    orchestrator.add_observer(broadcast_snapshot)
    orchestrator.add_observer(_metrics.record)

    admin_client.host = ADMIN_HOST
    admin_client.port = ADMIN_PORT

    # Register post-connect callback for reconnects
    admin_client.on_reconnect(_post_connect)

    ok = await admin_client.connect(password=ADMIN_PASSWORD, name="nttd")
    if ok:
        await _post_connect()
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

    await close_engine()
    event_logger.close()
    logger.info("nttd shut down")


app = FastAPI(
    title="nttd",
    description="Agent-agnostic API server for OpenTTD AI simulation",
    version="0.1.0",
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


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "openttd": "connected" if admin_client.connected else "disconnected",
    }
