"""Application-wide dependencies.

The SessionManager is the primary singleton — it owns per-session runtimes
(AdminClient, WorldState, Orchestrator, etc.) instead of global singletons.
"""

from fastapi import HTTPException

from nttd.runtime.session_manager import SessionManager
from nttd.runtime.session_runtime import SessionRuntime

session_manager: SessionManager | None = None  # initialized in app.py lifespan


def get_runtime(session_id: str) -> SessionRuntime:
    """Get the runtime for a running session, or raise 404."""
    if session_manager is None:
        raise RuntimeError("SessionManager not initialized")
    runtime = session_manager.get_runtime(session_id)
    if runtime is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} is not running")
    return runtime
