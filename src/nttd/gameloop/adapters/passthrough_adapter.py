"""Passthrough adapter for scripted/rule-based agents that don't use an LLM."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from nttd.gameloop.adapters.base import BaseAdapter, ToolExecutor

logger = logging.getLogger(__name__)


class PassthroughAdapter(BaseAdapter):
    """Adapter that calls a user-provided function instead of an LLM.

    The function receives the observation dict and returns a list of action dicts.
    If no function is provided, returns an empty action list (observe-only mode).
    """

    def __init__(self, decide_fn: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None) -> None:
        self._decide_fn = decide_fn

    async def decide(
        self,
        observation: dict[str, Any],
        instructions: str,
        observation_tools: list[dict[str, Any]] | None = None,
        tool_executor: ToolExecutor | None = None,
    ) -> str:
        if self._decide_fn is None:
            return "[]"
        try:
            actions = self._decide_fn(observation)
            return json.dumps(actions)
        except Exception:
            logger.exception("Passthrough decide function failed")
            return "[]"
