"""Gymnasium-compatible environment over nttd's step barrier.

An ordinary nttd client. It holds no privileged access and takes no shortcut: every
action goes through the same participant route an LLM agent posts to, so the action
ceiling, the scored lock, and the audit trail apply to a policy exactly as they do to
anything else. That is deliberate -- an RL entry that could act through a faster,
looser path would not be comparable to the entries it sits beside on a board.

The previous version of this file targeted six endpoints that did not exist
(``/agents/connect``, ``/session/mode``, ``/session/heartbeat/action``,
``/state/full``, ``/session/stop``, ``/session/heartbeat/interval``), so the RL
surface had been dead for some time. It also advanced the world with
``time.sleep(0.5)  # brief yield; the server handles actual timing``, which is a
guess rather than a barrier: nothing guaranteed the actions had landed or the world
had moved before the next observation was read. ``POST /step`` now returns only once
the world has advanced and been re-observed, so the loop is synchronous by
construction.

Reward is computed here, not by the server. What to optimise is the contestant's
choice, and a reward baked into nttd would have every RL entry optimising the
platform's opinion instead of its own. The leaderboard score stays separate from it,
which is what lets two policies with different shaping still be compared.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import requests
from gymnasium import spaces

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 300.0
# A step advances the world and blocks until it has, so the wait is bounded by game
# time rather than by the request. 15 game-days is about 30s at the fixed economy
# rate; the generous ceiling covers a large batch of pathfinding actions flushed
# before the advance.
_STEP_TIMEOUT = 600.0

_OBSERVATION_SIZE = 10


class NttdEnv:
    """Single-company environment over a stepped nttd session.

    The session must already exist and be running. Creating one is not the env's job:
    a session is a run, with a scenario, a seed, and a result record, and an env that
    silently span one up would hide which task a policy was trained on.

    Observation (10 floats, normalised to roughly [-1, 1]):
        0  balance          company money / 1e6
        1  loan_ratio       loan / max_loan
        2  income           last quarterly income / 1e5
        3  expenses         last quarterly expenses / 1e5
        4  company_value    value / 1e6
        5  profit_ratio     (income - expenses) / max(|income|, 1)
        6  vehicle_count    own vehicles / 100
        7  station_count    own stations / 50
        8  town_count       towns / 100
        9  elapsed          game-days since reset / 365

    The full entitled game state is available in ``info["snapshot"]``. This
    ten-float vector is a convenience for a baseline policy, not a limit: nttd always
    returns everything and filtering is the contestant's job, so a serious entry
    should build its own encoder from the snapshot.
    """

    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        session_id: str,
        token: str,
        base_url: str = "http://localhost:8000",
        company_id: int = 0,
        max_steps: int = 0,
    ) -> None:
        """
        Args:
            session_id: A running nttd session.
            token: The participant token for the company being played. The company is
                derived from it server-side, so a mismatched ``company_id`` here
                cannot widen what the policy may touch.
            max_steps: Truncate after this many steps, 0 to leave it to the
                scenario's end conditions. Truncation is the env's own budget; the
                server terminates on its end conditions independently.
        """
        self.base_url = base_url.rstrip("/")
        self.session_id = session_id
        self.token = token
        self.company_id = company_id
        self.max_steps = max_steps

        self._step_count = 0
        self._start_date = 0
        self._previous_value = 0.0

        self.observation_space = spaces.Box(
            low=-10.0, high=10.0, shape=(_OBSERVATION_SIZE,), dtype=np.float64,
        )
        # A step carries a variable-length list of actions, not one action: the
        # barrier flushes a batch. A policy that lays a whole route in one step is
        # doing something the interface is meant to allow.
        self.action_space = spaces.Sequence(
            spaces.Dict({"action": spaces.Text(max_length=64)}),
        )

    # -- plumbing ---------------------------------------------------------

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-Participant-Token": self.token}

    def _url(self, suffix: str) -> str:
        return f"{self.base_url}/v1/participant/sessions/{self.session_id}/{suffix}"

    def _post(self, suffix: str, payload: Any, timeout: float) -> dict[str, Any]:
        response = requests.post(
            self._url(suffix), json=payload, headers=self._headers, timeout=timeout,
        )
        response.raise_for_status()
        return response.json()

    # -- gym API ----------------------------------------------------------

    def reset(
        self, seed: int | None = None, options: dict[str, Any] | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        """Enter stepped mode and return the opening observation.

        ``seed`` is accepted for signature compatibility and ignored: the world's
        seed belongs to the scenario, and letting an env reseed mid-run would break
        the reproducibility the whole benchmark rests on. To train across worlds, run
        one session per seed.
        """
        if seed is not None:
            logger.warning(
                "NttdEnv.reset(seed=%s) ignored: the world seed is fixed by the "
                "scenario. Start a session per seed to vary worlds.", seed,
            )

        result = self._post("step/reset", None, _DEFAULT_TIMEOUT)
        snapshot = result.get("snapshot") or {}
        self._step_count = 0
        self._start_date = (snapshot.get("game") or {}).get("game_date", 0)
        observation, info = self._encode(snapshot)
        self._previous_value = info["company_value"]
        return observation, info

    def step(
        self, action: list[dict[str, Any]] | dict[str, Any] | None,
    ) -> tuple[Any, float, bool, bool, dict[str, Any]]:
        """Flush actions, advance the world, and observe.

        Accepts a list of actions or a single one. Returns the Gym five-tuple.
        """
        actions = self._normalise(action)
        result = self._post("step", {"actions": actions}, _STEP_TIMEOUT)

        snapshot = result.get("snapshot") or {}
        observation, info = self._encode(snapshot)

        # Change in company value: the closest single number to "did that help",
        # and it moves on building as well as on earning, so an early-game policy
        # gets signal before any cargo is delivered. Replace it -- this is a
        # baseline, not a definition of good play.
        value = info["company_value"]
        reward = (value - self._previous_value) / 10_000.0
        self._previous_value = value

        self._step_count += 1
        terminated = bool(result.get("terminated", False))
        truncated = bool(self.max_steps and self._step_count >= self.max_steps)

        info.update({
            "step": result.get("step", self._step_count),
            "days_advanced": result.get("days_advanced", 0),
            "end_reason": result.get("end_reason", ""),
        })
        return observation, reward, terminated, truncated, info

    def close(self) -> None:
        """Leave the session running.

        Deliberately does not stop it: the session owns the result record, and an env
        that tore it down on close would end the run whenever a training script
        crashed. Stop it explicitly, or let the end conditions do it.
        """
        return

    def render(self) -> None:
        logger.info(
            "session=%s step=%d company=%d", self.session_id, self._step_count,
            self.company_id,
        )

    # -- encoding ---------------------------------------------------------

    @staticmethod
    def _normalise(
        action: list[dict[str, Any]] | dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        """Accept a batch, a single action, or nothing.

        A step with no actions is legitimate: waiting while vehicles earn is a real
        move, and a policy must be able to make it.
        """
        if action is None:
            return []
        if isinstance(action, dict):
            return [action] if action.get("action") else []
        return [entry for entry in action if entry and entry.get("action")]

    def _encode(self, snapshot: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        """Project the full snapshot into the baseline observation vector."""
        game = snapshot.get("game") or {}
        companies = snapshot.get("companies") or []
        vehicles = snapshot.get("vehicles") or []
        stations = snapshot.get("stations") or []
        towns = snapshot.get("towns") or []

        company = next(
            (c for c in companies if c.get("id") == self.company_id), {},
        )
        money = float(company.get("money", 0) or 0)
        loan = float(company.get("loan", 0) or 0)
        max_loan = max(float(company.get("max_loan", 0) or 0), 1.0)
        income = float(company.get("income", 0) or 0)
        expenses = float(company.get("expenses", 0) or 0)
        value = float(company.get("value", 0) or 0)
        game_date = int(game.get("game_date", 0) or 0)

        own_vehicles = sum(1 for v in vehicles if v.get("company_id") == self.company_id)
        own_stations = sum(1 for s in stations if s.get("company_id") == self.company_id)

        observation = np.array([
            money / 1_000_000.0,
            loan / max_loan,
            income / 100_000.0,
            expenses / 100_000.0,
            value / 1_000_000.0,
            (income - expenses) / max(abs(income), 1.0),
            own_vehicles / 100.0,
            own_stations / 50.0,
            len(towns) / 100.0,
            (game_date - self._start_date) / 365.0,
        ], dtype=np.float64)

        info = {
            "game_date": game_date,
            "company_id": self.company_id,
            "balance": money,
            "loan": loan,
            "company_value": value,
            "vehicles": own_vehicles,
            "stations": own_stations,
            # The complete entitled state. Filtering is the contestant's job, so a
            # serious policy should encode from this rather than the ten floats.
            "snapshot": snapshot,
        }
        return observation, info
