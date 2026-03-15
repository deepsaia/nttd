from pydantic import BaseModel


class Subsidy(BaseModel):
    """An OpenTTD subsidy: a bonus payment for establishing a specific cargo route.

    Subsidies expire after a few years if not claimed. They are GS-exclusive —
    the admin port does not expose them.
    """

    id: int = 0
    cargo_id: int = 0
    cargo_label: str = ""
    src_type: str = ""   # "industry" or "town"
    src_id: int = 0
    src_name: str = ""
    dst_type: str = ""   # "industry" or "town"
    dst_id: int = 0
    dst_name: str = ""
    value: int = 0
    remaining_years: int = 0
