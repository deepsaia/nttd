"""Action Interpreter — the bridge between agent decisions and game execution.

Flow: agent output → parse → validate → execute → results

Usage::

    interpreter = ActionInterpreter(
        base_url="http://localhost:8000",
        session_id="ses_abc123",
        company_id=0,
    )

    # From structured output
    results = await interpreter.interpret([
        {"action_type": "build_road_stop", "parameters": {"tile": 12345}},
        {"action_type": "buy_vehicle", "parameters": {"depot_tile": 67890, "engine_id": 5}},
    ])

    # From raw LLM text
    results = await interpreter.interpret(llm_response_text)
"""

import logging
from typing import Any

from nttd.interpreter.action_schema import AgentAction
from nttd.interpreter.executor import ActionExecutor
from nttd.interpreter.parser import parse_action_list
from nttd.interpreter.validator import validate_actions

logger = logging.getLogger(__name__)


class ActionInterpreter:
    """Parses, validates, and executes agent action decisions."""

    def __init__(self, base_url: str, session_id: str, company_id: int) -> None:
        self.executor = ActionExecutor(base_url, session_id, company_id)

    async def interpret(
        self,
        agent_output: str | list[dict[str, Any]],
        skip_invalid: bool = True,
    ) -> list[dict[str, Any]]:
        """Parse agent output, validate, and execute actions.

        Args:
            agent_output: Raw agent output — structured list or text with embedded JSON.
            skip_invalid: If True, skip invalid actions and execute valid ones.
                          If False, abort all if any action is invalid.

        Returns:
            List of ActionResult dicts from execution.
        """
        actions = parse_action_list(agent_output)
        if not actions:
            logger.info("No actions parsed from agent output")
            return []

        logger.info("Parsed %d action(s) from agent output", len(actions))

        errors = validate_actions(actions)
        if errors:
            for idx, error in errors.items():
                logger.warning("Action %d invalid: %s", idx, error)
            if not skip_invalid:
                logger.error("Aborting: %d invalid action(s)", len(errors))
                return []
            actions = [a for i, a in enumerate(actions) if i not in errors]
            if not actions:
                logger.warning("All actions were invalid, nothing to execute")
                return []

        logger.info("Executing %d valid action(s)", len(actions))
        return await self.executor.execute(actions)

    async def parse_only(self, agent_output: str | list[dict[str, Any]]) -> list[AgentAction]:
        """Parse without executing — useful for debugging agent output."""
        return parse_action_list(agent_output)

    async def validate_only(
        self, agent_output: str | list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Parse and validate without executing — returns validation report."""
        actions = parse_action_list(agent_output)
        errors = validate_actions(actions)
        return {
            "total": len(actions),
            "valid": len(actions) - len(errors),
            "invalid": len(errors),
            "errors": {str(k): v for k, v in errors.items()},
            "actions": [a.model_dump() for a in actions],
        }
