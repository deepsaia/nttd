"""Generic A* pathfinding with pluggable cost functions.

Derived from the OpenTTD multiplayer/agent study, §14.4 (local research notes, not in the repo).
"""

import heapq
from dataclasses import dataclass, field
from typing import Any, Protocol

MAX_ITERATIONS: int = 50_000


@dataclass(slots=True, order=True)
class PathNode:
    f_cost: int
    g_cost: int = field(compare=False)
    x: int = field(compare=False)
    y: int = field(compare=False)
    direction: int = field(default=-1, compare=False)
    parent_key: int = field(default=-1, compare=False)
    action: str = field(default="move", compare=False)
    meta: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def state_key(self) -> int:
        if self.direction >= 0:
            return (self.x << 16) | (self.y << 2) | self.direction
        return (self.x << 16) | self.y


class CostFunction(Protocol):
    def heuristic(self, x1: int, y1: int, x2: int, y2: int) -> int: ...
    def neighbors(self, node: PathNode) -> list[PathNode]: ...


@dataclass
class PathResult:
    found: bool
    path: list[dict[str, Any]]
    total_cost: int
    tiles_explored: int
    iterations: int


def find_path(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    cost_fn: CostFunction,
    max_iterations: int = MAX_ITERATIONS,
) -> PathResult:
    """Run A* from start to end using the given cost function."""
    h = cost_fn.heuristic(start_x, start_y, end_x, end_y)
    start = PathNode(f_cost=h, g_cost=0, x=start_x, y=start_y, action="start")

    open_set: list[PathNode] = [start]
    came_from: dict[int, PathNode] = {}
    g_scores: dict[int, int] = {start.state_key: 0}

    iterations = 0

    while open_set and iterations < max_iterations:
        iterations += 1
        current = heapq.heappop(open_set)

        if current.x == end_x and current.y == end_y:
            path = _reconstruct(current, came_from)
            path[-1]["action"] = "end"
            return PathResult(
                found=True,
                path=path,
                total_cost=current.g_cost,
                tiles_explored=len(g_scores),
                iterations=iterations,
            )

        for neighbor in cost_fn.neighbors(current):
            tentative_g = current.g_cost + neighbor.g_cost
            key = neighbor.state_key

            if key in g_scores and tentative_g >= g_scores[key]:
                continue

            g_scores[key] = tentative_g
            h = cost_fn.heuristic(neighbor.x, neighbor.y, end_x, end_y)
            neighbor.f_cost = tentative_g + h
            neighbor.g_cost = tentative_g
            neighbor.parent_key = current.state_key
            came_from[key] = current
            heapq.heappush(open_set, neighbor)

    return PathResult(
        found=False,
        path=[],
        total_cost=0,
        tiles_explored=len(g_scores),
        iterations=iterations,
    )


def _reconstruct(
    end_node: PathNode, came_from: dict[int, PathNode],
) -> list[dict[str, Any]]:
    path: list[dict[str, Any]] = []
    current: PathNode | None = end_node

    while current is not None:
        entry: dict[str, Any] = {
            "x": current.x,
            "y": current.y,
            "action": current.action,
        }
        if current.meta:
            entry.update(current.meta)
        path.append(entry)
        parent = came_from.get(current.state_key)
        current = parent

    path.reverse()
    return path
