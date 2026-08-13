# config/actions

Three files, three different update rules. Editing the wrong one loses work, so the rule for
each is written here rather than left to be inferred from the contents.

| File | Rule | Source of truth |
| --- | --- | --- |
| `manifest.json` | **Generated. Never edit.** | `ottd_config/game/nttd-gs/main.nut` |
| `descriptions.json` | **Hand-written.** Edit this one. | a human who read the GameScript |
| `enums.json` | **Extracted from an OpenTTD build.** | the `openttd` binary itself |

Each file also says which it is internally: `manifest.json` carries `generated_from`,
`enums.json` carries `source` and `openttd_version`, and `descriptions.json` opens with a
`_comment` explaining what belongs in it.

## manifest.json

Regenerated from the GameScript's dispatch table:

```bash
uv run python scripts/generate_action_manifest.py
```

That rewrites `manifest.json` and `docs/action_reference.md` together, merging
`descriptions.json` in as it goes. It prints how many actions and parameters have no prose,
which is the number to drive to zero.

Anything typed into `manifest.json` by hand is destroyed the next time it runs. CI also fails
when a `main.nut` change lands without regenerating it, because a published surface that
disagrees with the game is the defect that produced issues #68 and #108: an agent was told a
parameter existed that the GameScript never read.

**This needs a checkout.** The wheel ships the generated files but not `scripts/`, so an
installed nttd cannot regenerate anything. It does not need to: the manifest describes the
GameScript, and changing that means editing `main.nut`, which is a checkout in the first place.

## descriptions.json

The prose. Kept out of `manifest.json` precisely so regeneration cannot destroy it.

Describe what the GameScript **actually does**, checked against its implementation. A
plausible description inferred from a parameter name is worse than a missing one, because an
agent will believe it. It also holds:

- `parameter_glossary`, one type and one description per parameter name, applied everywhere
  that name appears. That is what keeps 36 uses of `x` saying the same thing. An action
  overrides an entry only where the meaning genuinely differs, which is why `direction` has
  one: it picks a track orientation for `build_rail_station` and an adjacent tile everywhere
  else.
- `enum_bindings`, which OpenTTD enum a parameter draws from. The values are **not** written
  here, because a wrong constant is worse than a missing one: `OF_UNLOAD` and
  `OF_SERVICE_IF_NEEDED` are both 4 and the game would accept either.
- `one_of`, parameters that substitute for each other. Only the GameScript call site knows
  which alternatives belong together, so these are declared rather than extracted.

## enums.json

Constant values read out of a specific OpenTTD build, so that `enum_bindings` can resolve to
numbers nttd never guessed:

```bash
uv run python scripts/dump_gs_enums.py [path/to/openttd]
```

**This one goes stale silently when OpenTTD is upgraded**, which is the reason it records
`openttd_version`. `tests/test_action_enum_freshness.py` compares that against the OpenTTD on
this machine and fails when they diverge, so an upgrade is noticed here rather than as an
action mysteriously refused in a game. It skips when no binary is available, since it cannot
check what it cannot run.
