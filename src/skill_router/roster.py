"""Discover every SKILL.md the agent harnesses on this machine can load."""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator

import yaml

BODY_CHARS = 1600


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


def _skill_dirs(root: Path) -> Iterator[Path]:
    if not root.is_dir():
        return
    for md in sorted(root.glob("*/SKILL.md")):
        yield md


def _plugin_skill_dirs(cache: Path) -> Iterator[tuple[str, Path]]:
    if not cache.is_dir():
        return
    for md in sorted(cache.glob("*/*/*/skills/*/SKILL.md")):
        plugin = md.parents[2].parent.name
        yield plugin, md


def harness_sources(home: Path, cwd: Path | None) -> list[tuple[str, str | None, Path]]:
    sources: list[tuple[str, str | None, Path]] = [
        ("claude-code", None, home / ".claude" / "skills"),
        ("codex", None, home / ".codex" / "skills"),
        ("agents", None, home / ".agents" / "skills"),
    ]
    if cwd:
        for ancestor in [cwd, *cwd.parents]:
            project = ancestor / ".claude" / "skills"
            if project.is_dir():
                sources.append(("project", None, project))
                break
    return sources


def discover(home: Path | None = None, cwd: Path | None = None) -> list[Skill]:
    home = home or Path.home()
    seen: dict[str, Skill] = {}

    def add(name: str, harness: str, md: Path) -> None:
        if name in seen:
            return
        fields, body = parse_skill_md(md.read_text(encoding="utf-8", errors="replace"))
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

    for harness, _, root in harness_sources(home, cwd):
        for md in _skill_dirs(root):
            add(md.parent.name, harness, md)
    for plugin, md in _plugin_skill_dirs(home / ".claude" / "plugins" / "cache"):
        add(f"{plugin}:{md.parent.name}", "claude-code-plugin", md)
    return sorted(seen.values(), key=lambda s: s.name)


def cache_path() -> Path:
    override = os.environ.get("SKILL_ROUTER_CACHE")
    if override:
        return Path(override)
    return Path.home() / ".cache" / "skill-router" / "roster.json"


def _fingerprint(skills: list[Skill]) -> str:
    return json.dumps([(s.path, os.path.getmtime(s.path)) for s in skills])


def load(home: Path | None = None, cwd: Path | None = None, refresh: bool = False) -> list[Skill]:
    skills = discover(home, cwd)
    return skills


def to_json(skills: list[Skill]) -> str:
    return json.dumps([asdict(s) for s in skills], indent=1)
