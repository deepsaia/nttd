"""Coded tool: pair_orphan_stations -- pairs orphan stations by Manhattan distance."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from neuro_san.interfaces.coded_tool import CodedTool

from rail_mas.observation_util import get_observation

logger = logging.getLogger(__name__)


class PairOrphanStations(CodedTool):
    """Pairs orphan stations by proximity. Returns (src_id, dst_id) pairs."""

    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        orphan_ids = set(args.get("orphan_station_ids", []))
        if not orphan_ids:
            return json.dumps({"pairs": []})

        obs = get_observation(sly_data)
        if not obs:
            return json.dumps({"pairs": []})

        stations: List[Dict[str, Any]] = obs.get("stations", [])
        orphans = [s for s in stations if s.get("id") in orphan_ids]

        if len(orphans) < 2:
            return json.dumps({"pairs": [], "note": f"Only {len(orphans)} orphan station(s), need at least 2"})

        pairs = self._greedy_closest_pairs(orphans)
        return json.dumps({"pairs": pairs})

    def _greedy_closest_pairs(
        self, orphans: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Greedy closest-pair matching by Manhattan distance."""
        pairs: List[Dict[str, Any]] = []
        used: set[int] = set()

        for i, s1 in enumerate(orphans):
            s1_id = s1["id"]
            if s1_id in used:
                continue
            best_dist = float("inf")
            best_j = -1
            for j, s2 in enumerate(orphans):
                s2_id = s2["id"]
                if i == j or s2_id in used:
                    continue
                dist = abs(s1.get("x", 0) - s2.get("x", 0)) + abs(s1.get("y", 0) - s2.get("y", 0))
                if dist < best_dist:
                    best_dist = dist
                    best_j = j
            if best_j >= 0:
                s2 = orphans[best_j]
                pairs.append({
                    "src_id": s1_id,
                    "src_x": s1.get("x", 0),
                    "src_y": s1.get("y", 0),
                    "dst_id": s2["id"],
                    "dst_x": s2.get("x", 0),
                    "dst_y": s2.get("y", 0),
                    "distance": int(best_dist),
                })
                used.add(s1_id)
                used.add(orphans[best_j]["id"])

        return pairs
