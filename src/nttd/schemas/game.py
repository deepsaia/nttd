from enum import StrEnum

from pydantic import BaseModel


class RuntimeMode(StrEnum):
    HEARTBEAT = "heartbeat"
    ASYNC_REALTIME = "async_realtime"
    # Client-driven stepping, for RL and ES. No loop runs on the server: the game
    # stays paused until the contestant asks for a step, which flushes its actions
    # and advances a fixed number of game-days. Distinct from HEARTBEAT, where the
    # server owns the loop and waits a wall-clock window for actions to arrive --
    # a deadline that truncates a slow policy and idles for a fast one, when the
    # whole point of stepping is that deliberation is unbounded.
    STEPPED = "stepped"


class GameState(BaseModel):
    game_date: int = 0
    tick: int = 0
    paused: bool = False
    speed: int = 1
    mode: RuntimeMode = RuntimeMode.HEARTBEAT
    map_width: int = 0
    map_height: int = 0
    landscape: str = ""
    snapshot_id: str = ""
    # How long the run is, and how much of it is left.
    #
    # A contestant cannot plan without these. Whether to buy a vehicle depends on whether
    # there is time for it to pay for itself, and a run that hides its own horizon forces
    # that decision to be made blind: an aircraft bought with sixty days to go is cash
    # converted into a depreciating asset. This is a fact about the task, not privileged
    # information, so it is on the public status beside the date.
    #
    # Zero when the run is not bounded by days at all, which is a different thing from
    # having none left.
    game_days_total: int = 0
    game_days_remaining: int = 0
