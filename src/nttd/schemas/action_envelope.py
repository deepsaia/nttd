from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ActionMode(StrEnum):
    ATOMIC = "atomic"
    COMPOUND = "compound"
    STRATEGIC = "strategic"


class ActionEnvelope(BaseModel):
    action_id: str
    company_id: int
    mode: ActionMode = ActionMode.ATOMIC
    action_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
