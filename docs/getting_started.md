# Getting started: one whole experiment

From nothing to a row on the board. Every command below is one you run; nothing is
illustrative. If you only read one page first, read this one.

The pieces live in three repositories and it is worth knowing which does what:

| repository | what it owns |
|---|---|
| `nttd` | the engine. Draws the world, runs the game, records artifacts, scores the result. |
| `nttd-workbench` | contestant-side runners: the loop that decides what to do. |
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

### Running on Linux (untested)

nttd has never been run end to end on Linux. Lint and the test suite run there in CI, but
the suite needs no OpenTTD, so nothing has ever proved a game starts. If you want to try,
these are the two things known to be in the way.

**1. The binary is looked for at a macOS path.** The default is
`/Applications/OpenTTD.app/Contents/MacOS/openttd`, written out in six places. Set
`NTTD_OPENTTD_BINARY` to your executable and the server, the CLI and the scripts will use it.

**2. No distribution packages OpenTTD 15.3,** which is what nttd is written against. Checked
in August 2026:

| Source | Version |
| --- | --- |
| Ubuntu 24.04 noble, which is `ubuntu-latest` | 13.4 |
| Ubuntu plucky, Debian trixie | 14.1 |
| Debian sid | 15.1 |

This is not cosmetic. OpenTTD refuses a savegame written by a newer version, so an older
build cannot read a session's `final.sav` at all, and several behaviours nttd depends on were
established by measurement against 15.3. Install the official release rather than the
package:

```bash
curl -fsSLO https://cdn.openttd.org/openttd-releases/15.3/openttd-15.3-linux-generic-amd64.tar.xz
tar -xJf openttd-15.3-linux-generic-amd64.tar.xz
export NTTD_OPENTTD_BINARY="$PWD/openttd-15.3-linux-generic-amd64/openttd"
```

Add OpenGFX as well. The release tarball ships the baseset metadata but no graphics, and
OpenTTD will not start without a base graphics set even under `-D`, where nothing is drawn:

```bash
curl -fsSLO https://cdn.openttd.org/opengfx-releases/8.0/opengfx-8.0-all.zip
unzip -q opengfx-8.0-all.zip && tar -xf opengfx-8.0.tar \
  -C openttd-15.3-linux-generic-amd64/baseset
```

The generic build is dynamically linked, so on a slim system you may also need
`libfontconfig1 libfreetype6 liblzma5 liblzo2-2 libpng16-16 zlib1g`. Then check it before
trusting it: `$NTTD_OPENTTD_BINARY --version`, followed by
`uv run python -m scripts.verify_environment`, which is the script that would catch a
version difference actually mattering.

Reports of what does and does not work are welcome.

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

That one command is the four below rolled together, and the four are there when you want to
change something in the middle, run two sessions on one server, or start a session now and
attach to it much later:

```bash
uv run nttd server                                                # terminal 1
uv run nttd session create --config config/benchmark/t1_256_flat_1001_stepped.conf
uv run nttd session start -s <session> --agent-companies 1
uv run nttd session attach <session>   # prints the participant token
```

`--agent-companies 1` is the one to notice. Without it the session starts with no contestant
company, so no participant token is issued and nothing can play it.

A session id looks like `20260815-132431ist-quiet-pickle`, which is the date and time it
started followed by a word pair. It is the only name the run has, and it is what ties the
artifacts, the monitor view and the board row together.

---

## 4. Play it

Anything that can speak HTTP can play. The worked runners are in the examples repository:

```bash
git clone git@github.com:deepsaia/nttd-workbench.git
cd nttd-workbench && uv sync
uv run runex
```

A few questions, and the usual answer to each is Enter, because it reads the answers off
the running server. [cli_guide.md](cli_guide.md#nttd-runex) has the detail and the flags
for skipping them.

Nothing depends on it. The same run starts by hand:

```bash
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

It works on a run in progress or a finished one, and needs nothing running:
[cli_guide.md](cli_guide.md#nttd-monitor). Two panels earn their place while something is
going wrong:

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
uv run nttd package -s <session>             # writes <session dir>/submission
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

Add `--dry-run` first to see exactly what would be filed and where, and remember that the
pull request has to be **merged** before verification will find it. The README in
nttd-workbench covers the contestant path in full.

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
