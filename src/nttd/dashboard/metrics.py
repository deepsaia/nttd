"""Dashboard metrics writer for nttd.

Writes TensorBoard-compatible events and a live JSON metrics file.
Start TensorBoard with: tensorboard --logdir runs/

Also exposes a /metrics endpoint in the FastAPI app for real-time polling.
"""
import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MetricsWriter:
    """Accumulates per-step metrics and writes to TensorBoard + a JSON sidecar."""

    def __init__(self, log_dir: str = "runs") -> None:
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._step = 0
        self._latest: dict[str, Any] = {}

        # JSON sidecar for live polling without needing TensorBoard
        self._metrics_path = self._log_dir / "latest_metrics.json"

        try:
            from tensorboardX import SummaryWriter  # type: ignore[import-untyped]
            self._writer: Any = SummaryWriter(log_dir=str(self._log_dir))
            logger.info("TensorBoard writer started at %s/", log_dir)
        except ImportError:
            self._writer = None
            logger.info("tensorboardX not installed — metrics saved to %s only", self._metrics_path)

    def record(self, snapshot: Any) -> None:
        """Record a snapshot's metrics."""
        self._step += 1
        game = snapshot.game
        ts = time.time()

        metrics: dict[str, Any] = {
            "step": self._step,
            "timestamp": ts,
            "game_date": game.game_date,
            "companies": {},
        }

        if self._writer:
            self._writer.add_scalar("game/date", game.game_date, self._step)
            self._writer.add_scalar("game/vehicle_count", len(snapshot.vehicles), self._step)
            self._writer.add_scalar("game/station_count", len(snapshot.stations), self._step)
            self._writer.add_scalar("game/town_count", len(snapshot.towns), self._step)

        for company in snapshot.companies:
            cid = company.id
            money = getattr(company, "money", 0)
            loan = getattr(company, "loan", 0)
            income = getattr(company, "income", 0)
            value = getattr(company, "value", 0)
            vehicles = len([v for v in snapshot.vehicles if v.company_id == cid])
            stations = len([s for s in snapshot.stations if s.company_id == cid])

            metrics["companies"][cid] = {
                "name": company.name,
                "money": money,
                "loan": loan,
                "income": income,
                "value": value,
                "vehicles": vehicles,
                "stations": stations,
            }

            if self._writer:
                tag = f"company_{cid}"
                self._writer.add_scalar(f"{tag}/balance", money, self._step)
                self._writer.add_scalar(f"{tag}/loan", loan, self._step)
                self._writer.add_scalar(f"{tag}/income", income, self._step)
                self._writer.add_scalar(f"{tag}/value", value, self._step)
                self._writer.add_scalar(f"{tag}/vehicles", vehicles, self._step)
                self._writer.add_scalar(f"{tag}/stations", stations, self._step)

        self._latest = metrics
        self._metrics_path.write_text(json.dumps(metrics, indent=2))

    def get_latest(self) -> dict[str, Any]:
        return self._latest

    def close(self) -> None:
        if self._writer:
            self._writer.close()
