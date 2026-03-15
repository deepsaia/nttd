"""Structured event logger for nttd.

Writes JSONL to disk and optionally publishes scalar metrics to TensorBoard.
Every observation, action, GS call, error, and reconnect event is recorded.
"""
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class EventLogger:
    """Appends structured events to a JSONL file and optionally to TensorBoard."""

    def __init__(self, log_dir: str = "runs", use_tensorboard: bool = False) -> None:
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._step = 0

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._jsonl_path = self._log_dir / f"nttd_{timestamp}.jsonl"
        self._jsonl = open(self._jsonl_path, "a")  # noqa: SIM115

        self._tb_writer: Any = None
        if use_tensorboard:
            try:
                from tensorboardX import SummaryWriter  # type: ignore[import-untyped]
                self._tb_writer = SummaryWriter(log_dir=str(self._log_dir / f"tb_{timestamp}"))
                logger.info("TensorBoard writer started: %s", self._log_dir)
            except ImportError:
                logger.warning("tensorboardX not installed — skipping TensorBoard logging")

        logger.info("EventLogger writing to %s", self._jsonl_path)

    def _write(self, event_type: str, data: dict[str, Any]) -> None:
        record = {"t": time.time(), "type": event_type, **data}
        self._jsonl.write(json.dumps(record) + "\n")
        self._jsonl.flush()

    def log_observation(self, snapshot: Any) -> None:
        """Log a world state snapshot and publish company metrics to TensorBoard."""
        self._step += 1
        game = snapshot.game
        companies = snapshot.companies

        self._write("observation", {
            "step": self._step,
            "game_date": game.game_date,
            "mode": game.mode,
            "paused": game.paused,
            "company_count": len(companies),
            "town_count": len(snapshot.towns),
            "vehicle_count": len(snapshot.vehicles),
            "station_count": len(snapshot.stations),
        })

        if self._tb_writer:
            self._tb_writer.add_scalar("game/date", game.game_date, self._step)
            self._tb_writer.add_scalar("game/companies", len(companies), self._step)
            self._tb_writer.add_scalar("game/vehicles", len(snapshot.vehicles), self._step)
            self._tb_writer.add_scalar("game/stations", len(snapshot.stations), self._step)
            for c in companies:
                tag = f"company/{c.id}"
                self._tb_writer.add_scalar(f"{tag}/balance", c.money, self._step)
                self._tb_writer.add_scalar(f"{tag}/loan", c.loan, self._step)
                self._tb_writer.add_scalar(f"{tag}/value", getattr(c, "value", 0), self._step)
                self._tb_writer.add_scalar(f"{tag}/income", getattr(c, "income", 0), self._step)

    def log_action_submitted(self, envelope: Any) -> None:
        self._write("action_submitted", {
            "action_id": envelope.action_id,
            "company_id": envelope.company_id,
            "action_type": envelope.action_type,
            "mode": envelope.mode,
        })

    def log_action_result(self, result: Any) -> None:
        self._write("action_result", {
            "action_id": result.action_id,
            "status": result.status,
            "error": result.error or None,
        })
        if self._tb_writer:
            success = 1 if result.status == "success" else 0
            self._tb_writer.add_scalar("actions/success_rate", success, self._step)

    def log_gs_command(self, action: str, params: dict[str, Any] | None, result: dict[str, Any]) -> None:
        self._write("gs_command", {
            "action": action,
            "params": params,
            "success": result.get("success"),
            "error": result.get("error"),
        })

    def log_reconnect(self, attempt: int, success: bool) -> None:
        self._write("reconnect", {"attempt": attempt, "success": success})

    def log_error(self, context: str, error: str) -> None:
        self._write("error", {"context": context, "error": error})

    def close(self) -> None:
        self._jsonl.close()
        if self._tb_writer:
            self._tb_writer.close()
