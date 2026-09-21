# skill-router

Given what a user just asked for, name the one installed skill that should handle it, or say
whether the request needed a skill at all. It reads every `SKILL.md` the agent harnesses on this
machine can load (Claude Code, Codex, `~/.agents`, plugins, the current project) and asks
TypeSafe's Jev, a model that returns calibrated probabilities instead of text, to judge each one.

## Quick path

You need Python 3.13+, [uv](https://docs.astral.sh/uv/), and a TypeSafe API key from
[typesafe.ai](https://typesafe.ai).

```bash
uv tool install git+https://github.com/zm2231/skill-router   # or: git clone + uv sync, then prefix each command with `uv run`
skill-router setup                     # verifies the key, then stores it (Keychain on macOS, 0600 file elsewhere)
skill-router roster                    # every skill it would route over
skill-router route "turn this podcast into a labeled transcript"
```

The last line prints the outcome, then every skill's probability of being directly applicable,
with the rerank probability for the ones that reached the second stage:

```
intent: turn this podcast into a labeled transcript
matched: <skill-name>
  rerank verified; no-match 0.02  model=jev-1.13.0  tokens=31881
  direct 1.00  <skill-name>                             rerank 0.95
  direct 0.85  <runner-up>                              rerank 0.00
  direct 0.26  <third>                                  rerank 0.03
  direct 0.13  <fourth>
```

Add `--json` for the full record, `--block` for the `<skill_relevance>` block an agent would read.

## How a route is decided

| Stage | Question | Rule |
|-------|----------|------|
| 1. Score | One Score per skill, judged on its own: unrelated / adjacent / direct. Shards of `shard_size` run concurrently | Shortlist every skill with `P(direct) ≥ direct_floor`, capped at `shortlist_cap`; the top `shortlist_min` anyway when none clears it |
| 2. Rerank | One Choice over the shortlist's full description and body excerpt, plus `none-of-these` | `matched` when the top skill has `P ≥ accept_probability` and beats `none-of-these` by `accept_margin` |
| 3. Need | Only when nothing verified: one yes/no question, does this request materially require a specialized procedure at all, whether or not one is installed | `none_needed` at `P ≤ need_low`; `likely_missing` at `P ≥ need_high`; `uncertain` between, or whenever the shortlist cap cut candidates |

Four outcomes: `matched` names one skill. `none_needed` means ordinary reasoning and tools
suffice. `likely_missing` means a skill would help and none installed fits, which is the signal
to go looking for one. `uncertain` is exactly that, and is never turned into advice.

Skills are never ranked against each other in stage 1, so a request that needs nothing cannot
produce a confident-looking leader, and rosters of any size are scored completely rather than
in a tournament. Cost is one Score question per skill: roughly 30K Jev input tokens for a
150-skill roster, about $0.001 at Jev's list price.

## Where skills come from

Every root is a directory searched recursively for `SKILL.md`. The defaults:

| Harness | Root | Name |
|---------|------|------|
| project | nearest `.claude/skills/` walking up from `cwd` | directory name |
| claude-code | `~/.claude/skills/` | directory name |
| codex | `~/.codex/skills/` | directory name |
| agents | `~/.agents/skills/` | directory name |
| claude-code-plugin | `~/.claude/plugins/cache/*/*/*/skills/` | `plugin:skill` |

Add your own roots, or repoint the defaults, in the config's `[roots]` table; the harness name
is whatever key you give it. Drop a default with `disabled_harnesses`, or set its path to `""`.
`project_skills` and `plugin_cache` are the two special cases and can each be set to `""`.

```toml
[roots]
pi = "/path/to/pi/skills"          # new root, harness "pi"
codex = "~/somewhere/else/skills"  # repointed default
```

The skill's name is the directory holding `SKILL.md`, not the frontmatter `name:`. Only the
frontmatter `description` is used for scoring; a skill without one gets the first 200 chars of
its body. First occurrence of a name wins, in the order above.

## Surfaces

| Surface | Command | Notes |
|---------|---------|-------|
| CLI | `skill-router route "<intent>" [--context ...] [--json \| --block]` | Exit 2: missing key or bad config. Exit 3: TypeSafe unreachable or rejected the request. One-line stderr message either way |
| MCP (stdio) | `skill-router-mcp` | `route_skill(intent, context, cwd)` returns the full record including the outcome, every skill's `direct` and `rerank` probabilities, `no_match`, and `need`; `list_skills(cwd)` |
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

The hook scores the whole roster on every message you send. It injects a block only for a
verified match and never advice to install something, but the Jev cost is paid either way.
Prefer the MCP tool, which the agent calls only when it wants a route.
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
optional. Unknown keys and out-of-range values are rejected at load.

```toml
model = "jev-latest"
shard_size = 50            # Score questions per request; shards run concurrently
parallel = 4               # concurrent shard requests
direct_floor = 0.20        # P(direct) a skill needs to reach the rerank
shortlist_cap = 6          # most skills reranked; more over the floor marks the route truncated
shortlist_min = 3          # reranked anyway when nothing clears the floor
accept_probability = 0.55  # rerank probability the winner needs
accept_margin = 0.15       # and its lead over none-of-these
need_high = 0.70           # need probability at or above which nothing-verified becomes likely_missing
need_low = 0.30            # at or below which it becomes none_needed; between is uncertain
timeout = 30.0             # per request, CLI and MCP
hook_timeout = 5.0         # per request inside the prompt hook, no retries; 3 * hook_timeout <= hook_deadline
hook_deadline = 15.0       # end to end; the hook prints nothing and exits 0 past this; max 18,
                           # because the settings.json hook entry runs with timeout 20
intent_chars = 4000        # inputs are truncated to these before they are sent
context_chars = 4000
wide_description_chars = 320     # description chars per skill in the Score stage
rerank_description_chars = 1500  # description chars per shortlisted skill in the rerank
excerpt_chars = 700              # body chars per shortlisted skill in the rerank
plugin_cache = "~/.claude/plugins/cache"  # "" to skip Claude Code plugins
project_skills = ".claude/skills"         # walked up from cwd; "" to skip
disabled_harnesses = ["codex"]            # any harness name, including project and claude-code-plugin
exclude = ["some-skill-name"]

[roots]                                   # merged over the defaults; see "Where skills come from"
pi = "~/pi/skills"
```



## Tests

```bash
uv run pytest
```

## Checklist before relying on it

- [ ] `skill-router roster` lists the skills you expect, with the harness you expect
- [ ] `skill-router route "<a request you know the skill for>"` names that skill
- [ ] `skill-router route "thanks, looks good"` returns `none_needed`
- [ ] `skill-router route "<something no installed skill does>"` returns `likely_missing`
- [ ] The hook is not wired unless you accept the per-prompt cost

## Next step

Wire `skill-router-mcp` into your agent's MCP config so it can call `route_skill` when it is
unsure which skill to load.
