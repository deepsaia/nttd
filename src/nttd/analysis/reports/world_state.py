"""World state report: towns, industries, subsidies, and map overview."""

from __future__ import annotations

import json

from nttd.analysis.loader import SessionData
from nttd.analysis.reports.registry import ReportResult, register, session_header


def _extract_world_state(s: SessionData) -> dict:
    """Extract town, industry, and subsidy data from the latest snapshot."""
    if s.snapshots.is_empty():
        return {"session_id": s.session_id, "model": s.model, "has_data": False}

    last_row = s.snapshots.sort("game_date").row(-1, named=True)
    try:
        snap = json.loads(last_row["snapshot_json"])
    except (json.JSONDecodeError, TypeError, KeyError):
        return {"session_id": s.session_id, "model": s.model, "has_data": False}

    towns = snap.get("towns", [])
    industries = snap.get("industries", [])
    subsidies = snap.get("subsidies", [])
    stations = snap.get("stations", [])
    cargo_flows = snap.get("cargo_flows", [])

    total_population = sum(t.get("population", 0) for t in towns)
    cities = [t for t in towns if t.get("is_city")]

    return {
        "session_id": s.session_id,
        "model": s.model,
        "has_data": True,
        "num_towns": len(towns),
        "num_cities": len(cities),
        "total_population": total_population,
        "towns": [
            {
                "id": t.get("id"),
                "name": t.get("name", ""),
                "population": t.get("population", 0),
                "houses": t.get("houses", 0),
                "is_city": t.get("is_city", False),
                "growth_rate": t.get("growth_rate", 0),
            }
            for t in sorted(towns, key=lambda x: x.get("population", 0), reverse=True)
        ],
        "num_industries": len(industries),
        "industries": [
            {
                "id": i.get("id"),
                "name": i.get("name", ""),
                "type_name": i.get("type_name", ""),
                "is_raw": i.get("is_raw", False),
                "production": i.get("production", []),
            }
            for i in industries
        ],
        "num_subsidies": len(subsidies),
        "subsidies": subsidies,
        "num_stations": len(stations),
        "stations": [
            {
                "id": st.get("id"),
                "name": st.get("name", ""),
                "company_id": st.get("company_id", -1),
                "x": st.get("x", 0),
                "y": st.get("y", 0),
            }
            for st in stations
        ],
        "num_cargo_flows": len(cargo_flows),
        "total_cargo_amount": sum(cf.get("amount", 0) for cf in cargo_flows),
        "has_tiles": not s.tiles.is_empty(),
        "tile_count": len(s.tiles) if not s.tiles.is_empty() else 0,
    }


@register("world_state")
def generate(sessions: list[SessionData]) -> ReportResult:
    """Produce a world state overview: towns, industries, subsidies."""
    states = [_extract_world_state(s) for s in sessions]
    data = {"world": states}
    md_lines: list[str] = ["# World State Report\n"]

    for s, st in zip(sessions, states):
        md_lines.append(session_header(s))
        if not st["has_data"]:
            md_lines.append("- No snapshot data available\n")
            continue

        md_lines.append(f"- **Towns**: {st['num_towns']} ({st['num_cities']} cities)")
        md_lines.append(f"- **Total population**: {st['total_population']:,}")
        md_lines.append(f"- **Industries**: {st['num_industries']}")
        md_lines.append(f"- **Stations**: {st['num_stations']}")
        md_lines.append(f"- **Subsidies**: {st['num_subsidies']}")
        md_lines.append(f"- **Cargo flows**: {st['num_cargo_flows']} (total: {st['total_cargo_amount']:,})")
        if st["has_tiles"]:
            md_lines.append(f"- **Tiles recorded**: {st['tile_count']:,}")

        if st["towns"]:
            md_lines.append("\n### Towns")
            md_lines.append("| Name | Pop | Houses | City | Growth |")
            md_lines.append("|------|----:|-------:|:----:|-------:|")
            for t in st["towns"]:
                city = "yes" if t["is_city"] else ""
                md_lines.append(
                    f"| {t['name']} | {t['population']:,} | {t['houses']} "
                    f"| {city} | {t['growth_rate']} |"
                )

        if st["industries"]:
            md_lines.append("\n### Industries")
            md_lines.append("| Name | Type | Raw | Production |")
            md_lines.append("|------|------|:---:|------------|")
            for i in st["industries"]:
                raw = "yes" if i["is_raw"] else ""
                prod_parts = []
                for p in i.get("production", []):
                    label = p.get("cargo_label", f"cargo_{p.get('cargo_id', '?')}")
                    prod_parts.append(f"{label}: {p.get('last_month', 0)}")
                prod_str = ", ".join(prod_parts) if prod_parts else "-"
                md_lines.append(f"| {i['name']} | {i['type_name']} | {raw} | {prod_str} |")

        md_lines.append("")

    return ReportResult(
        name="world_state",
        title="World State Report",
        data=data,
        figures=[],
        markdown="\n".join(md_lines),
    )
