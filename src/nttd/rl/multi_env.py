"""PettingZoo-style environment over several companies in one nttd session.

Two shapes of multi-agent play, and this file is only one of them:

**Independent runners.** N separate processes, each with its own participant token,
each holding one ``NttdEnv``. Nothing here is involved. That is the shape a real
multi-agent benchmark entry takes, and the server's step barrier already synchronises
the shared clock across them.

**One process, N policies.** Self-play and population training want a single loop that
holds every company at once, which is what PettingZoo's ``ParallelEnv`` describes and
what this class provides. It is a client of the same participant routes, so it holds no
privileged access over the independent case.

The N ``POST /step`` calls have to be in flight together. Each one blocks until the
barrier's window closes, and the window does not close until every registered stepper
has arrived, so issuing them one after another would deadlock on the first. They go out
on a thread pool for that reason, not for speed.

Deliberately no ``pettingzoo`` dependency. The API shape is what callers want, and
taking the package as a hard dependency for two base classes would push it onto every
nttd install.

Requires the ``rl`` extra:  uv add 'nttd[rl]'
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from nttd.rl.env import NttdEnv

logger = logging.getLogger(__name__)

AgentId = str


class NttdParallelEnv:
    """Every company in one stepped session, stepped together from one process."""

    metadata = {"name": "nttd_parallel_v0", "is_parallelizable": True}

    def __init__(
        self,
        session_id: str,
        tokens: dict[int, str],
        base_url: str = "http://localhost:8000",
        max_steps: int = 0,
    ) -> None:
        """
        Args:
            session_id: A running nttd session started with several agent companies.
            tokens: Participant token per company id, as ``participants.json`` holds
                them and ``nttd session attach`` prints them. The company is derived
                from the token server-side, so a wrong key here cannot widen what a
                policy may touch; it only mislabels your own bookkeeping.
            max_steps: Truncate after this many steps, 0 to leave it to the scenario's
                end conditions.
        """
        if not tokens:
            raise ValueError(
                "NttdParallelEnv needs at least one company token. Start the session "
                "with --agent-companies N and read logs/sessions/<id>/participants.json"
            )

        self.session_id = session_id
        self.max_steps = max_steps
        self.possible_agents: list[AgentId] = [
            self._agent_id(company_id) for company_id in sorted(tokens)
        ]
        self.agents: list[AgentId] = list(self.possible_agents)

        self._envs: dict[AgentId, NttdEnv] = {
            self._agent_id(company_id): NttdEnv(
                session_id=session_id,
                token=token,
                base_url=base_url,
                company_id=company_id,
                max_steps=max_steps,
            )
            for company_id, token in sorted(tokens.items())
        }
        self._pool = ThreadPoolExecutor(
            max_workers=len(self._envs), thread_name_prefix="nttd-step",
        )
        self._step_count = 0

    @staticmethod
    def _agent_id(company_id: int) -> AgentId:
        return f"company_{company_id}"

    def observation_space(self, agent: AgentId) -> Any:
        return self._envs[agent].observation_space

    def action_space(self, agent: AgentId) -> Any:
        return self._envs[agent].action_space

    def reset(
        self, seed: int | None = None, options: dict[str, Any] | None = None,
    ) -> tuple[dict[AgentId, Any], dict[AgentId, dict[str, Any]]]:
        """Register every company as a stepper and return the opening observations.

        Sequential rather than concurrent: ``/step/reset`` does not wait at the
        barrier, and registering one company at a time makes the barrier's expected set
        grow predictably.

        ``seed`` is ignored, as in ``NttdEnv``: the world's seed belongs to the
        scenario, and reseeding mid-run would break the reproducibility the benchmark
        rests on.
        """
        self.agents = list(self.possible_agents)
        self._step_count = 0

        observations: dict[AgentId, Any] = {}
        infos: dict[AgentId, dict[str, Any]] = {}
        for agent, env in self._envs.items():
            observations[agent], infos[agent] = env.reset(seed=seed, options=options)
        return observations, infos

    def step(
        self, actions: dict[AgentId, Any],
    ) -> tuple[
        dict[AgentId, Any],
        dict[AgentId, float],
        dict[AgentId, bool],
        dict[AgentId, bool],
        dict[AgentId, dict[str, Any]],
    ]:
        """Step every live agent through one shared window.

        An agent missing from ``actions`` still steps, with an empty batch. It has to:
        the barrier waits for every registered stepper, so silently skipping one would
        stall the window until the liveness timeout evicted it. Waiting while vehicles
        earn is a legitimate move anyway, and an empty batch is how you express it.
        """
        live = [agent for agent in self.agents if agent in self._envs]
        futures = {
            agent: self._pool.submit(self._envs[agent].step, actions.get(agent))
            for agent in live
        }

        observations: dict[AgentId, Any] = {}
        rewards: dict[AgentId, float] = {}
        terminations: dict[AgentId, bool] = {}
        truncations: dict[AgentId, bool] = {}
        infos: dict[AgentId, dict[str, Any]] = {}

        for agent, future in futures.items():
            observation, reward, terminated, truncated, info = future.result()
            observations[agent] = observation
            rewards[agent] = reward
            terminations[agent] = terminated
            truncations[agent] = truncated
            infos[agent] = info

        self._step_count += 1
        # One world, one set of end conditions: the run ends for everyone at once. A
        # company going bankrupt is an end condition of the session, not of one agent,
        # so per-agent termination cannot diverge here.
        self.agents = [
            agent for agent in live
            if not (terminations[agent] or truncations[agent])
        ]
        return observations, rewards, terminations, truncations, infos

    def close(self) -> None:
        """Release the thread pool and leave the session running.

        Deliberately does not stop the session: it owns the result record, and an env
        that tore it down on close would end the run whenever a training script
        crashed.
        """
        self._pool.shutdown(wait=False)
        for env in self._envs.values():
            env.close()

    def render(self) -> None:
        """Rendering is out of band: connect an OpenTTD client to the session's port."""
        first = next(iter(self._envs.values()), None)
        if first is not None:
            first.render()
