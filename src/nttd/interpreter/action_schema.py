"""Schema for agent-produced actions: the format agents output as decisions.

Agents are instructed to output actions in this format. The interpreter
parses them into ActionEnvelopes for submission to the nttd REST API.

Agent output format::

    [
        {"action_type": "build_road_stop", "parameters": {"tile": 12345, "is_truck_stop": true}},
        {"action_type": "buy_vehicle", "parameters": {"depot_tile": 67890, "engine_id": 5}},
        {"action_type": "add_order", "parameters": {"vehicle_id": 0, "destination": 12345}}
    ]

The interpreter adds action_id, company_id, and mode before submitting.

These examples are checked against the action manifest by a test, because an agent copies
the format it is shown rather than looking the action up. Both were wrong: this one
passed ``length`` to ``build_road_stop``, which has no such parameter, and gave
``add_order`` an ``order_index``, which belongs to ``insert_order``. ``add_order``
appends to the end, so there is no position to give.
"""

from typing import Any

from pydantic import BaseModel, Field


class AgentAction(BaseModel):
    """A single action as produced by an agent."""

    action_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
