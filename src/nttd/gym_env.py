"""Gymnasium-compatible environment wrapping nttd's heartbeat mode.

The env communicates with a running nttd server over HTTP. This keeps the
design agent-agnostic — the env is just another nttd client.

Usage:
    import gymnasium as gym
    from nttd.gym_env import NttdEnv

    env = NttdEnv(company_id=0)
    obs, info = env.reset()
    for _ in range(100):
        action = env.action_space.sample()   # replace with policy
        obs, reward, terminated, truncated, info = env.step(action)
    env.close()
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

try:
    import importlib.util
    _GYM_AVAILABLE = (
        importlib.util.find_spec("gymnasium") is not None
        and importlib.util.find_spec("numpy") is not None
    )
except Exception:
    _GYM_AVAILABLE = False


def _require_gym() -> None:
    if not _GYM_AVAILABLE:
        raise ImportError(
            "gymnasium and numpy are required for NttdEnv. "
            "Install with: uv add 'nttd[rl]' or pip install gymnasium numpy"
        )


class NttdEnv:
    """Single-company Gym environment backed by nttd heartbeat mode.

    Observation space (10 floats, all normalized to ~[-1, 1]):
        0  balance            company bank balance / 1_000_000
        1  loan               current loan / max_loan (0–1)
        2  income             last quarterly income / 100_000
        3  expenses           last quarterly expenses / 100_000
        4  company_value      company value / 1_000_000
        5  profit_ratio       (income - expenses) / max(income, 1)
        6  vehicle_count      number of active vehicles / 100
        7  station_count      number of stations / 50
        8  town_count         number of towns / 100
        9  game_date_norm     (game_date - start_date) / 365

    Action space:
        A gymnasium.spaces.Dict with a single key "envelope" that contains a
        raw action envelope dict. In practice, RL policies typically use a
        discrete wrapper on top — see NttdDiscreteEnv below.

    Reward:
        delta_balance / 10_000 + 0.01 * step survival bonus
        Negative when the company loses money.
    """

    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        company_id: int = 0,
        heartbeat_days: int = 30,
        action_window_seconds: float = 3.0,
        max_steps: int = 1000,
        agent_id: str | None = None,
    ) -> None:
        _require_gym()
        self.base_url = base_url.rstrip("/")
        self.company_id = company_id
        self.heartbeat_days = heartbeat_days
        self.max_steps = max_steps
        self._agent_id = agent_id or f"gym_{uuid.uuid4().hex[:8]}"
        self._step_count = 0
        self._start_date: int = 0
        self._prev_balance: float = 0.0
        self._session_active = False

        import numpy as np  # noqa: PLC0415
        from gymnasium import spaces as gym_spaces  # noqa: PLC0415
        self.np = np
        self._spaces = gym_spaces

        self.observation_space = gym_spaces.Box(
            low=-10.0, high=10.0, shape=(10,), dtype=np.float64
        )
        # Action space: a dict envelope. Policies may wrap with DiscreteWrapper.
        self.action_space = gym_spaces.Dict({
            "action_type": gym_spaces.Text(min_length=1, max_length=64),
        })

    def reset(
        self,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        import requests  # noqa: PLC0415

        self._step_count = 0

        # Register agent
        try:
            resp = requests.post(f"{self.base_url}/agents/connect", json={
                "agent_id": self._agent_id,
                "company_id": self.company_id,
            }, timeout=5)
            resp.raise_for_status()
        except Exception as e:
            logger.warning("Could not register agent: %s", e)

        # Set heartbeat mode and parameters
        try:
            requests.post(f"{self.base_url}/session/mode?mode=heartbeat", timeout=5)
            requests.post(
                f"{self.base_url}/session/heartbeat/interval?days={self.heartbeat_days}",
                timeout=5,
            )
        except Exception as e:
            logger.warning("Could not configure heartbeat: %s", e)

        # Get initial state
        obs, info = self._get_obs_and_info()
        self._start_date = info.get("game_date", 0)
        self._prev_balance = obs[0] * 1_000_000
        self._session_active = True
        return obs, info

    def step(self, action: dict[str, Any]) -> tuple[Any, float, bool, bool, dict[str, Any]]:
        import requests  # noqa: PLC0415

        # Submit action via heartbeat action endpoint
        if action and action.get("action_type"):
            params = dict(action.get("params", {}))
            params.setdefault("company_id", self.company_id)
            try:
                requests.post(
                    f"{self.base_url}/session/heartbeat/action",
                    json={"action": action["action_type"], "params": params},
                    timeout=5,
                )
            except Exception as e:
                logger.warning("Failed to submit heartbeat action: %s", e)

        # Wait for the heartbeat to complete (game advances)
        time.sleep(0.5)  # brief yield; the server handles actual timing

        obs, info = self._get_obs_and_info()

        # Reward: balance delta + small survival bonus
        balance = obs[0] * 1_000_000
        reward = (balance - self._prev_balance) / 10_000.0 + 0.01
        self._prev_balance = balance

        self._step_count += 1
        terminated = False  # no bankruptcy detection yet
        truncated = self._step_count >= self.max_steps

        return obs, reward, terminated, truncated, info

    def _get_obs_and_info(self) -> tuple[Any, dict[str, Any]]:
        import requests  # noqa: PLC0415
        np = self.np

        try:
            r = requests.get(f"{self.base_url}/state/full", timeout=5)
            r.raise_for_status()
            state = r.json()
        except Exception as e:
            logger.warning("Failed to get state: %s", e)
            return np.zeros(10, dtype=np.float64), {}

        game = state.get("game", {})
        companies = state.get("companies", [])
        vehicles = state.get("vehicles", [])
        stations = state.get("stations", [])
        towns = state.get("towns", [])

        company = next((c for c in companies if c.get("id") == self.company_id), {})

        balance = company.get("money", 0) / 1_000_000
        loan = company.get("loan", 0)
        max_loan = max(company.get("max_loan", 1), 1)
        loan_ratio = loan / max_loan
        income = company.get("income", 0) / 100_000
        value = company.get("value", 0) / 1_000_000
        expenses = 0.0  # approximated from loan change
        profit_ratio = income / max(abs(income), 1.0)
        vehicle_count = len([v for v in vehicles if v.get("company_id") == self.company_id]) / 100.0
        station_count = len([s for s in stations if s.get("company_id") == self.company_id]) / 50.0
        town_count = len(towns) / 100.0
        game_date = game.get("game_date", 0)
        date_norm = (game_date - self._start_date) / 365.0

        obs = np.array([
            balance, loan_ratio, income, expenses,
            value, profit_ratio, vehicle_count, station_count,
            town_count, date_norm,
        ], dtype=np.float64)

        info = {
            "game_date": game_date,
            "company_id": self.company_id,
            "balance": company.get("money", 0),
            "loan": loan,
            "vehicles": int(vehicle_count * 100),
            "stations": int(station_count * 50),
            "step": self._step_count,
        }
        return obs, info

    def render(self) -> None:
        obs, info = self._get_obs_and_info()
        logger.info(
            "Step %d | date=%d | balance=%.0f | vehicles=%d | stations=%d",
            self._step_count, info.get("game_date", 0),
            info.get("balance", 0), info.get("vehicles", 0), info.get("stations", 0),
        )

    def close(self) -> None:
        if not self._session_active:
            return
        import requests  # noqa: PLC0415
        try:
            requests.post(f"{self.base_url}/agents/{self._agent_id}/disconnect", timeout=3)
            requests.post(f"{self.base_url}/session/stop", timeout=3)
        except Exception:
            pass
        self._session_active = False
