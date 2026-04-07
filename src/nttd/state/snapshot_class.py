"""Named snapshot classes for agent observations.

A SnapshotClass defines which data sections an agent receives as its observation.
Built-in presets (minimal, compact, standard, full) are registered by default.
Users can register custom classes via the API.
"""

from dataclasses import dataclass, field

ALL_SECTIONS: frozenset[str] = frozenset({
    "company",
    "vehicles",
    "vehicles_detail",
    "vehicles_summary",
    "stations",
    "stations_detail",
    "stations_count",
    "towns",
    "top_towns",
    "industries",
    "routes",
    "subsidies",
    "game",
})


@dataclass(frozen=True)
class SnapshotClass:
    name: str
    sections: frozenset[str]
    description: str = ""


_BUILTIN_PRESETS: list[SnapshotClass] = [
    SnapshotClass(
        name="minimal",
        sections=frozenset({"company"}),
        description="Date + company balance/loan only",
    ),
    SnapshotClass(
        name="compact",
        sections=frozenset({"company", "vehicles_summary", "stations_count", "top_towns"}),
        description="Lightweight summary for fast cycles",
    ),
    SnapshotClass(
        name="agent",
        sections=frozenset({
            "company", "vehicles_detail", "stations_detail", "top_towns", "industries",
        }),
        description="Rich observation for agents: vehicles with orders, stations with cargo, industries",
    ),
    SnapshotClass(
        name="standard",
        sections=frozenset({"company", "vehicles", "stations", "towns", "industries"}),
        description="Full entity lists for the agent's company",
    ),
    SnapshotClass(
        name="full",
        sections=ALL_SECTIONS,
        description="Complete StateSnapshot as JSON",
    ),
]


@dataclass
class SnapshotClassRegistry:
    """Registry of named snapshot classes, shared per session."""

    _classes: dict[str, SnapshotClass] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for preset in _BUILTIN_PRESETS:
            self._classes[preset.name] = preset

    def register(self, cls: SnapshotClass) -> None:
        self._classes[cls.name] = cls

    def get(self, name: str) -> SnapshotClass:
        if name not in self._classes:
            raise KeyError(f"Unknown snapshot class: {name!r}. Available: {list(self._classes)}")
        return self._classes[name]

    def list_classes(self) -> list[SnapshotClass]:
        return list(self._classes.values())
