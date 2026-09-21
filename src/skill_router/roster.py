"""Discover every SKILL.md the agent harnesses on this machine can load."""
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

BODY_CHARS = 1600
NAME_CHARS = 128


def json_len(text: str) -> int:
    """Chars the text occupies inside a JSON string, quotes excluded."""
    return len(json.dumps(text)) - 2


def fit_json(text: str, limit: int) -> str:
    """The longest prefix of text whose JSON-encoded form fits in limit chars."""
    text = text[:limit]
    while text and json_len(text) > limit:
        text = text[: len(text) - max(1, (json_len(text) - limit) // 12)]
    return text


@dataclass(frozen=True)
class Skill:
    name: str
    harness: str
    path: str
    description: str
    body: str

    @property
    def invoke(self) -> str:
        return self.name


def parse_skill_md(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    close = text.find("\n---", 3)
    if close == -1:
        return {}, text
    raw = text[3:close]
    body = text[close + 4:].strip()
    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError:
        loaded = None
    if not isinstance(loaded, dict):
        return {}, body
    fields = {str(k): " ".join(str(v).split()) for k, v in loaded.items() if v is not None}
    return fields, body


DEFAULT_ROOTS = {
    "claude-code": "~/.claude/skills",
    "codex": "~/.codex/skills",
    "agents": "~/.agents/skills",
}
DEFAULT_PLUGIN_CACHE = "~/.claude/plugins/cache"
DEFAULT_PROJECT_SKILLS = ".claude/skills"


def check_source_dir(path: str | Path) -> Path | None:
    """The expanded directory a skill source points at; None when it is off or absent.
    A path that exists but is not a directory is a misconfiguration, never an empty source."""
    if not path:
        return None
    expanded = Path(path).expanduser()
    if not expanded.exists():
        return None
    if not expanded.is_dir():
        raise NotADirectoryError(f"{expanded} is not a directory")
    return expanded


def _skill_files(root: Path) -> Iterator[Path]:
    if check_source_dir(root) is None:
        return
    yield from sorted(root.rglob("SKILL.md"))


def _plugin_skill_files(cache: Path) -> Iterator[tuple[str, Path]]:
    if check_source_dir(cache) is None:
        return
    for md in sorted(cache.glob("*/*/*/skills/*/SKILL.md")):
        plugin = md.parents[2].parent.name
        yield plugin, md


def harness_sources(
    roots: dict[str, str],
    cwd: Path | None,
    project_skills: str,
    disabled_harnesses: list[str],
) -> list[tuple[str, Path]]:
    """Named roots in scan order: the project's own skills first, then every configured root."""
    disabled = set(disabled_harnesses)
    sources: list[tuple[str, Path]] = []
    if cwd and project_skills and "project" not in disabled:
        for ancestor in [cwd, *cwd.parents]:
            project = check_source_dir(ancestor / project_skills)
            if project is not None:
                sources.append(("project", project))
                break
    sources += [(name, Path(path).expanduser()) for name, path in roots.items() if name not in disabled and path]
    return sources


def discover(
    cwd: Path | None = None,
    roots: dict[str, str] | None = None,
    plugin_cache: str | None = DEFAULT_PLUGIN_CACHE,
    project_skills: str = DEFAULT_PROJECT_SKILLS,
    disabled_harnesses: list[str] | None = None,
    exclude: list[str] | None = None,
) -> list[Skill]:
    roots = DEFAULT_ROOTS | (roots or {})
    disabled = list(disabled_harnesses or [])
    excluded = set(exclude or [])
    seen: dict[str, Skill] = {}

    def add(name: str, harness: str, md: Path) -> None:
        if name in seen or name in excluded or json_len(name) > NAME_CHARS:
            return
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        fields, body = parse_skill_md(text)
        description = fields.get("description", "")
        if not description:
            description = " ".join(re.sub(r"^#+\s*", "", body[:400], flags=re.MULTILINE).split())[:200]
        seen[name] = Skill(
            name=name,
            harness=harness,
            path=str(md),
            description=description,
            body=body[:BODY_CHARS],
        )

    for harness, root in harness_sources(roots, cwd, project_skills, disabled):
        for md in _skill_files(root):
            add(md.parent.name, harness, md)
    if plugin_cache and "claude-code-plugin" not in disabled:
        for plugin, md in _plugin_skill_files(Path(plugin_cache).expanduser()):
            add(f"{plugin}:{md.parent.name}", "claude-code-plugin", md)
    return sorted(seen.values(), key=lambda s: s.name)


def to_json(skills: list[Skill]) -> str:
    return json.dumps([asdict(s) for s in skills], indent=1)
