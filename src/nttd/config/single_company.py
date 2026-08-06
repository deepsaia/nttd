"""One contestant per scored run.

A scored result is one company's performance on one world. A session started with
several participant tokens is a different thing: co-contestants sharing a map, competing
for the same towns and industries, which changes the problem in ways nothing on a
leaderboard row records. Two such runs are not comparable with each other, and neither is
comparable with a solo run on the same world.

Multi-company sessions stay available and useful. Self-play and population training want
exactly that shape, and ``NttdParallelEnv`` exists to drive it. They are simply not
scoreable, and a contestant should learn that when the session starts rather than when a
board rejects the bundle.

Kept beside the profile rules rather than inline at the call site, because it is a
conformance rule of the same kind: computed from the run, never declared.
"""

from __future__ import annotations

# One contestant. Zero is allowed and means a session nobody plays through the
# participant routes, which is how a human entry recorded over CMD_LOGGING looks.
MAX_SCORED_COMPANIES = 1


def blocks_scoring(agent_companies: int) -> str | None:
    """Say why this many contestants cannot be scored, or None when it is fine.

    Returns a sentence rather than a bool so the caller has something to log and show,
    and so the reason travels with the refusal instead of being reconstructed.
    """
    if agent_companies <= MAX_SCORED_COMPANIES:
        return None
    return (
        f"{agent_companies} contestant companies share this session. A scored run is "
        f"one company on one world, so this session is not scored. Start it with "
        f"--agent-companies 1 to be scored, or keep the extra companies for self-play "
        f"and accept an unscored run."
    )
