"""``batch_round``: the calls of many agents for one round, in one envelope.

An orchestrator that runs several agents cannot otherwise tell the server which calls
belong to the same moment. The envelope carries them together: reads run first, every
act forms one round, and each agent gets its own result. A single agent never needs it.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from nttd.mcp.game_session import GameSession
from nttd.mcp.moves import coerce_flag, read_moves
from nttd.mcp.tools.focus import FOCUS_KEYS
from nttd.mcp.tools.query import run_query

BATCH_ROUND = """Round envelope for an orchestrator that runs several agents.
Carries every agent's call for one round as {agent_tag, tool, args} entries,
where tool is one of observe, act, query, list_commands, focus. Reads run first,
all moves are sent together with the agents in a random order, and the game
advances exactly once. Replies with per-agent results keyed by agent_tag.
For delegated calls, owner_tag names the creator whose focus and participant
context apply; agent_tag remains the executor receiving the result. Correlated
callbacks, if used, must also target that executor.
A single agent never needs this tool.
"""


logger = logging.getLogger(__name__)


def error_of(exc: Exception) -> dict[str, Any]:
    """An error the agent reads, from a game refusal or any other failure."""
    if isinstance(exc, httpx.HTTPStatusError):
        return {"error": f"nttd returned {exc.response.status_code}", "detail": exc.response.text[:500]}
    reason = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
    return {"error": reason}


async def run_round(session: GameSession, entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Process one round: reads in order, then one play for every act.

    Returns {"results": {agent_tag: result}}. A failure of one entry is reported
    inside that agent's result, so one bad request never fails the round.
    """
    results: dict[str, Any] = {}
    actor_moves: dict[str, list[dict[str, Any]]] = {}
    observers: list[str] = []
    focus_requests: dict[str, dict[str, Any]] = {}
    focus_errors: dict[str, str] = {}
    owners: dict[str, str] = {}

    for entry in entries:
        tag = session.tag(entry.get("agent_tag"))
        owners[tag] = session.tag(entry.get("owner_tag", tag))
        tool = entry.get("tool", "")
        args = entry.get("args") or {}
        try:
            if tool == "observe":
                observers.append(tag)
            elif tool == "focus":
                if coerce_flag(args.get("clear")):
                    session.focus.clear(owners[tag])
                    observers.append(tag)
                else:
                    focus_requests[tag] = {key: args.get(key) for key in FOCUS_KEYS}
            elif tool == "act":
                moves, error = read_moves(args.get("moves"))
                if error:
                    results[tag] = {"error": error}
                elif coerce_flag(args.get("dry_run")):
                    results[tag] = await session.validate(moves)
                else:
                    actor_moves.setdefault(tag, []).extend(moves)
            elif tool == "query":
                results[tag] = await run_query(session, args.get("query", ""), args.get("parameters"))
            elif tool == "list_commands":
                results[tag] = session.lookup_action(args.get("name") or None)
            else:
                results[tag] = {"error": f"Unknown tool: {tool}"}
        except Exception as exc:
            results[tag] = error_of(exc)

    played: dict[str, dict[str, Any]] = {}
    snapshot: dict[str, Any] | None = None
    if actor_moves:
        try:
            played = await session.play_round(actor_moves, owners=owners)
            if not session.terminated:
                snapshot = session.last_snapshot
        except Exception as exc:
            logger.warning("nttd commands failed for %d actor(s): %s", len(actor_moves), error_of(exc)["error"])
            played = {tag: error_of(exc) for tag in actor_moves}

    # The round's view: the snapshot after the play, or one fresh fetch shared by every
    # observer and focus request. Focus changes land before any view is cut, so every
    # result of the round reflects the same set of focuses.
    readers = observers + list(focus_requests)
    if readers and snapshot is None:
        try:
            snapshot = await session.snapshot()
        except httpx.HTTPStatusError as exc:
            failure = session.ended_result() if session.session_closed(exc) else error_of(exc)
            for tag in readers:
                results[tag] = failure
            readers = []
        except Exception as exc:
            for tag in readers:
                results[tag] = error_of(exc)
            readers = []
    for tag, args in focus_requests.items():
        if tag in readers:
            outcome = session.focus.set_focus(owners[tag], snapshot or {}, args)
            if "error" in outcome:
                results[tag] = outcome
                focus_errors[tag] = outcome["error"]
    readers = [tag for tag in readers if tag not in focus_errors]
    for tag, result in played.items():
        results[tag] = session.view(owners[tag], result)
        if tag in focus_errors:
            # The action has already run. Preserve both its receipt and the
            # failed view change so the caller does not retry the action blindly.
            results[tag] = {**results[tag], "focus_error": focus_errors[tag]}
    # An agent that both acted and read in one round gets its act result, already
    # cut to the focus it asked for.
    for tag in readers:
        if tag not in played:
            results[tag] = session.view(owners[tag], snapshot or {})

    logger.info(
        "[round] entries=%d actors=%d observers=%d focus=%d step=%d terminated=%s",
        len(entries), len(actor_moves), len(observers), len(focus_requests), session.step_count, session.terminated,
    )
    return {"results": results}


def register(mcp: FastMCP, session: GameSession) -> None:
    """Register the round envelope."""

    @mcp.tool(description=BATCH_ROUND, meta={"terralingua/owner_tag": True})
    async def batch_round(entries: list[dict[str, Any]]) -> str:
        await session.ensure_started()
        return json.dumps(await run_round(session, entries))
