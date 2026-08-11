"""Whether a session is going wrong, judged from what it has actually done.

These rules exist because every failure worth catching is silent. A hung step looks like
a slow one. An agent that builds nothing looks like an agent being careful. A company with
22 stations and no vehicles looks busy and earns exactly nothing. None of it raises, and
none of it shows up as an error in a log.

Each rule was written against a real run, and the four T1 runs of 2026-08-11 tripped four
of them at once: rail submitted 2 actions in 28 steps, road built 22 stations and bought
no vehicle, and all four finished on the idle baseline rating of 30.

The rules only ever report. Acting on them is the caller's business, and the monitor only
stops a run when explicitly asked to.
"""

from __future__ import annotations

from typing import Any

# Ten steps is a third of a T1 run. Reaching it with nothing built means the run cannot
# score whatever it does with the rest of its time.
BARREN_STEPS = 10

# Infrastructure without vehicles is the most expensive way to score nothing, and it is
# the failure every one of the first four runs made. Later than BARREN_STEPS because
# building before buying is correct, and only wrong if it never ends.
IDLE_FLEET_STEPS = 14

# Fewer than one action every four steps. Deliberation is free in stepped play, so this is
# not about being slow: it is about a run that cannot act at all.
#
# Set from the runs it has to catch. rail-t1 managed 2 actions across 28 steps, which is
# 0.07, and it spent the other 26 steps hunting for stations it had built itself. A floor
# of 0.05 let that through, which made the rule useless for the one case it existed for.
# road-t1, which did act, ran at 0.77.
ACTIONS_PER_STEP_FLOOR = 0.25

# One action refused this many times is a loop, not bad luck.
SAME_REFUSAL_LIMIT = 5

# Seven times a normal step. A step is about a minute, so seven minutes of silence from a
# session that claims to be live is a session that is not coming back.
STALL_SECONDS = 420

_OK = "ok"
_WARN = "warn"
_BAD = "bad"

_LEVEL_RANK = {_OK: 0, _WARN: 1, _BAD: 2}


class Health:
    """The verdicts on one session."""

    def __init__(
        self,
        meta: dict[str, Any],
        steps: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        age_seconds: int | None = None,
    ) -> None:
        self._meta = meta
        self._steps = steps
        self._actions = actions
        self._age = age_seconds

    def verdicts(self) -> list[dict[str, str]]:
        """Everything wrong, worst first. Empty means nothing tripped."""
        found: list[dict[str, str]] = []
        for verdict in (
            self._stalled(),
            self._broke(),
            self._barren(),
            self._idle_fleet(),
            self._unconnected(),
            self._not_acting(),
            self._refusal_loop(),
        ):
            if verdict is not None:
                found.append(verdict)
        found.sort(key=lambda v: -_LEVEL_RANK[v["level"]])
        return found

    def level(self) -> str:
        """The worst level any rule reached, for the index row."""
        verdicts = self.verdicts()
        if not verdicts:
            return _OK
        return verdicts[0]["level"]

    def summary(self) -> str:
        """One phrase for the index: what is most wrong, or that nothing is."""
        verdicts = self.verdicts()
        if not verdicts:
            return "healthy"
        return verdicts[0]["rule"]

    # ------------------------------------------------------------------

    def _stalled(self) -> dict[str, str] | None:
        if not self._meta.get("live") or self._age is None:
            return None
        if self._age <= STALL_SECONDS:
            return None
        return {
            "level": _BAD,
            "rule": "stalled",
            "detail": f"live, but nothing written for {self._age}s",
            "why_it_matters": (
                "a step takes about a minute, so this is a step that is not coming back "
                "rather than a slow one"
            ),
        }

    def _broke(self) -> dict[str, str] | None:
        balance = self._meta.get("balance")
        if balance is None or balance >= 0:
            return None
        return {
            "level": _BAD,
            "rule": "overdrawn",
            "detail": f"balance {balance}",
            "why_it_matters": "nothing more can be built until this is back above zero",
        }

    def _barren(self) -> dict[str, str] | None:
        steps = len(self._steps)
        if steps < BARREN_STEPS or self._meta.get("stations"):
            return None
        return {
            "level": _BAD,
            "rule": "nothing built",
            "detail": f"{steps} steps, no stations",
            "why_it_matters": (
                "a company with no infrastructure cannot score above the idle baseline"
            ),
        }

    def _idle_fleet(self) -> dict[str, str] | None:
        """Built something, bought nothing. The most expensive way to score nothing."""
        steps = len(self._steps)
        stations = self._meta.get("stations") or 0
        vehicles = self._meta.get("vehicles") or 0
        if steps < IDLE_FLEET_STEPS or not stations or vehicles:
            return None
        return {
            "level": _BAD,
            "rule": "no vehicles",
            "detail": f"{stations} stations, no vehicles, after {steps} steps",
            "why_it_matters": (
                "stations do not earn, vehicles do; every station built so far has cost "
                "money and returned none of it"
            ),
        }

    def _unconnected(self) -> dict[str, str] | None:
        """Two or more stations and no vehicle to work them is a route never finished."""
        stations = self._meta.get("stations") or 0
        vehicles = self._meta.get("vehicles") or 0
        if stations < 2 or vehicles:
            return None
        if len(self._steps) < BARREN_STEPS:
            return None
        return {
            "level": _WARN,
            "rule": "stations not served",
            "detail": f"{stations} stations with nothing calling at them",
            "why_it_matters": (
                "an unfinished route has already cost what it cost, so finishing one "
                "beats starting another"
            ),
        }

    def _not_acting(self) -> dict[str, str] | None:
        steps = len(self._steps)
        if steps < BARREN_STEPS:
            return None
        attempted = self._meta.get("actions") or 0
        if attempted >= steps * ACTIONS_PER_STEP_FLOOR:
            return None
        return {
            "level": _BAD,
            "rule": "not acting",
            "detail": (
                f"{attempted} actions across {steps} steps, so about "
                f"{steps - attempted} of them changed nothing"
            ),
            "why_it_matters": (
                "a step that submits nothing sees the same world again with no more "
                "information, so the run is not progressing at all"
            ),
        }

    def _refusal_loop(self) -> dict[str, str] | None:
        counts: dict[str, int] = {}
        for action in self._actions:
            if action.get("status") == "success":
                continue
            name = action.get("action_type") or "?"
            counts[name] = counts.get(name, 0) + 1
        if not counts:
            return None
        worst, count = max(counts.items(), key=lambda item: item[1])
        if count < SAME_REFUSAL_LIMIT:
            return None
        return {
            "level": _WARN,
            "rule": "refusal loop",
            "detail": f"{worst} refused {count} times",
            "why_it_matters": (
                "the same refusal repeating means the feedback is not reaching the "
                "policy, or is not saying anything it can use"
            ),
        }
