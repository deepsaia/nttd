from enum import StrEnum

from pydantic import BaseModel


class RuntimeMode(StrEnum):
    HEARTBEAT = "heartbeat"
    ASYNC_REALTIME = "async_realtime"
    ASSISTED = "assisted"


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
