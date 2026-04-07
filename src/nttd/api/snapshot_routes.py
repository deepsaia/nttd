"""API routes for managing snapshot classes (named observation configs)."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from nttd.api import dependencies as deps
from nttd.state.snapshot_class import ALL_SECTIONS, SnapshotClass

logger = logging.getLogger(__name__)
router = APIRouter(tags=["snapshot-classes"])


class RegisterSnapshotClassRequest(BaseModel):
    name: str
    sections: list[str]
    description: str = ""


@router.get("/sessions/{session_id}/snapshot-classes")
async def list_snapshot_classes(session_id: str) -> dict[str, Any]:
    """List available snapshot classes for a session."""
    runtime = _get_runtime(session_id)
    classes = runtime.snapshot_class_registry.list_classes()
    return {
        "classes": [
            {"name": c.name, "sections": sorted(c.sections), "description": c.description}
            for c in classes
        ],
        "available_sections": sorted(ALL_SECTIONS),
    }


@router.post("/sessions/{session_id}/snapshot-classes")
async def register_snapshot_class(
    session_id: str, request: RegisterSnapshotClassRequest,
) -> dict[str, Any]:
    """Register a custom snapshot class for a session."""
    runtime = _get_runtime(session_id)

    invalid = set(request.sections) - ALL_SECTIONS
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sections: {sorted(invalid)}. Valid: {sorted(ALL_SECTIONS)}",
        )

    cls = SnapshotClass(
        name=request.name,
        sections=frozenset(request.sections),
        description=request.description,
    )
    runtime.snapshot_class_registry.register(cls)
    logger.info("Registered snapshot class %r for session %s", request.name, session_id)

    return {"name": cls.name, "sections": sorted(cls.sections), "description": cls.description}


def _get_runtime(session_id: str) -> Any:
    mgr = deps.session_manager
    if mgr is None:
        raise HTTPException(status_code=503, detail="Session manager not ready")
    runtime = mgr.get_runtime(session_id)
    if runtime is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not running")
    return runtime
