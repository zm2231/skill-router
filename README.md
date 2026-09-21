# skill-router

Given what a user just asked for, name the one installed skill that should handle it, or say
none does. It reads every `SKILL.md` the agent harnesses on this machine can load (Claude Code,
Codex, `~/.agents`, plugins, the current project) and asks TypeSafe's Jev, a model that returns
calibrated probabilities instead of text, to pick. Two API calls per intent for a roster that
fits one request.

## Quick path

You need Python 3.13+, [uv](https://docs.astral.sh/uv/), and a TypeSafe API key from
[typesafe.ai](https://typesafe.ai).

```bash
uv tool install git+https://github.com/zm2231/skill-router   # or: git clone + uv sync, then prefix each command with `uv run`
skill-router setup                     # verifies the key, then stores it (Keychain on macOS, 0600 file elsewhere)
skill-router roster                    # every skill it would route over
skill-router route "turn this podcast into a labeled transcript"
```

The last line prints the outcome, then the shortlist with each skill's probability and fit:

```
intent: turn this podcast into a labeled transcript
gate 0.52  rerank winner  model=jev-1.13.0  tokens=12384
matched: <skill-name>
  0.970  <skill-name>                             fits 0.94
  0.030  <runner-up>                              fits 0.16
```

Add `--json` for the gate scores and ranked shortlist, `--block` for the `<skill_relevance>`
block an agent would read.

## How a route is decided

| Step | Request | Result |
|------|---------|--------|
| 1. Gate | Three yes/no questions: does this request act on the user's system, would it follow a documented procedure, does prose suffice? | `none_needed` when the combined score is under `gate_floor`; otherwise continue |
| 2. Wide rank | One Choice over the whole roster, name plus 320 chars of description each | Top `shortlist` (3) skills |
| 3. Rerank | One Choice over the shortlist with full description and body excerpt, plus an explicit `none-of-these` option; each candidate also gets an absolute "does this skill do this" check | `matched` with one name, or `missing` |

A winner must clear `fits_threshold` (0.30); in the gray zone between `gate_floor` and
`gate_threshold` it must clear `gray_fits_threshold` (0.75) instead. Rosters larger than
`choice_chars` are ranked in chunks and the chunk leaders compete, one extra request per chunk.

## Where skills come from

| Source | Path | Name |
|--------|------|------|
| project | nearest `.claude/skills/` walking up from `cwd` | directory name |
| claude-code | `~/.claude/skills/` | directory name |
| codex | `~/.codex/skills/` | directory name |
| agents | `~/.agents/skills/` | directory name |
| extra | `extra_roots` in config | directory name |
| claude-code-plugin | `~/.claude/plugins/cache/*/*/*/skills/` | `plugin:skill` |

Each entry is `<dir>/*/SKILL.md`. The name is the directory, not the frontmatter `name:`. Only
the frontmatter `description` is used for ranking; a skill without one gets the first 200 chars
of its body. First occurrence of a name wins, in the order above.

## Surfaces

| Surface | Command | Notes |
|---------|---------|-------|
| CLI | `skill-router route "<intent>" [--context ...] [--json \| --block]` | Exit 2: missing key or bad config. Exit 3: TypeSafe unreachable or rejected the request. One-line stderr message either way |
| MCP (stdio) | `skill-router-mcp` | `route_skill(intent, context, cwd)` and `list_skills(cwd)`; call on demand from an agent |
| Claude Code hook | `skill-router-hook` | Fires on every `UserPromptSubmit`, prints a `<skill_relevance>` block into context |

### Wiring the MCP server

Claude Code:

```bash
claude mcp add --scope user skill-router -- skill-router-mcp
```

Codex (`~/.codex/config.toml`):

```toml
[mcp_servers.skill-router]
command = "skill-router-mcp"
```

If you installed with `uv sync` instead of `uv tool install`, point `command` at
`<repo>/.venv/bin/skill-router-mcp`. `route_skill` returns the same JSON as `route --json`
plus a `suggestion` field holding the `<skill_relevance>` block.

### The hook costs tokens on every prompt

The hook adds two Jev requests and a suggestion block to every message you send, whether or
not a skill is relevant. Prefer the MCP tool, which the agent calls only when it wants a route.
If you do wire the hook, this is the entry:

```json
"UserPromptSubmit": [
  { "hooks": [ { "type": "command", "command": "<repo>/.venv/bin/skill-router-hook", "timeout": 20 } ] }
]
```

## Key resolution

`setup` verifies the key against the API before storing it. At runtime the key is read from
`TYPESAFE_API_KEY`, then the macOS Keychain item `typesafe-api-key`, then the 0600 file
`~/.config/skill-router/api_key` (the store used on Linux).

## Config

`~/.config/skill-router/config.toml`, or the path in `SKILL_ROUTER_CONFIG`. Every key is
optional. Unknown keys and out-of-range values are rejected at load with the formula in the
error text.

```toml
model = "jev-latest"
shortlist = 3
gate_floor = 0.12          # below: none_needed without a second request
gate_threshold = 0.30      # above: the request needs a skill; below: gray zone
fits_threshold = 0.30      # required fit when the gate says a skill is needed
gray_fits_threshold = 0.75 # required fit in the gray zone
timeout = 30.0             # per request, CLI and MCP
hook_timeout = 6.0         # per request inside the prompt hook, no retries; at most hook_deadline
hook_deadline = 15.0       # end to end; the hook prints nothing and exits 0 past this; max 18,
                           # because the settings.json hook entry runs with timeout 20
intent_chars = 4000        # inputs are truncated to these before they are sent
context_chars = 4000
wide_description_chars = 320     # description chars per skill in the wide ranking
rerank_description_chars = 1500  # description chars per shortlisted skill in the rerank
excerpt_chars = 700              # body chars per shortlisted skill in the rerank
choice_chars = 90000       # bound on one Choice question; must hold two wide entries and the
                           # whole shortlist with excerpts
extra_roots = ["~/my-skills"]
disabled_harnesses = ["codex"]
exclude = ["some-skill-name"]
```

## Tests

```bash
uv run pytest
```

## Checklist before relying on it

- [ ] `skill-router roster` lists the skills you expect, with the harness you expect
- [ ] `skill-router route "<a request you know the skill for>"` names that skill
- [ ] `skill-router route "thanks, looks good"` returns `none_needed`
- [ ] The hook is not wired unless you accept the per-prompt cost

## Next step

Wire `skill-router-mcp` into your agent's MCP config so it can call `route_skill` when it is
unsure which skill to load.
