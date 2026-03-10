from collections import OrderedDict

from nttd.schemas.action_envelope import ActionEnvelope
from nttd.schemas.action_result import ActionResult, ActionStatus


class ActionTracker:
    """Tracks submitted actions and their execution results."""

    def __init__(self, max_history: int = 1000) -> None:
        self._actions: OrderedDict[str, ActionEnvelope] = OrderedDict()
        self._results: OrderedDict[str, ActionResult] = OrderedDict()
        self._max_history = max_history

    def submit(self, envelope: ActionEnvelope) -> ActionResult:
        self._actions[envelope.action_id] = envelope
        result = ActionResult(action_id=envelope.action_id, status=ActionStatus.PENDING)
        self._results[envelope.action_id] = result
        self._trim()
        return result

    def update_status(self, action_id: str, status: ActionStatus, error: str = "") -> ActionResult | None:
        result = self._results.get(action_id)
        if result is None:
            return None
        result.status = status
        result.error = error
        return result

    def get_result(self, action_id: str) -> ActionResult | None:
        return self._results.get(action_id)

    def get_recent(self, limit: int = 50) -> list[ActionResult]:
        items = list(self._results.values())
        return items[-limit:]

    def _trim(self) -> None:
        while len(self._actions) > self._max_history:
            key, _ = self._actions.popitem(last=False)
            self._results.pop(key, None)
