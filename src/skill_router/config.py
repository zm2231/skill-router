"""Runtime configuration: harness roots, thresholds, model. Read from a TOML file, overridable by env."""
from __future__ import annotations

import math
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .roster import DEFAULT_PLUGIN_CACHE, DEFAULT_PROJECT_SKILLS, check_source_dir

HOOK_CEILING = 18.0
HOOK_MIN_ROUNDS = 3

INTEGER_FIELDS = (
    "shard_size", "parallel", "shortlist_cap", "shortlist_min",
    "wide_description_chars", "rerank_description_chars", "excerpt_chars", "intent_chars", "context_chars",
)
PROBABILITY_FIELDS = ("direct_floor", "accept_probability", "accept_margin", "need_high", "need_low")
DURATION_FIELDS = ("timeout", "hook_timeout", "hook_deadline")


class ConfigError(ValueError):
    pass


def config_path() -> Path:
    override = os.environ.get("SKILL_ROUTER_CONFIG")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / "skill-router" / "config.toml"


@dataclass
class Config:
    model: str = "jev-latest"
    shard_size: int = 50
    parallel: int = 4
    direct_floor: float = 0.20
    shortlist_cap: int = 6
    shortlist_min: int = 3
    accept_probability: float = 0.55
    accept_margin: float = 0.15
    need_high: float = 0.70
    need_low: float = 0.30
    wide_description_chars: int = 320
    rerank_description_chars: int = 1500
    excerpt_chars: int = 700
    timeout: float = 30.0
    hook_timeout: float = 5.0
    hook_deadline: float = 15.0
    intent_chars: int = 4_000
    context_chars: int = 4_000
    roots: dict[str, str] = field(default_factory=dict)
    plugin_cache: str = DEFAULT_PLUGIN_CACHE
    project_skills: str = DEFAULT_PROJECT_SKILLS
    disabled_harnesses: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        problems = self._type_problems()
        if problems:
            raise ConfigError("; ".join(problems))
        for name in INTEGER_FIELDS:
            if getattr(self, name) < 1:
                problems.append(f"{name} must be at least 1")
        for name in PROBABILITY_FIELDS:
            if not 0.0 <= getattr(self, name) <= 1.0:
                problems.append(f"{name} must be between 0 and 1")
        if self.shortlist_min > self.shortlist_cap:
            problems.append("shortlist_min must not exceed shortlist_cap")
        if self.need_low > self.need_high:
            problems.append("need_low must not exceed need_high")
        for name in DURATION_FIELDS:
            if getattr(self, name) <= 0:
                problems.append(f"{name} must be positive")
        if self.hook_deadline > HOOK_CEILING:
            problems.append(f"hook_deadline must not exceed {HOOK_CEILING:g}; the installed hook is killed at 20s")
        if HOOK_MIN_ROUNDS * self.hook_timeout > self.hook_deadline:
            problems.append(f"{HOOK_MIN_ROUNDS} * hook_timeout must not exceed hook_deadline: a route is at least "
                            f"{HOOK_MIN_ROUNDS} sequential requests, and larger rosters shrink each request's share")
        for name, path in [*self.roots.items(), ("plugin_cache", self.plugin_cache)]:
            try:
                check_source_dir(path)
            except NotADirectoryError as exc:
                problems.append(f"{name}: {exc}")
        if problems:
            raise ConfigError("; ".join(problems))

    def _type_problems(self) -> list[str]:
        problems: list[str] = []
        if not isinstance(self.model, str) or not self.model.strip():
            problems.append("model must be a non-empty string")
        for name in ("disabled_harnesses", "exclude"):
            v = getattr(self, name)
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                problems.append(f"{name} must be a list of strings")
        if not isinstance(self.roots, dict) or not all(
            isinstance(k, str) and k and isinstance(v, str) for k, v in self.roots.items()
        ):
            problems.append("roots must be a table of name = \"directory\"")
        for name in ("plugin_cache", "project_skills"):
            if not isinstance(getattr(self, name), str):
                problems.append(f"{name} must be a string")
        for name in INTEGER_FIELDS:
            if isinstance(getattr(self, name), bool) or not isinstance(getattr(self, name), int):
                problems.append(f"{name} must be an integer")
        for name in PROBABILITY_FIELDS + DURATION_FIELDS:
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                problems.append(f"{name} must be a finite number")
        return problems

    @classmethod
    def load(cls) -> Config:
        path = config_path()
        data: dict = {}
        if path.is_file():
            try:
                data = tomllib.loads(path.read_text(encoding="utf-8"))
            except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as exc:
                raise ConfigError(f"{path}: {exc}") from exc
        unknown = sorted(k for k in data if k not in cls.__dataclass_fields__)
        if unknown:
            raise ConfigError(f"{path}: unknown keys {', '.join(unknown)}")
        env_model = os.environ.get("TYPESAFE_DEFAULT_MODEL")
        if env_model:
            data["model"] = env_model
        try:
            return cls(**data)
        except ConfigError as exc:
            raise ConfigError(f"{path}: {exc}") from exc
        except TypeError as exc:
            raise ConfigError(f"{path}: {exc}") from exc
