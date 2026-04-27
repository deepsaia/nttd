"""Orders and routes report: vehicle order chains, route analysis."""

from __future__ import annotations

import json

import polars as pl

from nttd.analysis.loader import SessionData
from nttd.analysis.reports.registry import ReportResult, register, session_header


def _extract_orders_data(s: SessionData) -> dict:
    """Extract vehicle orders and routes from the latest snapshot."""
    if s.snapshots.is_empty():
        return {"session_id": s.session_id, "model": s.model, "has_data": False}

    last_row = s.snapshots.sort("game_date").row(-1, named=True)
    try:
        snap = json.loads(last_row["snapshot_json"])
    except (json.JSONDecodeError, TypeError, KeyError):
        return {"session_id": s.session_id, "model": s.model, "has_data": False}

    vehicles = snap.get("vehicles", [])
    routes = snap.get("routes", [])
    stations = {st["id"]: st.get("name", f"Station #{st['id']}") for st in snap.get("stations", [])}

    # Per-vehicle order summary
    vehicle_orders: list[dict] = []
    vehicles_without_orders = 0
    total_orders = 0
    for v in vehicles:
        orders = v.get("orders", [])
        total_orders += len(orders)
        if not orders:
            vehicles_without_orders += 1

        order_detail: list[dict] = []
        for o in orders:
            dest = o.get("destination", 0)
            order_detail.append({
                "index": o.get("index", 0),
                "destination": dest,
                "destination_name": stations.get(dest, f"tile {dest}"),
                "flags": o.get("flags", 0),
                "is_goto_station": o.get("is_goto_station", False),
                "is_goto_depot": o.get("is_goto_depot", False),
                "is_goto_waypoint": o.get("is_goto_waypoint", False),
            })

        vehicle_orders.append({
            "vehicle_id": v.get("id"),
            "vehicle_name": v.get("name", ""),
            "vehicle_type": v.get("type", "unknown"),
            "order_count": len(orders),
            "orders": order_detail,
        })

    # Order action stats from actions.parquet
    order_actions = {}
    if not s.actions.is_empty():
        order_prefixes = [
            "add_order", "insert_order", "remove_order", "set_order",
            "share_order", "copy_order", "move_order", "skip_to_order",
        ]
        mask = pl.lit(False)
        for prefix in order_prefixes:
            mask = mask | pl.col("action_type").str.starts_with(prefix)
        order_types = s.actions.filter(mask)
        if not order_types.is_empty():
            for group in order_types.partition_by("action_type"):
                atype = group["action_type"][0]
                ok = int((group["status"] == "success").sum())
                order_actions[atype] = {
                    "total": len(group),
                    "success": ok,
                    "failed": len(group) - ok,
                }

    # Route summary
    route_data: list[dict] = []
    has_year_passed = False
    for r in routes:
        station_names = [stations.get(sid, f"#{sid}") for sid in r.get("station_ids", [])]
        p_last = r.get("total_profit_last_year", 0)
        if p_last != 0:
            has_year_passed = True
        route_data.append({
            "route_id": r.get("route_id"),
            "vehicle_type": r.get("vehicle_type", ""),
            "vehicle_count": r.get("vehicle_count", 0),
            "station_ids": r.get("station_ids", []),
            "station_names": station_names,
            "profit_this_year": r.get("total_profit_this_year", 0),
            "profit_last_year": p_last,
        })
    # Also check vehicles for year-passed if routes had none
    if not has_year_passed:
        has_year_passed = any(v.get("profit_last_year", 0) != 0 for v in vehicles)

    return {
        "session_id": s.session_id,
        "model": s.model,
        "has_data": True,
        "has_year_passed": has_year_passed,
        "total_vehicles": len(vehicles),
        "total_orders": total_orders,
        "vehicles_without_orders": vehicles_without_orders,
        "vehicle_orders": vehicle_orders,
        "order_actions": order_actions,
        "routes": route_data,
    }


@register("orders")
def generate(sessions: list[SessionData]) -> ReportResult:
    """Produce orders and routes analysis."""
    all_data = [_extract_orders_data(s) for s in sessions]
    data = {"orders": all_data}
    md_lines: list[str] = ["# Orders & Routes Report\n"]

    for s, od in zip(sessions, all_data):
        md_lines.append(session_header(s))
        if not od["has_data"]:
            md_lines.append("- No snapshot data available\n")
            continue

        md_lines.append(f"- **Vehicles**: {od['total_vehicles']}")
        md_lines.append(f"- **Total orders assigned**: {od['total_orders']}")
        md_lines.append(f"- **Vehicles without orders**: {od['vehicles_without_orders']}")

        if od["order_actions"]:
            md_lines.append("\n### Order Actions")
            md_lines.append("| Action | Total | OK | Fail |")
            md_lines.append("|--------|------:|---:|-----:|")
            for atype, stats in sorted(od["order_actions"].items()):
                md_lines.append(f"| {atype} | {stats['total']} | {stats['success']} | {stats['failed']} |")

        if od["routes"]:
            md_lines.append("\n### Routes")
            if od["has_year_passed"]:
                md_lines.append("| Type | Vehicles | Stations | This Year | Last Year | Total |")
                md_lines.append("|------|--------:|---------:|---------:|---------:|------:|")
                for r in od["routes"]:
                    stops = " -> ".join(r["station_names"])
                    total = r["profit_this_year"] + r["profit_last_year"]
                    md_lines.append(
                        f"| {r['vehicle_type']} | {r['vehicle_count']} "
                        f"| {stops} | {r['profit_this_year']:,} "
                        f"| {r['profit_last_year']:,} | {total:,} |"
                    )
            else:
                md_lines.append("| Type | Vehicles | Stations | Profit |")
                md_lines.append("|------|--------:|---------:|-------:|")
                for r in od["routes"]:
                    stops = " -> ".join(r["station_names"])
                    md_lines.append(
                        f"| {r['vehicle_type']} | {r['vehicle_count']} "
                        f"| {stops} | {r['profit_this_year']:,} |"
                    )

        if od["vehicle_orders"]:
            md_lines.append("\n### Per-Vehicle Orders")
            for vo in od["vehicle_orders"]:
                if not vo["orders"]:
                    md_lines.append(f"- **{vo['vehicle_name']}** ({vo['vehicle_type']} #{vo['vehicle_id']}): no orders")
                    continue
                stops = " -> ".join(o["destination_name"] for o in vo["orders"])
                md_lines.append(f"- **{vo['vehicle_name']}** ({vo['vehicle_type']} #{vo['vehicle_id']}): {stops}")

        md_lines.append("")

    return ReportResult(
        name="orders",
        title="Orders & Routes Report",
        data=data,
        figures=[],
        markdown="\n".join(md_lines),
    )
