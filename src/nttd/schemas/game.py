from enum import StrEnum

from pydantic import BaseModel


class RuntimeMode(StrEnum):
    HEARTBEAT = "heartbeat"
    ASYNC_REALTIME = "async_realtime"
    ASSISTED = "assisted"
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
