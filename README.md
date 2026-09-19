# skill-router

Routes an agent's intent to the one installed skill that fits, across harnesses, using
TypeSafe's Jev (a System One model that returns calibrated probabilities instead of text).

Two requests per intent, following TypeSafe's skill-suggestion cookbook:

1. Rank every skill on the roster with a Choice question, and gate with three Nouls that ask
   whether the request needs a skill at all.
2. Rerank the top three with each skill's full description and opening body, and verify each
   with an absolute "does this skill do this" Noul. Any shortlist whose best fit is under the
   threshold returns nothing.

Three outcomes: `matched` (one skill name), `missing` (the request needs a skill and none
installed covers it; the rerank has an explicit no-match option), and `none_needed`.

## Tests

```bash
uv run python -m unittest discover -s tests
```

## Setup

```bash
uv sync
uv run skill-router setup          # stores the TypeSafe key in the macOS Keychain
uv run skill-router roster         # what would be routed over
uv run skill-router route "turn this podcast into a labeled transcript"
```

`setup` verifies the key against the API before storing it. The key is read from
`TYPESAFE_API_KEY`, then the macOS Keychain item `typesafe-api-key`, then the 0600 file
`~/.config/skill-router/api_key` (the store used on Linux).

## Roster discovery

`~/.claude/skills`, `~/.claude/plugins/cache/**/skills` (as `plugin:skill`), `~/.codex/skills`,
`~/.agents/skills`, and the nearest project `.claude/skills`. First occurrence of a name wins.

## Surfaces

- CLI: `skill-router route "<intent>" [--json | --block]`
- MCP: `skill-router-mcp` (stdio) exposes `route_skill(intent, context, cwd)` and `list_skills(cwd)`.
- Claude Code hook: `skill-router-hook` reads the `UserPromptSubmit` payload and prints a
  `<skill_relevance>` block; wire it in `settings.json` under `hooks.UserPromptSubmit`.

## Config

`~/.config/skill-router/config.toml` (or `SKILL_ROUTER_CONFIG`). Every key is optional;
unknown keys and out-of-range values are rejected at load:

```toml
model = "jev-latest"
shortlist = 3
gate_floor = 0.12          # below: none_needed without a second request
gate_threshold = 0.30      # above: the request needs a skill; below: gray zone
fits_threshold = 0.30      # required fit when the gate says a skill is needed
gray_fits_threshold = 0.75 # required fit in the gray zone
timeout = 30.0             # per request, CLI and MCP
hook_timeout = 6.0         # per request inside the prompt hook, no retries
hook_deadline = 15.0       # end to end; the hook prints nothing and exits 0 past this
intent_chars = 4000        # inputs are truncated to these before they are sent
context_chars = 4000
wide_chunk_chars = 90000   # rosters larger than this are ranked in chunks, then leaders compete;
                           # must hold two entries: 2 * (128 + wide_description_chars + 8)
extra_roots = ["~/my-skills"]
disabled_harnesses = ["codex"]
exclude = ["zain-voice-v1"]
```
