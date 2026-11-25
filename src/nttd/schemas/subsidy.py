from typing import Literal

from pydantic import BaseModel, Field


class Subsidy(BaseModel):
    """An OpenTTD subsidy: a bonus payment for establishing a specific cargo route.

    The game reports an expiry in economy-days. They are GS-exclusive:
    the admin port does not expose them.
    """

    id: int = 0
    cargo_id: int | None = None
    cargo_label: str | None = None
    src_type: Literal["industry", "town"] | None = None
    src_id: int | None = None
    src_name: str | None = None
    dst_type: Literal["industry", "town"] | None = None
    dst_id: int | None = None
    dst_name: str | None = None
    is_awarded: bool | None = None
    remaining_days: int | None = Field(default=None, description="Economy-days until expiry, as reported by the game.")
