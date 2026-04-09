#!/usr/bin/env python3
"""Generate SVG diagrams for nttd documentation.

Usage:
    python scripts/generate_diagrams.py

Generates:
    docs/images/architecture_overview.svg
    docs/images/gameloop_cycle.svg
    docs/images/transport_modes.svg
"""

from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "docs" / "images"


def _write_svg(filename: str, content: str) -> None:
    path = OUTPUT_DIR / filename
    path.write_text(content, encoding="utf-8")
    print(f"  Generated {path}")


def generate_architecture_overview() -> None:
    svg = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 700 520" font-family="system-ui, sans-serif">
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5"
            markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#555"/>
    </marker>
  </defs>

  <!-- Background -->
  <rect width="700" height="520" rx="8" fill="#f8f9fa"/>

  <!-- Title -->
  <text x="350" y="30" text-anchor="middle" font-size="16" font-weight="bold" fill="#1a1a2e">nttd Architecture</text>

  <!-- Agent Layer -->
  <rect x="50" y="50" width="600" height="70" rx="8" fill="#e8f4fd" stroke="#2196F3" stroke-width="1.5"/>
  <text x="350" y="75" text-anchor="middle" font-size="13" font-weight="bold" fill="#1565C0">Agent Layer (external)</text>
  <text x="150" y="100" text-anchor="middle" font-size="11" fill="#555">OpenAI</text>
  <text x="290" y="100" text-anchor="middle" font-size="11" fill="#555">LangChain</text>
  <text x="430" y="100" text-anchor="middle" font-size="11" fill="#555">Custom/RL</text>
  <text x="560" y="100" text-anchor="middle" font-size="11" fill="#555">MCP</text>

  <!-- Arrow -->
  <line x1="350" y1="120" x2="350" y2="150" stroke="#555" stroke-width="1.5" marker-end="url(#arrow)"/>
  <text x="380" y="140" font-size="10" fill="#888">HTTP/JSON</text>

  <!-- nttd API Server -->
  <rect x="50" y="155" width="600" height="180" rx="8" fill="#fff3e0" stroke="#FF9800" stroke-width="1.5"/>
  <text x="350" y="178" text-anchor="middle" font-size="13" font-weight="bold" fill="#E65100">nttd API Server</text>

  <!-- Sub-boxes -->
  <rect x="70" y="190" width="170" height="60" rx="6" fill="#fff" stroke="#ddd"/>
  <text x="155" y="215" text-anchor="middle" font-size="11" font-weight="bold" fill="#333">Gameloop Manager</text>
  <text x="155" y="235" text-anchor="middle" font-size="10" fill="#666">connections, cycles</text>

  <rect x="260" y="190" width="170" height="60" rx="6" fill="#fff" stroke="#ddd"/>
  <text x="345" y="215" text-anchor="middle" font-size="11" font-weight="bold" fill="#333">Observation Toolkit</text>
  <text x="345" y="235" text-anchor="middle" font-size="10" fill="#666">31 query tools</text>

  <rect x="450" y="190" width="180" height="60" rx="6" fill="#fff" stroke="#ddd"/>
  <text x="540" y="215" text-anchor="middle" font-size="11" font-weight="bold" fill="#333">Action Validator</text>
  <text x="540" y="235" text-anchor="middle" font-size="10" fill="#666">whitelist + execute</text>

  <!-- AdminClient -->
  <rect x="120" y="270" width="460" height="50" rx="6" fill="#f5f5f5" stroke="#999"/>
  <text x="350" y="295" text-anchor="middle" font-size="11" font-weight="bold" fill="#333">AdminClient (async TCP, correlation IDs, chunked messages)</text>
  <text x="350" y="310" text-anchor="middle" font-size="10" fill="#666">single connection per session, multiplexed</text>

  <!-- Arrow -->
  <line x1="350" y1="335" x2="350" y2="365" stroke="#555" stroke-width="1.5" marker-end="url(#arrow)"/>
  <text x="380" y="355" font-size="10" fill="#888">Admin Port</text>

  <!-- OpenTTD -->
  <rect x="50" y="370" width="600" height="130" rx="8" fill="#e8f5e9" stroke="#4CAF50" stroke-width="1.5"/>
  <text x="350" y="395" text-anchor="middle" font-size="13" font-weight="bold" fill="#2E7D32">OpenTTD Dedicated Server</text>

  <rect x="100" y="410" width="500" height="70" rx="6" fill="#fff" stroke="#81C784"/>
  <text x="350" y="435" text-anchor="middle" font-size="11" font-weight="bold" fill="#333">nttd GameScript (Squirrel)</text>
  <text x="350" y="455" text-anchor="middle" font-size="10" fill="#666">90+ commands: queries, builds, vehicles, orders, pathfinding</text>
  <text x="350" y="470" text-anchor="middle" font-size="10" fill="#666">GSTestMode dry-run validation, GSCompanyMode scoping</text>
</svg>"""
    _write_svg("architecture_overview.svg", svg)


def generate_gameloop_cycle() -> None:
    svg = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 400" font-family="system-ui, sans-serif">
  <defs>
    <marker id="arr" viewBox="0 0 10 10" refX="10" refY="5"
            markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#555"/>
    </marker>
  </defs>

  <rect width="600" height="400" rx="8" fill="#f8f9fa"/>
  <text x="300" y="30" text-anchor="middle" font-size="16" font-weight="bold" fill="#1a1a2e">Observe-Decide-Act Cycle</text>

  <!-- OBSERVE -->
  <rect x="40" y="60" width="140" height="80" rx="12" fill="#e3f2fd" stroke="#1976D2" stroke-width="2"/>
  <text x="110" y="95" text-anchor="middle" font-size="13" font-weight="bold" fill="#1565C0">OBSERVE</text>
  <text x="110" y="115" text-anchor="middle" font-size="10" fill="#555">Compact state</text>
  <text x="110" y="130" text-anchor="middle" font-size="10" fill="#555">snapshot (JSON)</text>

  <!-- DECIDE -->
  <rect x="230" y="60" width="140" height="80" rx="12" fill="#fff3e0" stroke="#F57C00" stroke-width="2"/>
  <text x="300" y="95" text-anchor="middle" font-size="13" font-weight="bold" fill="#E65100">DECIDE</text>
  <text x="300" y="115" text-anchor="middle" font-size="10" fill="#555">LLM + 31 tools</text>
  <text x="300" y="130" text-anchor="middle" font-size="10" fill="#555">(multi-turn)</text>

  <!-- ACT -->
  <rect x="420" y="60" width="140" height="80" rx="12" fill="#e8f5e9" stroke="#388E3C" stroke-width="2"/>
  <text x="490" y="95" text-anchor="middle" font-size="13" font-weight="bold" fill="#2E7D32">ACT</text>
  <text x="490" y="115" text-anchor="middle" font-size="10" fill="#555">Validate + execute</text>
  <text x="490" y="130" text-anchor="middle" font-size="10" fill="#555">via GameScript</text>

  <!-- Arrows between phases -->
  <line x1="180" y1="100" x2="228" y2="100" stroke="#555" stroke-width="1.5" marker-end="url(#arr)"/>
  <line x1="370" y1="100" x2="418" y2="100" stroke="#555" stroke-width="1.5" marker-end="url(#arr)"/>

  <!-- TRACK box below -->
  <rect x="230" y="180" width="140" height="60" rx="12" fill="#f3e5f5" stroke="#7B1FA2" stroke-width="2"/>
  <text x="300" y="210" text-anchor="middle" font-size="13" font-weight="bold" fill="#6A1B9A">TRACK</text>
  <text x="300" y="228" text-anchor="middle" font-size="10" fill="#555">Metrics + Parquet</text>

  <!-- Arrow from ACT to TRACK -->
  <path d="M 490 140 Q 490 210 372 210" fill="none" stroke="#555" stroke-width="1.5" marker-end="url(#arr)"/>

  <!-- Arrow from TRACK back to OBSERVE -->
  <path d="M 230 210 Q 110 210 110 142" fill="none" stroke="#555" stroke-width="1.5" marker-end="url(#arr)"/>
  <text x="150" y="200" font-size="10" fill="#888">next cycle</text>

  <!-- Multi-turn tool loop -->
  <rect x="200" y="270" width="200" height="110" rx="8" fill="#fffde7" stroke="#F9A825" stroke-width="1" stroke-dasharray="4"/>
  <text x="300" y="295" text-anchor="middle" font-size="11" font-weight="bold" fill="#F57F17">Multi-Turn Tool Loop</text>
  <text x="300" y="315" text-anchor="middle" font-size="10" fill="#555">LLM calls observation tools</text>
  <text x="300" y="332" text-anchor="middle" font-size="10" fill="#555">get_towns, find_airport_spots,</text>
  <text x="300" y="349" text-anchor="middle" font-size="10" fill="#555">get_engines, get_tile_info...</text>
  <text x="300" y="368" text-anchor="middle" font-size="10" fill="#888">until LLM outputs action JSON</text>

  <!-- Dashed line from DECIDE to tool loop -->
  <line x1="300" y1="140" x2="300" y2="268" stroke="#F9A825" stroke-width="1" stroke-dasharray="4"/>
</svg>"""
    _write_svg("gameloop_cycle.svg", svg)


def generate_transport_modes() -> None:
    svg = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 700 380" font-family="system-ui, sans-serif">
  <rect width="700" height="380" rx="8" fill="#f8f9fa"/>
  <text x="350" y="30" text-anchor="middle" font-size="16" font-weight="bold" fill="#1a1a2e">Transport Specialist Agents</text>

  <!-- Road -->
  <rect x="20" y="50" width="155" height="310" rx="8" fill="#e3f2fd" stroke="#1976D2" stroke-width="1.5"/>
  <text x="97" y="78" text-anchor="middle" font-size="14" font-weight="bold" fill="#1565C0">Road</text>
  <text x="97" y="100" text-anchor="middle" font-size="10" fill="#555">Connect towns</text>
  <text x="97" y="115" text-anchor="middle" font-size="10" fill="#555">via road vehicles</text>
  <line x1="35" y1="125" x2="160" y2="125" stroke="#90CAF9"/>
  <text x="35" y="145" font-size="9" fill="#333">1. find_bus_stop_spots</text>
  <text x="35" y="160" font-size="9" fill="#333">2. find_depot_spots</text>
  <text x="35" y="175" font-size="9" fill="#333">3. build_road_stop x2</text>
  <text x="35" y="190" font-size="9" fill="#333">4. build_road_depot</text>
  <text x="35" y="205" font-size="9" fill="#333">5. connect_road</text>
  <text x="35" y="220" font-size="9" fill="#333">6. buy_vehicle</text>
  <text x="35" y="235" font-size="9" fill="#333">7. add_order x2</text>
  <text x="35" y="250" font-size="9" fill="#333">8. start_vehicle</text>
  <line x1="35" y1="265" x2="160" y2="265" stroke="#90CAF9"/>
  <text x="97" y="285" text-anchor="middle" font-size="10" fill="#1976D2">Low capital</text>
  <text x="97" y="300" text-anchor="middle" font-size="10" fill="#1976D2">Forgiving terrain</text>
  <text x="97" y="315" text-anchor="middle" font-size="10" fill="#1976D2">~4-6s cycle time</text>

  <!-- Rail -->
  <rect x="190" y="50" width="155" height="310" rx="8" fill="#fff3e0" stroke="#F57C00" stroke-width="1.5"/>
  <text x="267" y="78" text-anchor="middle" font-size="14" font-weight="bold" fill="#E65100">Rail</text>
  <text x="267" y="100" text-anchor="middle" font-size="10" fill="#555">Connect industries</text>
  <text x="267" y="115" text-anchor="middle" font-size="10" fill="#555">via trains</text>
  <line x1="205" y1="125" x2="330" y2="125" stroke="#FFCC80"/>
  <text x="205" y="145" font-size="9" fill="#333">1. get_industries</text>
  <text x="205" y="160" font-size="9" fill="#333">2. find_flat_spots</text>
  <text x="205" y="175" font-size="9" fill="#333">3. build_rail_depot</text>
  <text x="205" y="190" font-size="9" fill="#333">4. build_rail_station x2</text>
  <text x="205" y="205" font-size="9" fill="#333">5. connect_rail</text>
  <text x="205" y="220" font-size="9" fill="#333">6. build_rail_signal xN</text>
  <text x="205" y="235" font-size="9" fill="#333">7. buy_vehicle + orders</text>
  <text x="205" y="250" font-size="9" fill="#333">8. start_vehicle</text>
  <line x1="205" y1="265" x2="330" y2="265" stroke="#FFCC80"/>
  <text x="267" y="285" text-anchor="middle" font-size="10" fill="#E65100">Complex build</text>
  <text x="267" y="300" text-anchor="middle" font-size="10" fill="#E65100">Needs flat land</text>
  <text x="267" y="315" text-anchor="middle" font-size="10" fill="#E65100">~6-11s cycle time</text>

  <!-- Air -->
  <rect x="360" y="50" width="155" height="310" rx="8" fill="#e8f5e9" stroke="#388E3C" stroke-width="1.5"/>
  <text x="437" y="78" text-anchor="middle" font-size="14" font-weight="bold" fill="#2E7D32">Air</text>
  <text x="437" y="100" text-anchor="middle" font-size="10" fill="#555">Airports in top</text>
  <text x="437" y="115" text-anchor="middle" font-size="10" fill="#555">towns + aircraft</text>
  <line x1="375" y1="125" x2="500" y2="125" stroke="#A5D6A7"/>
  <text x="375" y="145" font-size="9" fill="#333">1. get_towns (top 2)</text>
  <text x="375" y="160" font-size="9" fill="#333">2. find_airport_spots</text>
  <text x="375" y="175" font-size="9" fill="#333">3. build_airport x2</text>
  <text x="375" y="190" font-size="9" fill="#333">4. get_hangars</text>
  <text x="375" y="205" font-size="9" fill="#333">5. buy_vehicle</text>
  <text x="375" y="220" font-size="9" fill="#333">6. add_order x2</text>
  <text x="375" y="235" font-size="9" fill="#333">7. start_vehicle</text>
  <text x="375" y="250" font-size="9" fill="#333"></text>
  <line x1="375" y1="265" x2="500" y2="265" stroke="#A5D6A7"/>
  <text x="437" y="285" text-anchor="middle" font-size="10" fill="#2E7D32">High capital</text>
  <text x="437" y="300" text-anchor="middle" font-size="10" fill="#2E7D32">Fast setup</text>
  <text x="437" y="315" text-anchor="middle" font-size="10" fill="#2E7D32">~4-6s cycle time</text>

  <!-- Water -->
  <rect x="530" y="50" width="155" height="310" rx="8" fill="#e0f7fa" stroke="#00838F" stroke-width="1.5"/>
  <text x="607" y="78" text-anchor="middle" font-size="14" font-weight="bold" fill="#006064">Water</text>
  <text x="607" y="100" text-anchor="middle" font-size="10" fill="#555">Coastal towns</text>
  <text x="607" y="115" text-anchor="middle" font-size="10" fill="#555">via ships</text>
  <line x1="545" y1="125" x2="670" y2="125" stroke="#80DEEA"/>
  <text x="545" y="145" font-size="9" fill="#333">1. get_towns (coastal)</text>
  <text x="545" y="160" font-size="9" fill="#333">2. find_dock_spots</text>
  <text x="545" y="175" font-size="9" fill="#333">3. build_dock x2</text>
  <text x="545" y="190" font-size="9" fill="#333">4. find_water_depot</text>
  <text x="545" y="205" font-size="9" fill="#333">5. build_water_depot</text>
  <text x="545" y="220" font-size="9" fill="#333">6. buy_vehicle</text>
  <text x="545" y="235" font-size="9" fill="#333">7. add_order x2</text>
  <text x="545" y="250" font-size="9" fill="#333">8. start_vehicle</text>
  <line x1="545" y1="265" x2="670" y2="265" stroke="#80DEEA"/>
  <text x="607" y="285" text-anchor="middle" font-size="10" fill="#006064">Map dependent</text>
  <text x="607" y="300" text-anchor="middle" font-size="10" fill="#006064">Highest success%</text>
  <text x="607" y="315" text-anchor="middle" font-size="10" fill="#006064">~3-4s cycle time</text>
</svg>"""
    _write_svg("transport_modes.svg", svg)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Generating nttd diagrams...")
    generate_architecture_overview()
    generate_gameloop_cycle()
    generate_transport_modes()
    print("Done.")


if __name__ == "__main__":
    main()
