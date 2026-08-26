# nttd

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22105381.svg)](https://doi.org/10.5281/zenodo.22105381)

**A benchmark for long-horizon planning, built on OpenTTD.**

**nttd does not run your agent.** This repository is the engine: it draws the world, runs
the game and scores the result. The agents that play it live in
**[nttd-workbench](https://github.com/deepsaia/nttd-workbench)**, which is where to go if
what you want is to watch something play a session rather than to write one from scratch.

An agent has to build a transport network that turns a profit: survey a map, pick routes
worth serving, lay track and roads, buy vehicles, set orders, and manage a loan. A decision
made in the first game month is still paying or costing you two game years later.

nttd wraps an OpenTTD 15.3 dedicated server and exposes the game as a structured JSON API.
It is agent-agnostic and framework-agnostic: you bring the loop, in your own process, in
whatever language you like. An LLM agent, a multi-agent system, an RL policy, an ES
population and a human all reach the game through the same surface and are recorded the
same way.

![nttd architecture](docs/images/architecture.svg)

New here, and want the whole thing explained rather than listed?
**[docs/getting_started.md](docs/getting_started.md)** walks one experiment end to end.

---

## Install

macOS, Python 3.13+, [uv](https://docs.astral.sh/uv/), and
[OpenTTD 15.3](https://www.openttd.org/downloads/openttd-releases/latest).

```bash
git clone git@github.com:deepsaia/nttd.git
cd nttd
uv sync                                       # server, CLI, analysis, RL, MCP, tests
uv run python -m scripts.verify_environment   # spawns real servers; takes a few minutes
```

Install OpenTTD, launch it once, and add **OpenGFX2 Classic** from Online Content. nttd
looks for `/Applications/OpenTTD.app/Contents/MacOS/openttd`; override with
`NTTD_OPENTTD_BINARY`.

> **nttd is developed and tested on macOS only.** Linux and Windows are untested and need
> extra steps: [getting_started.md](docs/getting_started.md#running-on-linux-untested).

---

## Run a benchmark

Four commands across two repositories, because nttd runs no agent.

```bash
# --- here ---------------------------------------------------------------------------------
uv run nttd server                                                            # terminal 1
uv run nttd benchmark --config config/benchmark/t1_256_flat_1001_stepped.conf  # terminal 2

# --- in an nttd-workbench checkout --------------------------------------------------------
uv run runex                                                                  # terminal 3
```

`nttd server` is the API on `:8000`; leave it up, one server serves any number of sessions.
`nttd benchmark` creates a session, generates its world, starts OpenTTD, prints the session
id and participant token, then waits for an end condition and writes the result.
`ls config/benchmark/` has all four tiers in both modes.

> ### [Optional] Drive the lifecycle yourself
>
> Instead of `nttd benchmark`, which is these rolled into one. Use them separately to change
> something in between, run two sessions against one server, or open a world now and attach
> to it much later. Nothing here waits for the end condition, so you stop the run yourself.
>
> ```bash
> uv run nttd session create --config config/benchmark/t2_256_flat_1001_realtime.conf
> uv run nttd session start -s <session> --agent-companies 1   # no flag, no company, no token
> uv run nttd session attach <session>                         # positional here; token and routes
> uv run nttd session stop -s <session>                        # writes result.parquet
> uv run nttd result -s <session>
> ```

### Watch it, and read it

```bash
uv run nttd monitor                      # then open http://127.0.0.1:4281
uv run nttd analyze -s <session>
```

### Submit it

```bash
uv run nttd package -s <session>                         # writes <session dir>/submission
uv run nttd verify logs/sessions/<session>/submission    # your own check, advisory
uv sync --extra publish                                  # once
export HF_TOKEN=...                                      # your own token, write scope
uv run nttd publish -s <session> --entrant <you> --id <name> --dry-run
```

### Check a scenario before a long run

```bash
uv run nttd scenario validate config/benchmark/t2_256_flat_1001_realtime.conf
uv run nttd scenario profile             # the rules a scored scenario must satisfy
```

---

## Commands

```
nttd server                 Start the API server
nttd benchmark              Stand up a benchmark task and wait for it to end
nttd session create         Create a session from a scenario
nttd session start          Generate the world and start OpenTTD
nttd session attach         Show the token and routes a runner needs
nttd session stop           Stop a session and write its result
nttd session list           List sessions
nttd session status         Show detailed session status
nttd scenario validate      Check a scenario without running it
nttd scenario profile       Show the rules a scored scenario must satisfy
nttd actions                Show every action and what it takes
nttd mcp                    Serve one session to an MCP client
nttd runex                  Run an experiment against a live session, choosing interactively
nttd monitor                Watch sessions in a browser while they run
nttd package                Package a session into a submission bundle
nttd verify                 Self-check a bundle before submitting it
nttd result                 Show the scored result record
nttd analyze                Generate analysis reports
nttd publish                File a bundle on the board as a pull request
```

Every command with its flags: [docs/cli_guide.md](docs/cli_guide.md). Full API at
`http://localhost:8000/docs` once the server is running.

---

## Documentation

| | |
|---|---|
| [Getting started](docs/getting_started.md) | One whole experiment, from install to a published row |
| [Architecture](docs/architecture.md) | How the pieces fit, and why the boundaries are where they are |
| [Play modes and scoring](docs/play_modes.md) | Which worlds are scoreable, the two modes, and how a run is ranked |
| [CLI guide](docs/cli_guide.md) | Every command, with examples |
| [Agent guide](docs/agent_guide.md) | Writing a runner against the participant routes |
| [Gameplay guide](docs/gameplay_guide.md) | What the score measures, and how to earn it |
| [Action reference](docs/action_reference.md) | Every action, its parameters and accepted values |
| [MCP guide](docs/mcp_guide.md) | Playing over MCP: five tools, both transports |
| [Session analysis](docs/session_analyzer.md) | Reading a completed run, and the monitor |

---

## Development

```bash
uv run pytest -q
uv run ruff check src/ tests/
uv run python scripts/generate_diagrams.py
uv run python scripts/generate_action_manifest.py   # regenerates docs/action_reference.md
```

The GameScript lives in `ottd_config/game/nttd-gs/main.nut`. It is loaded from the
per-session config directory, so editing it takes effect on the next session: no rebuild.

Reference runners live in
[deepsaia/nttd-workbench](https://github.com/deepsaia/nttd-workbench). They are
contestant-side code and none of them import the `nttd` package: this repository ships only
the engine, `src/nttd`.

---

## License

Apache-2.0. The GameScript runs in-process against OpenTTD's GPL-2.0 API; see
`ottd_config/game/nttd-gs/` for its header.

---

## Citation

If you use nttd in academic work, please cite it using the following BibTeX entry:

```bibtex
@software{nttd,
  author = {Deepak},
  title  = {{nttd: an agent-agnostic benchmark for long-horizon planning, built on OpenTTD}},
  year   = {2026},
  doi    = {10.5281/zenodo.22105381},
  url    = {https://doi.org/10.5281/zenodo.22105381}
}
```

The DOI above is the **concept DOI**, which always resolves to the latest release and
aggregates citations across all versions. To cite a specific version instead, use that
version's DOI from the [Zenodo record](https://doi.org/10.5281/zenodo.22105381).
