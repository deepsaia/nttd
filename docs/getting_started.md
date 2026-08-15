# Getting started: one whole experiment

From nothing to a row on the board. Every command below is one you run; nothing is
illustrative. If you only read one page first, read this one.

The pieces live in three repositories and it is worth knowing which does what:

| repository | what it owns |
|---|---|
| `nttd` | the engine. Draws the world, runs the game, records artifacts, scores the result. |
| `nttd-examples` | contestant-side runners: the loop that decides what to do. |
| `nttd-leaderboard` | the board. Verifies a bundle and publishes the verdict. |

---

## 1. Install

```bash
git clone git@github.com:deepsaia/nttd.git
cd nttd
uv sync
```

You also need the game itself. `docs/cli_guide.md` has the per-platform detail; the short
version is that nttd drives a real OpenTTD binary and will tell you if it cannot find one:

```bash
uv run nttd scenario validate config/benchmark/t1_256_flat_1001_stepped.conf
```

---

## 2. Pick a tier

A scenario decides the world and how long the run lasts. The shipped ones are named for what
they are, `<tier>_<size>_<terrain>_<seed>_<mode>`:

```bash
ls config/benchmark/
```

- **T1** is a single game year, 366 days. Short, and the right one to learn on.
- **Stepped** advances only when your runner asks it to, so thinking time is free. **Realtime**
  runs on a clock, so speed counts. They are not comparable to each other and the board keeps
  them apart.

Start with `t1_256_flat_1001_stepped.conf`.

---

## 3. Run it

Two terminals.

```bash
uv run nttd server                                                     # terminal 1
uv run nttd benchmark --config config/benchmark/t1_256_flat_1001_stepped.conf   # terminal 2
```

`benchmark` creates the session, draws the world, prints a **session id** and a
**participant token**, and then waits. It does not play: attaching a runner is your half.

A session id looks like `20260815-132431ist-quiet-pickle`, which is the date and time it
started followed by a word pair. It is the only name the run has, and it is what ties the
artifacts, the monitor view and the board row together.

---

## 4. Play it

Anything that can speak HTTP can play. The worked runners are in the examples repository:

```bash
git clone git@github.com:deepsaia/nttd-examples.git
cd nttd-examples && uv sync
uv run python -m examples.minimal_runner --session <session> --token <token>
```

`docs/agent_guide.md` in this repository describes the action surface, and `docs/actions/`
documents every action with its parameters and returns. If you would rather drive it by hand
first, `uv run nttd mcp --session <session>` serves one session over MCP.

---

## 5. Watch it while it runs

```bash
uv run nttd monitor        # then open http://127.0.0.1:4281
```

The monitor reads session directories from disk, so it works on a run in progress, on a
finished one, and on a copy of a session directory from another machine. Two panels earn
their place while something is going wrong:

- **Fleet, worst earner first** names the vehicle that is failing and why: lost, no orders,
  in depot, not moving. A single silent failure among thirty vehicles is the first row.
- **Actions by type** separates one call failing repeatedly from occasional refusals.

---

## 6. Read what happened

```bash
uv run nttd result -s <session>     # the scored row
uv run nttd analyze -s <session>    # fourteen reports: cargo, finance, routes, fleet, world
```

`docs/gameplay_guide.md` explains what the score is actually measuring, which is worth
reading before trying to improve it.

---

## 7. Submit it

```bash
uv run nttd submit -s <session>              # writes <session dir>/submission
uv run nttd verify <session dir>/submission  # your own check first
```

`verify` reports the same checks the board runs and predicts a verdict, but it is advisory:
it ran on your machine, from code you could have changed. The verdict that counts is
computed by whoever ingests the bundle.

Then file it. One command, and the pull request is yours: the token is your own HuggingFace
one, and nobody needs write access to the board.

```bash
uv sync --extra publish                                   # once
export HF_TOKEN=...                                       # your token, write scope
uv run nttd publish -s <session> --entrant <your name>
```

Add `--dry-run` first to see exactly what would be filed and where. `docs/submitting.md` in
nttd-examples covers the contestant path in full.

### If you are running the board yourself

The third repository verifies what was filed and publishes the page. Verifying needs an
OpenTTD binary, because it reloads the savegame and recomputes the score:

```bash
git clone git@github.com:deepsaia/nttd-leaderboard.git
cd nttd-leaderboard && uv sync

uv run nttd-board ingest <pr number>                  # the cheap check on one pull request
uv run nttd-board verify --submission <entrant>/<id>  # verify one, then publish
uv run nttd-board verify                              # or everything unjudged

uv run --no-project --with huggingface_hub python scripts/deploy_space.py
uv run --no-project --with huggingface_hub python scripts/deploy_datasets.py
```

Publishing needs a write token. It is a repository secret used by the workflows and nowhere
else, so nothing above needs it in a shell unless you are publishing from your own machine.

Verification and deployment are deliberately separate: deploying publishes a page, verifying
decides a verdict, and bundling them would mean a page could not be corrected without
rejudging every submission. `docs/how-the-board-works.md` there has the rest.

---

## What good looks like

A first run that builds nothing is normal, and the monitor will say so rather than leaving
you to guess. The things that most often go wrong on a first attempt, in order:

1. **A build returning `success` is not a working route.** Verify that a vehicle can reach
   the far end before buying one.
2. **A station outside its own catchment earns nothing.** Coverage is small; site by it.
3. **Borrowing to the ceiling costs score.** The rating's loan component is
   `250,000 - current_loan`, so a full 300,000 loan forfeits all of it.

All three are covered with evidence in `docs/gameplay_guide.md`.
