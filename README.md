# skill-router

Routes an agent's intent to the one installed skill that fits, across harnesses, using
TypeSafe's Jev (a System One model that returns calibrated probabilities instead of text).

Two requests per intent, following TypeSafe's skill-suggestion cookbook:

1. Rank every skill on the roster with a Choice question, and gate with three Nouls that ask
   whether the request needs a skill at all.
2. Rerank the top three with each skill's full description and opening body, and verify each
   with an absolute "does this skill do this" Noul. Any shortlist whose best fit is under the
   threshold returns nothing.

## Setup

```bash
uv sync
uv run skill-router setup          # stores the TypeSafe key in the macOS Keychain
uv run skill-router roster         # what would be routed over
uv run skill-router route "turn this podcast into a labeled transcript"
```

The key is read from `TYPESAFE_API_KEY` first, then the Keychain item `typesafe-api-key`.

## Roster discovery

`~/.claude/skills`, `~/.claude/plugins/cache/**/skills` (as `plugin:skill`), `~/.codex/skills`,
`~/.agents/skills`, and the nearest project `.claude/skills`. First occurrence of a name wins.
