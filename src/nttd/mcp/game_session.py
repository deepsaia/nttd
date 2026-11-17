"""One game session, played as one company, by any number of agents.

The session knows the game mode, counts steps, remembers that the game ended, keeps
the reward baseline, and holds the focus of each agent. It turns the commands of a
round into the shape each game route takes, pairs the results back to the agents by
id, and cuts each agent's snapshot to that agent's focus.
"""

from __future__ import annotations

import difflib
import logging
import random
from typing import Any

import httpx

from nttd.config import action_manifest
from nttd.mcp.focus import FocusRegistry
from nttd.mcp.moves import name_commands
from nttd.mcp.participant_client import ParticipantClient
from nttd.mcp.snapshot import explain_timeouts, reshape

AGENT_TAG_PARAM = "Name of the agent making the call."

GAME_ENDED_NOTE = "The game has ended. No more actions can be taken."

MISSING_RESULT_NOTE = "The game returned no result for this command."


logger = logging.getLogger(__name__)

STEPPED = "stepped"
# Manifest tiers an agent may send: game commands and read-only queries.
AGENT_TIERS = ("participant", "read_only")


class GameSession:
    """Plays one nttd session as one company."""

    def __init__(
        self,
        client: ParticipantClient,
        company_id: int = 0,
        days: int | None = None,
        reward_enabled: bool = False,
        seed: int | None = None,
        default_tag: str = "agent",
    ) -> None:
        self.client = client
        self.company_id = company_id
        self.days = days
        self.reward_enabled = reward_enabled
        self.rng = random.Random(seed)
        self.default_tag = default_tag
        self.mode = STEPPED
        self.started = False
        self.step_count = 0
        self.command_count = 0
        self.terminated = False
        self.end_reason: str | None = None
        self.last_net_worth: float | None = None
        self.last_snapshot: dict[str, Any] | None = None
        self.focus = FocusRegistry()

    def tag(self, agent_tag: str | None) -> str:
        """The caller's tag, or the default when the call named none."""
        return (
            agent_tag.strip()
            if isinstance(agent_tag, str) and agent_tag.strip()
            else self.default_tag
        )

    async def start(self) -> dict[str, Any]:
        """Read the mode, register as the stepper when the game steps, and take the
        reward baseline. Returns the opening snapshot."""
        status = await self.client.status()
        self.mode = status.get("mode", STEPPED)
        if self.mode == STEPPED:
            reply = await self.client.reset()
            snapshot = reshape(reply.get("snapshot", reply))
        else:
            snapshot = await self.snapshot()
        self.last_net_worth = self.net_worth(snapshot)
        self.last_snapshot = snapshot
        self.started = True
        logger.info(
            "Session %s plays company %d in %s mode",
            self.client.session_id,
            self.company_id,
            self.mode,
        )
        return snapshot

    async def ensure_started(self) -> None:
        """Start on the first call that needs the game, inside the server's event loop."""
        if not self.started:
            await self.start()

    def net_worth(self, snapshot: dict[str, Any]) -> float:
        """The company's money minus loan, from a snapshot."""
        for company in snapshot.get("companies", []):
            if isinstance(company, dict) and company.get("id") == self.company_id:
                return float(company.get("money", 0)) - float(company.get("loan", 0))
        return 0.0

    async def snapshot(self) -> dict[str, Any]:
        """The full game state, reshaped, not cut to any focus."""
        return reshape(await self.client.observe())

    async def observe(self, tag: str) -> dict[str, Any]:
        """The game state as one agent sees it."""
        return self.view(tag, await self.snapshot())

    def view(self, tag: str, result: dict[str, Any]) -> dict[str, Any]:
        """A result cut to the agent's focus. Agents without a focus see it whole."""
        return self.focus.apply(tag, result)

    async def query(self, name: str, parameters: dict[str, Any]) -> dict[str, Any]:
        return await self.client.query(name, parameters or {})

    async def validate(self, moves: list[dict[str, Any]]) -> dict[str, Any]:
        """The game's own check of the commands, without running them."""
        reply = await self.client.validate(
            [
                {"action_type": move["command"], "parameters": move["parameters"]}
                for move in moves
            ]
        )
        return {"dry_run": True, **reply}

    def lookup_action(self, name: str | None) -> dict[str, Any]:
        """Describe a command or query from the manifest. Only the entries an agent
        may send exist here; an operator action is unknown."""
        entries = {
            key: entry
            for key, entry in action_manifest.ACTIONS.items()
            if entry.get("tier") in AGENT_TIERS
        }
        if name is None:
            summary = {
                key: str(entry.get("description", "")).split(". ")[0]
                for key, entry in sorted(entries.items())
            }
            return {"count": len(summary), "commands": summary}
        entry = entries.get(name)
        if entry is None:
            return {
                "error": f"No such command or query: {name}",
                "did_you_mean": difflib.get_close_matches(
                    name, entries, n=5, cutoff=0.5
                ),
            }
        return {"name": name, **entry}

    async def set_focus(
        self, tag: str, args: dict[str, Any], snapshot: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Store the agent's focus and return its view, or the error."""
        if snapshot is None:
            snapshot = await self.snapshot()
        outcome = self.focus.set_focus(tag, snapshot, args)
        if "error" in outcome:
            return outcome
        return self.focus.apply(tag, snapshot)

    async def clear_focus(
        self, tag: str, snapshot: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Remove the agent's focus and return the whole map."""
        self.focus.clear(tag)
        return snapshot if snapshot is not None else await self.snapshot()

    def name(self, tag: str, moves: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Give the moves of one agent their ids, advancing the server counter."""
        named = name_commands(moves, tag, self.command_count)
        self.command_count += len(named)
        return named

    def step_entry(self, command: dict[str, Any]) -> dict[str, Any]:
        """The shape the step route takes."""
        return {
            "action": command["command"],
            "params": {**command["parameters"], "company_id": self.company_id},
            "action_id": command["action_id"],
            "metadata": {"participant_id": command["agent_tag"]},
        }

    def envelope(self, command: dict[str, Any]) -> dict[str, Any]:
        """The shape the submit route takes."""
        return {
            "action_id": command["action_id"],
            "company_id": self.company_id,
            "action_type": command["command"],
            "parameters": command["parameters"],
            "mode": "atomic",
            "metadata": {"participant_id": command["agent_tag"]},
        }

    async def play_round(
        self, actor_moves: dict[str, list[dict[str, Any]]]
    ) -> dict[str, dict[str, Any]]:
        """Run the commands of one round and return one raw result per actor.

        The actors run in a random order; each actor's block keeps the order it gave.
        In stepped mode the blocks form one step. Otherwise each block is one
        submitted batch and a snapshot is read after the last one. The snapshot after
        the round is kept in ``last_snapshot``. Results are not cut to any focus; the
        caller does that with ``view`` once every focus change of the round is in.
        """
        actors = list(actor_moves)
        self.rng.shuffle(actors)
        if self.terminated:
            return {tag: self.ended_result() for tag in actors}
        commands = {tag: self.name(tag, actor_moves[tag]) for tag in actors}
        try:
            if self.mode == STEPPED:
                reply = await self.client.step(
                    [self.step_entry(c) for tag in actors for c in commands[tag]],
                    self.days,
                )
                snapshot = reshape(reply.get("snapshot") or {})
                results = reply.get("action_results") or []
                self.step_count = reply.get("step", self.step_count + 1)
                if reply.get("terminated"):
                    self.terminated = True
                    self.end_reason = reply.get("end_reason")
                round_info = {
                    key: reply.get(key)
                    for key in ("step", "days_advanced", "terminated", "end_reason")
                }
            else:
                results = []
                for tag in actors:
                    if commands[tag]:
                        results.extend(
                            await self.client.submit_batch(
                                [self.envelope(c) for c in commands[tag]]
                            )
                        )
                snapshot = await self.snapshot()
                self.step_count += 1
                round_info = {"step": self.step_count}
        except httpx.HTTPStatusError as exc:
            if self.session_closed(exc):
                return {tag: self.ended_result() for tag in actors}
            raise
        self.last_snapshot = snapshot
        by_id = {
            result.get("action_id"): result
            for result in results
            if isinstance(result, dict)
        }
        reward = self.settle_reward(snapshot)
        outcome: dict[str, dict[str, Any]] = {}
        for tag in actors:
            own = explain_timeouts(
                [self.result_of(by_id, command) for command in commands[tag]]
            )
            result: dict[str, Any] = {
                "snapshot": snapshot,
                "action_results": own,
                **round_info,
            }
            if reward is not None:
                result["reward"] = reward
            outcome[tag] = result
        return outcome

    @staticmethod
    def result_of(
        by_id: dict[Any, dict[str, Any]], command: dict[str, Any]
    ) -> dict[str, Any]:
        """The game's result for one command, or a placeholder when it sent none."""
        result = by_id.get(command["action_id"])
        if result is None:
            return {
                "action_id": command["action_id"],
                "action_type": command["command"],
                "status": "unknown",
                "error": MISSING_RESULT_NOTE,
            }
        return result

    def settle_reward(self, snapshot: dict[str, Any]) -> float | None:
        """The change in money minus loan since the last reading, or None when off."""
        net = self.net_worth(snapshot)
        delta = net - (self.last_net_worth if self.last_net_worth is not None else net)
        self.last_net_worth = net
        return delta if self.reward_enabled else None

    def session_closed(self, exc: httpx.HTTPStatusError) -> bool:
        """A game that keeps its own clock ends by closing its session; every call
        then gets a 404. Record the end and say whether this error was that."""
        if self.mode == STEPPED or exc.response.status_code != 404:
            return False
        self.terminated = True
        self.end_reason = "session closed"
        return True

    def ended_result(self) -> dict[str, Any]:
        return {
            "terminated": True,
            "end_reason": self.end_reason,
            "note": GAME_ENDED_NOTE,
        }
