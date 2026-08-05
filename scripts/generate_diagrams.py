#!/usr/bin/env python3
"""Generate the architecture diagrams in docs/images/.

    uv run python scripts/generate_diagrams.py

The SVG source lives here rather than as committed artwork so a change to the
architecture is a readable diff rather than a wall of regenerated path data.

Each diagram carries a ``<style>`` block with a ``prefers-color-scheme: dark``
override. They are embedded in a README, which GitHub renders in whichever theme the
reader chose; a diagram with a hardcoded light background is unreadable for half the
audience. Light is the default, so the fallback is the safe one.
"""

from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "docs" / "images"

# One palette across every diagram, so a colour means the same thing in each: a
# contestant is always violet, nttd always blue, OpenTTD always green, a refusal
# always red, and recorded data always amber. Mid-tone values, chosen to hold
# contrast on white and on dark.
_STYLE = """  <style>
    .bg    { fill: #ffffff; }
    .title { fill: #14161f; font-weight: 700; }
    .label { fill: #14161f; }
    .muted { fill: #5b6472; }
    .edge  { stroke: #8b95a6; fill: none; }
    .box   { fill: #ffffff; stroke: #8b95a6; }
    .actor { fill: #f0ecf8; stroke: #6b5b95; }
    .actor-t { fill: #4a3f6b; font-weight: 600; }
    .server { fill: #e8f1f8; stroke: #2f6f9f; }
    .server-t { fill: #1d4f74; font-weight: 600; }
    .game  { fill: #e9f4ec; stroke: #3f7d58; }
    .game-t { fill: #2b5940; font-weight: 600; }
    .guard { fill: #fbeceb; stroke: #b0413e; }
    .guard-t { fill: #8a2f2c; font-weight: 600; }
    .data  { fill: #fdf5e6; stroke: #a8792c; }
    .data-t { fill: #7a5720; font-weight: 600; }
    @media (prefers-color-scheme: dark) {
      .bg    { fill: #14161f; }
      .title { fill: #f2f4f8; }
      .label { fill: #e4e8ef; }
      .muted { fill: #9aa4b4; }
      .edge  { stroke: #7d879a; }
      .box   { fill: #1c1f2b; stroke: #7d879a; }
      .actor { fill: #2a2440; stroke: #a894d6; }
      .actor-t { fill: #c9bcf0; }
      .server { fill: #162c3d; stroke: #5aa3d4; }
      .server-t { fill: #a3d0ee; }
      .game  { fill: #17301f; stroke: #6fb98a; }
      .game-t { fill: #a5dcb8; }
      .guard { fill: #351d1c; stroke: #dc7a77; }
      .guard-t { fill: #f0aaa8; }
      .data  { fill: #332715; stroke: #d4a94f; }
      .data-t { fill: #e8c579; }
    }
  </style>
"""

_DEFS = """  <defs>
    <marker id="a" viewBox="0 0 10 10" refX="9" refY="5"
            markerWidth="7" markerHeight="7" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#8b95a6"/>
    </marker>
  </defs>
"""


# Average advance of ui-sans-serif at 12px, measured against the rendered output.
# Approximate on purpose: it exists to keep a label inside its box, not to typeset.
_CHAR_WIDTH = 6.25


def text_width(text: str, font_size: int = 12) -> float:
    """Estimate the rendered width of a label.

    Used to derive a diagram's width from its longest line. Hand-tuned widths went
    stale the moment the content changed: a label overflowing its viewBox is invisible
    in the SVG source and only shows up when someone renders it.
    """
    return len(text) * _CHAR_WIDTH * (font_size / 12)


def _svg(width: int, height: int, body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}"'
        f' width="{width}" height="{height}"'
        ' font-family="ui-sans-serif, system-ui, sans-serif" font-size="12">\n'
        f"{_STYLE}{_DEFS}"
        f'  <rect class="bg" width="{width}" height="{height}" rx="10"/>\n'
        f"{body}</svg>\n"
    )


def _write(filename: str, content: str) -> None:
    (OUTPUT_DIR / filename).write_text(content, encoding="utf-8")
    print(f"  wrote docs/images/{filename}")


def architecture() -> None:
    """The whole system: who plays, through what, against what, recording what."""
    body = """
  <text class="title" x="440" y="28" text-anchor="middle" font-size="15">nttd architecture</text>
  <text class="muted" x="440" y="46" text-anchor="middle">the contestant owns the loop; nttd owns the world and the record</text>

  <rect class="actor" x="24" y="70" width="196" height="152" rx="8"/>
  <text class="actor-t" x="122" y="91" text-anchor="middle">Contestant (own process)</text>
  <rect class="box" x="40" y="101" width="164" height="22" rx="4"/>
  <text class="label" x="122" y="116" text-anchor="middle">LLM agent</text>
  <rect class="box" x="40" y="128" width="164" height="22" rx="4"/>
  <text class="label" x="122" y="143" text-anchor="middle">Multi-agent system</text>
  <rect class="box" x="40" y="155" width="164" height="22" rx="4"/>
  <text class="label" x="122" y="170" text-anchor="middle">RL policy</text>
  <rect class="box" x="40" y="182" width="164" height="22" rx="4"/>
  <text class="label" x="122" y="197" text-anchor="middle">ES population / human</text>
  <text class="muted" x="122" y="240" text-anchor="middle">observe, decide, act</text>

  <line class="edge" x1="222" y1="146" x2="268" y2="146" marker-end="url(#a)"/>
  <rect class="server" x="270" y="70" width="152" height="152" rx="8"/>
  <text class="server-t" x="346" y="91" text-anchor="middle">Play surfaces</text>
  <rect class="box" x="284" y="101" width="124" height="22" rx="4"/>
  <text class="label" x="346" y="116" text-anchor="middle">HTTP (REST)</text>
  <rect class="box" x="284" y="128" width="124" height="22" rx="4"/>
  <text class="label" x="346" y="143" text-anchor="middle">MCP</text>
  <rect class="box" x="284" y="155" width="124" height="22" rx="4"/>
  <text class="label" x="346" y="170" text-anchor="middle">Gym (stepped)</text>
  <text class="muted" x="346" y="197" text-anchor="middle">one token per company</text>

  <line class="edge" x1="424" y1="146" x2="466" y2="146" marker-end="url(#a)"/>
  <rect class="guard" x="468" y="70" width="152" height="152" rx="8"/>
  <text class="guard-t" x="544" y="91" text-anchor="middle">Admission</text>
  <rect class="box" x="482" y="101" width="124" height="22" rx="4"/>
  <text class="label" x="544" y="116" text-anchor="middle">operator tier?</text>
  <rect class="box" x="482" y="128" width="124" height="22" rx="4"/>
  <text class="label" x="544" y="143" text-anchor="middle">in the vocabulary?</text>
  <rect class="box" x="482" y="155" width="124" height="22" rx="4"/>
  <text class="label" x="544" y="170" text-anchor="middle">within budget?</text>
  <text class="muted" x="544" y="197" text-anchor="middle">one gate, every path</text>

  <line class="edge" x1="622" y1="146" x2="664" y2="146" marker-end="url(#a)"/>
  <rect class="server" x="666" y="70" width="190" height="152" rx="8"/>
  <text class="server-t" x="761" y="91" text-anchor="middle">Session runtime</text>
  <rect class="box" x="680" y="101" width="162" height="22" rx="4"/>
  <text class="label" x="761" y="116" text-anchor="middle">scored lock</text>
  <rect class="box" x="680" y="128" width="162" height="22" rx="4"/>
  <text class="label" x="761" y="143" text-anchor="middle">orchestrator, step barrier</text>
  <rect class="box" x="680" y="155" width="162" height="22" rx="4"/>
  <text class="label" x="761" y="170" text-anchor="middle">recorder</text>
  <text class="muted" x="761" y="197" text-anchor="middle">one per run</text>

  <line class="edge" x1="761" y1="224" x2="761" y2="262" marker-end="url(#a)"/>
  <text class="muted" x="761" y="248" text-anchor="middle">admin port, GameScript</text>
  <rect class="game" x="620" y="264" width="236" height="70" rx="8"/>
  <text class="game-t" x="738" y="286" text-anchor="middle">OpenTTD 15.3 (dedicated)</text>
  <text class="muted" x="738" y="305" text-anchor="middle">seeded world, pinned by -G</text>
  <text class="muted" x="738" y="322" text-anchor="middle">economy: 1 wall-min = 1 month</text>

  <line class="edge" x1="700" y1="186" x2="466" y2="292" marker-end="url(#a)"/>
  <rect class="data" x="24" y="264" width="436" height="70" rx="8"/>
  <text class="data-t" x="242" y="286" text-anchor="middle">Record (Parquet, per session)</text>
  <text class="muted" x="242" y="305" text-anchor="middle">actions . snapshots . events . tiles . result</text>
  <text class="muted" x="242" y="322" text-anchor="middle">result.parquet is what a leaderboard ingests</text>
"""
    _write("architecture.svg", _svg(880, 354, body))


def trust_tiers() -> None:
    """What each tier is for, and where the real boundary sits."""
    body = """
  <text class="title" x="414" y="28" text-anchor="middle" font-size="15">Trust tiers, and the boundary that actually holds</text>
  <text class="muted" x="414" y="46" text-anchor="middle">a contestant self-hosts, so it holds every credential: tiers organise, the scored lock protects</text>

  <rect class="guard" x="24" y="70" width="250" height="136" rx="8"/>
  <text class="guard-t" x="149" y="92" text-anchor="middle">/v1/operator</text>
  <text class="muted" x="149" y="111" text-anchor="middle">scenario authoring, debugging</text>
  <text class="label" x="40" y="134">deity powers, rcon, save/load</text>
  <text class="label" x="40" y="152">gs/execute, mode, step size</text>
  <text class="label" x="40" y="170">9 superhuman actions</text>
  <text class="muted" x="40" y="192">refused for a scored session</text>

  <rect class="actor" x="286" y="70" width="250" height="136" rx="8"/>
  <text class="actor-t" x="411" y="92" text-anchor="middle">/v1/participant</text>
  <text class="muted" x="411" y="111" text-anchor="middle">gameplay, scoped by token</text>
  <text class="label" x="302" y="134">actions/submit, step, report</text>
  <text class="label" x="302" y="152">state/full, gs/query (read-only)</text>
  <text class="label" x="302" y="170">76 human-parity actions</text>
  <text class="muted" x="302" y="192">company comes from the token</text>

  <rect class="server" x="548" y="70" width="250" height="136" rx="8"/>
  <text class="server-t" x="673" y="92" text-anchor="middle">/v1/public</text>
  <text class="muted" x="673" y="111" text-anchor="middle">read-only, no credential</text>
  <text class="label" x="564" y="134">session status</text>
  <text class="label" x="564" y="152">metrics, leaderboard</text>
  <text class="label" x="564" y="170">analysis</text>

  <rect class="box" x="24" y="230" width="774" height="98" rx="8"/>
  <text class="title" x="44" y="254">The tiers are namespacing, not authentication.</text>
  <text class="label" x="44" y="277">A contestant runs nttd themselves, so no credential can be withheld from them. What protects a result</text>
  <text class="label" x="44" y="295">is SESSION STATE: a scenario with scored = true refuses every game-mutating operator operation for</text>
  <text class="label" x="44" y="313">the whole run, for every caller, and records each attempt in the action log.</text>
"""
    _write("trust_tiers.svg", _svg(822, 348, body))


def scoreable_worlds() -> None:
    """The 5x5 matrix a scored run may be played on, and what is pinned around it.

    Built from the live profile rather than hardcoded, so narrowing
    config/benchmark/profile.conf and regenerating shows the smaller board.
    """
    from nttd.config.benchmark_profile import ALLOWED_RANGES, LOCKED_SETTINGS

    sizes = [str(v) for v in ALLOWED_RANGES["size"]]
    terrains = [str(v) for v in ALLOWED_RANGES["terrain_type"]]

    cell_w, cell_h = 104, 34
    left, top = 150, 96
    rows: list[str] = []

    pinned = ", ".join(f"{k} = {v}" for k, v in sorted(LOCKED_SETTINGS.items()))
    half = len(pinned) // 2
    split = pinned.find(", ", half)
    locked_lines = [pinned[:split], pinned[split + 2:]] if split > 0 else [pinned]
    seed_lines = [
        "Any seed is admissible, so the 25 maps are families rather than fixed boards.",
        "task_id is a digest over scenario id, version, seed and settings, so runs on "
        "one world group by themselves.",
    ]
    # Derived, not chosen: the locked list grows whenever a setting is pinned, and a
    # fixed width would silently push it outside the viewBox.
    widest = max(text_width(line) for line in locked_lines + seed_lines)
    width = max(left + cell_w * len(sizes) + 40, int(44 + widest + 44))

    rows.append(
        f'  <text class="title" x="{width // 2}" y="30" text-anchor="middle" '
        f'font-size="15">What a scored run may be played on</text>'
    )
    rows.append(
        f'  <text class="muted" x="{width // 2}" y="48" text-anchor="middle">'
        f'{len(sizes)} sizes x {len(terrains)} terrain types = '
        f'{len(sizes) * len(terrains)} maps, each with any seed</text>'
    )

    for col, size in enumerate(sizes):
        x = left + col * cell_w + cell_w // 2
        rows.append(
            f'  <text class="label" x="{x}" y="{top - 10}" text-anchor="middle" '
            f'font-weight="600">{size}</text>'
        )
    rows.append(
        f'  <text class="muted" x="{left - 12}" y="{top - 10}" text-anchor="end">'
        f'size_x = size_y</text>'
    )

    for row, terrain in enumerate(terrains):
        y = top + row * cell_h
        rows.append(
            f'  <text class="label" x="{left - 12}" y="{y + 22}" text-anchor="end">'
            f'{terrain}</text>'
        )
        for col in range(len(sizes)):
            x = left + col * cell_w
            rows.append(
                f'  <rect class="game" x="{x + 2}" y="{y + 2}" '
                f'width="{cell_w - 4}" height="{cell_h - 4}" rx="4"/>'
            )

    grid_bottom = top + cell_h * len(terrains)

    locked_y = grid_bottom + 26
    rows.append(f'  <rect class="guard" x="24" y="{locked_y}" width="{width - 48}" height="76" rx="8"/>')
    rows.append(f'  <text class="guard-t" x="44" y="{locked_y + 22}">Locked: identical in every scored run</text>')
    for index, line in enumerate(locked_lines):
        rows.append(f'  <text class="label" x="44" y="{locked_y + 43 + index * 18}">{line}</text>')

    seed_y = locked_y + 88
    rows.append(f'  <rect class="data" x="24" y="{seed_y}" width="{width - 48}" height="76" rx="8"/>')
    rows.append(f'  <text class="data-t" x="44" y="{seed_y + 22}">The seed is where the variance lives</text>')
    for index, line in enumerate(seed_lines):
        rows.append(f'  <text class="label" x="44" y="{seed_y + 43 + index * 18}">{line}</text>')

    _write("scoreable_worlds.svg", _svg(width, seed_y + 96, "\n".join(rows) + "\n"))


def play_modes() -> None:
    """Who plays, in which mode, and what that mode actually measures."""
    body = """
  <text class="title" x="493" y="28" text-anchor="middle" font-size="15">Play modes: what each one measures</text>
  <text class="muted" x="493" y="46" text-anchor="middle">nttd never asks what kind of contestant you are, so the column below is convention plus one hard constraint</text>

  <rect class="actor" x="24" y="74" width="330" height="182" rx="8"/>
  <text class="actor-t" x="44" y="98">Contestant</text>
  <text class="muted" x="250" y="98">usual mode</text>

  <text class="label" x="44" y="126">Human</text>
  <text class="muted" x="250" y="126">real time only</text>
  <text class="label" x="44" y="154">Single LLM agent</text>
  <text class="muted" x="250" y="154">either</text>
  <text class="label" x="44" y="182">Multi-agent system</text>
  <text class="muted" x="250" y="182">either</text>
  <text class="label" x="44" y="210">RL policy</text>
  <text class="muted" x="250" y="210">stepped</text>
  <text class="label" x="44" y="238">ES population</text>
  <text class="muted" x="250" y="238">stepped</text>

  <line class="edge" x1="356" y1="130" x2="404" y2="124" marker-end="url(#a)"/>
  <line class="edge" x1="356" y1="222" x2="404" y2="218" marker-end="url(#a)"/>

  <rect class="server" x="406" y="86" width="196" height="76" rx="8"/>
  <text class="server-t" x="504" y="110" text-anchor="middle">Real time</text>
  <text class="muted" x="504" y="130" text-anchor="middle">the world never stops;</text>
  <text class="muted" x="504" y="147" text-anchor="middle">submit whenever ready</text>

  <rect class="server" x="406" y="180" width="196" height="76" rx="8"/>
  <text class="server-t" x="504" y="204" text-anchor="middle">Stepped</text>
  <text class="muted" x="504" y="224" text-anchor="middle">paused between steps;</text>
  <text class="muted" x="504" y="241" text-anchor="middle">deliberation costs 0 days</text>

  <line class="edge" x1="604" y1="124" x2="642" y2="124" marker-end="url(#a)"/>
  <line class="edge" x1="604" y1="218" x2="642" y2="218" marker-end="url(#a)"/>

  <rect class="box" x="644" y="86" width="318" height="76" rx="8"/>
  <text class="label" x="662" y="110" font-weight="600">Measures play AND speed</text>
  <text class="muted" x="662" y="130">A faster model gets more decisions per horizon.</text>
  <text class="muted" x="662" y="147">Bounded by wall-minutes. Ceiling: 15 actions.</text>

  <rect class="box" x="644" y="180" width="318" height="76" rx="8"/>
  <text class="label" x="662" y="204" font-weight="600">Measures policy only</text>
  <text class="muted" x="662" y="224">Slowness is not punished: thinking is free.</text>
  <text class="muted" x="662" y="241">Bounded by steps. Wall-clock bounds are refused.</text>

  <rect class="guard" x="24" y="272" width="938" height="58" rx="8"/>
  <text class="guard-t" x="44" y="294">Why a human is real time only</text>
  <text class="label" x="44" y="315">A stepped world is paused until a registered stepper calls POST /step, and an OpenTTD client has no way to. Everything else is convention.</text>

  <rect class="data" x="24" y="344" width="938" height="76" rx="8"/>
  <text class="data-t" x="44" y="366">Scored the same way in either mode</text>
  <text class="label" x="44" y="387">performance_rating (0-1000), cargo delivered breaks ties, one row per company.</text>
  <text class="label" x="44" y="405">The mode is recorded, so a reader can compare within it rather than across it.</text>
"""
    _write("play_modes.svg", _svg(986, 440, body))


def step_barrier() -> None:
    """The stepped-mode sequence, and why the flush happens unpaused."""
    body = """
  <text class="title" x="427" y="28" text-anchor="middle" font-size="15">The step barrier (stepped mode, for RL and ES)</text>
  <text class="muted" x="427" y="46" text-anchor="middle">one synchronous call per step; between steps the game is paused, so deliberation is free</text>

  <rect class="actor" x="24" y="72" width="150" height="54" rx="8"/>
  <text class="actor-t" x="99" y="95" text-anchor="middle">1. observe</text>
  <text class="muted" x="99" y="113" text-anchor="middle">paused</text>

  <line class="edge" x1="176" y1="99" x2="210" y2="99" marker-end="url(#a)"/>
  <rect class="actor" x="212" y="72" width="180" height="54" rx="8"/>
  <text class="actor-t" x="302" y="95" text-anchor="middle">2. deliberate</text>
  <text class="muted" x="302" y="113" text-anchor="middle">unbounded, costs 0 game-days</text>

  <line class="edge" x1="394" y1="99" x2="428" y2="99" marker-end="url(#a)"/>
  <rect class="server" x="430" y="72" width="150" height="54" rx="8"/>
  <text class="server-t" x="505" y="95" text-anchor="middle">3. POST /step</text>
  <text class="muted" x="505" y="113" text-anchor="middle">batch, up to 15</text>

  <line class="edge" x1="505" y1="128" x2="505" y2="162" marker-end="url(#a)"/>

  <rect class="game" x="176" y="164" width="654" height="98" rx="8"/>
  <text class="game-t" x="503" y="186" text-anchor="middle">inside one request, synchronously</text>
  <rect class="box" x="192" y="198" width="138" height="48" rx="4"/>
  <text class="label" x="261" y="219" text-anchor="middle">fix target date</text>
  <text class="muted" x="261" y="236" text-anchor="middle">before the world moves</text>
  <line class="edge" x1="332" y1="222" x2="354" y2="222" marker-end="url(#a)"/>
  <rect class="box" x="356" y="198" width="138" height="48" rx="4"/>
  <text class="label" x="425" y="219" text-anchor="middle">unpause, flush</text>
  <text class="muted" x="425" y="236" text-anchor="middle">actions need ticks</text>
  <line class="edge" x1="496" y1="222" x2="518" y2="222" marker-end="url(#a)"/>
  <rect class="box" x="520" y="198" width="138" height="48" rx="4"/>
  <text class="label" x="589" y="219" text-anchor="middle">advance N days</text>
  <text class="muted" x="589" y="236" text-anchor="middle">to the fixed target</text>
  <line class="edge" x1="660" y1="222" x2="682" y2="222" marker-end="url(#a)"/>
  <rect class="box" x="684" y="198" width="132" height="48" rx="4"/>
  <text class="label" x="750" y="219" text-anchor="middle">pause, observe</text>
  <text class="muted" x="750" y="236" text-anchor="middle">consistent state</text>

  <rect class="guard" x="24" y="282" width="806" height="78" rx="8"/>
  <text class="guard-t" x="44" y="305">Why the flush unpauses, rather than applying actions to a still world</text>
  <text class="label" x="44" y="327">A GameScript command completes on a game TICK. The pathfinder yields through Sleep(1), which counts ticks, so a</text>
  <text class="label" x="44" y="345">LONG connect_road hangs while paused and a short one does not. Which one, is not knowable in advance.</text>

  <text class="title" x="427" y="404" text-anchor="middle" font-size="14">With several companies: the clock is shared, participation is not</text>

  <rect class="actor" x="24" y="424" width="150" height="44" rx="8"/>
  <text class="actor-t" x="99" y="443" text-anchor="middle">company 0 steps</text>
  <text class="muted" x="99" y="460" text-anchor="middle">arrives first, waits</text>

  <rect class="actor" x="24" y="478" width="150" height="44" rx="8"/>
  <text class="actor-t" x="99" y="497" text-anchor="middle">company 1 steps</text>
  <text class="muted" x="99" y="514" text-anchor="middle">arrives later</text>

  <line class="edge" x1="176" y1="446" x2="228" y2="465" marker-end="url(#a)"/>
  <line class="edge" x1="176" y1="500" x2="228" y2="481" marker-end="url(#a)"/>

  <rect class="server" x="230" y="440" width="176" height="66" rx="8"/>
  <text class="server-t" x="318" y="464" text-anchor="middle">window</text>
  <text class="muted" x="318" y="481" text-anchor="middle">closes when every</text>
  <text class="muted" x="318" y="496" text-anchor="middle">registered stepper is in</text>

  <line class="edge" x1="408" y1="473" x2="446" y2="473" marker-end="url(#a)"/>
  <rect class="game" x="448" y="440" width="176" height="66" rx="8"/>
  <text class="game-t" x="536" y="464" text-anchor="middle">ONE world advance</text>
  <text class="muted" x="536" y="481" text-anchor="middle">both batches, company</text>
  <text class="muted" x="536" y="496" text-anchor="middle">order; same observation</text>

  <line class="edge" x1="626" y1="473" x2="664" y2="473" marker-end="url(#a)"/>
  <rect class="box" x="666" y="440" width="164" height="66" rx="8"/>
  <text class="label" x="748" y="464" text-anchor="middle">K steps = K intervals</text>
  <text class="muted" x="748" y="481" text-anchor="middle">whether 1 company</text>
  <text class="muted" x="748" y="496" text-anchor="middle">plays or four</text>

  <rect class="guard" x="24" y="534" width="806" height="58" rx="8"/>
  <text class="guard-t" x="44" y="556">No decision deadline; only a liveness one</text>
  <text class="label" x="44" y="577">A slow policy is never truncated. A company silent for 10 minutes is evicted and recorded, so a dead runner cannot hang the run.</text>
"""
    _write("step_barrier.svg", _svg(854, 612, body))


def benchmark_profile() -> None:
    """What a scored world may be, and how a task gets its identity."""
    body = """
  <text class="title" x="414" y="28" text-anchor="middle" font-size="15">What makes two runs comparable</text>
  <text class="muted" x="414" y="46" text-anchor="middle">config/benchmark/profile.conf is the single authority, and is meant to be edited by hand</text>

  <rect class="guard" x="24" y="70" width="254" height="180" rx="8"/>
  <text class="guard-t" x="151" y="92" text-anchor="middle">Locked</text>
  <text class="muted" x="151" y="111" text-anchor="middle">must match exactly</text>
  <text class="label" x="40" y="136">starting_year = 2020</text>
  <text class="label" x="40" y="154">variety, smoothness, rivers</text>
  <text class="label" x="40" y="172">sea_level, map_edges</text>
  <text class="label" x="40" y="190">town_names, number_towns</text>
  <text class="label" x="40" y="208">industry_density, landscape</text>
  <text class="muted" x="40" y="234">a difference here is invisible</text>

  <rect class="actor" x="290" y="70" width="254" height="180" rx="8"/>
  <text class="actor-t" x="417" y="92" text-anchor="middle">Free to vary</text>
  <text class="muted" x="417" y="111" text-anchor="middle">each is a leaderboard column</text>
  <text class="label" x="306" y="136">size (both axes, equal)</text>
  <text class="muted" x="306" y="152">64 | 128 | 256 | 512 | 1024</text>
  <text class="label" x="306" y="176">terrain_type</text>
  <text class="muted" x="306" y="192">very_flat | flat | hilly |</text>
  <text class="muted" x="306" y="208">mountainous | alpinist</text>
  <text class="muted" x="306" y="234">5 x 5 = 25 scoreable maps</text>

  <rect class="data" x="556" y="70" width="242" height="180" rx="8"/>
  <text class="data-t" x="677" y="92" text-anchor="middle">task_id</text>
  <text class="muted" x="677" y="111" text-anchor="middle">derived, not declared</text>
  <text class="label" x="572" y="138">sha256 over</text>
  <text class="muted" x="572" y="156">scenario id + version</text>
  <text class="muted" x="572" y="172">+ seed</text>
  <text class="muted" x="572" y="188">+ normalised settings</text>
  <text class="label" x="572" y="216">same world, same id,</text>
  <text class="label" x="572" y="234">whoever hosted it</text>

  <rect class="box" x="24" y="274" width="774" height="78" rx="8"/>
  <text class="title" x="44" y="298">Conformance is the credential. There is no list of approved scenarios.</text>
  <text class="label" x="44" y="320">Write your own: if it stays inside the profile it is a benchmark run, whether or not it says so. Scoredness is COMPUTED</text>
  <text class="label" x="44" y="338">from the world, so scored = true grants nothing: over a non-conforming world it is refused, not honoured.</text>
"""
    _write("benchmark_profile.svg", _svg(822, 372, body))


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Generating architecture diagrams:")
    architecture()
    trust_tiers()
    step_barrier()
    scoreable_worlds()
    play_modes()
    benchmark_profile()
    print("Done.")


if __name__ == "__main__":
    main()
