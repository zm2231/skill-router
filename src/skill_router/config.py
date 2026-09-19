"""Runtime configuration: harness roots, thresholds, model. Read from a TOML file, overridable by env."""
from __future__ import annotations

import json
import math
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .prompts import CHOICE_INSTRUCTIONS, NO_MATCH, NO_MATCH_CRITERIA, RERANK_INSTRUCTIONS
from .roster import BODY_CHARS, NAME_CHARS

HOOK_CEILING = 18.0
WIDE_OVERHEAD = len(json.dumps({"type": "choice", "instructions": CHOICE_INSTRUCTIONS, "criteria": {}}))
RERANK_OVERHEAD = 2 + len(json.dumps(
    {"type": "choice", "instructions": RERANK_INSTRUCTIONS, "criteria": {NO_MATCH: NO_MATCH_CRITERIA}}
))


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
    shortlist: int = 3
    gate_floor: float = 0.12
    gate_threshold: float = 0.30
    fits_threshold: float = 0.30
    gray_fits_threshold: float = 0.75
    wide_description_chars: int = 320
    rerank_description_chars: int = 1500
    excerpt_chars: int = 700
    timeout: float = 30.0
    hook_timeout: float = 6.0
    hook_deadline: float = 15.0
    intent_chars: int = 4_000
    context_chars: int = 4_000
    choice_chars: int = 90_000
    extra_roots: list[str] = field(default_factory=list)
    disabled_harnesses: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.validate()

    @property
    def max_entry_chars(self) -> int:
        """Serialized chars one roster entry can add to the wide Choice."""
        return NAME_CHARS + self.wide_description_chars + 8

    @property
    def wide_capacity(self) -> int:
        """Chars left for roster entries in one wide Choice after the fixed text."""
        return self.choice_chars - WIDE_OVERHEAD

    @property
    def max_rerank_chars(self) -> int:
        """Upper bound on the rerank Choice: every shortlisted entry plus the no-match option."""
        entry = NAME_CHARS + self.rerank_description_chars + min(self.excerpt_chars, BODY_CHARS) + 16
        return self.shortlist * entry + RERANK_OVERHEAD

    def validate(self) -> None:
        problems = self._type_problems()
        if problems:
            raise ConfigError("; ".join(problems))
        if self.shortlist < 1:
            problems.append("shortlist must be at least 1")
        for name in ("gate_floor", "gate_threshold", "fits_threshold", "gray_fits_threshold"):
            v = getattr(self, name)
            if not 0.0 <= v <= 1.0:
                problems.append(f"{name} must be between 0 and 1")
        if self.wide_capacity < 2 * self.max_entry_chars:
            problems.append(
                f"choice_chars must fit at least two entries: {WIDE_OVERHEAD} + 2 * ({NAME_CHARS} + wide_description_chars + 8)"
            )
        if self.max_rerank_chars > self.choice_chars:
            problems.append(
                f"shortlist * ({NAME_CHARS} + rerank_description_chars + min(excerpt_chars, {BODY_CHARS}) + 16) "
                f"+ {RERANK_OVERHEAD} must not exceed choice_chars"
            )
        if self.gate_floor > self.gate_threshold:
            problems.append("gate_floor must not exceed gate_threshold")
        for name in ("timeout", "hook_timeout", "hook_deadline"):
            if getattr(self, name) <= 0:
                problems.append(f"{name} must be positive")
        if self.hook_deadline > HOOK_CEILING:
            problems.append(f"hook_deadline must not exceed {HOOK_CEILING:g}; the installed hook is killed at 20s")
        if self.hook_timeout > self.hook_deadline:
            problems.append("hook_timeout must not exceed hook_deadline")
        for name in ("wide_description_chars", "rerank_description_chars", "excerpt_chars", "intent_chars", "context_chars", "choice_chars"):
            if getattr(self, name) < 1:
                problems.append(f"{name} must be at least 1")
        if problems:
            raise ConfigError("; ".join(problems))

    def _type_problems(self) -> list[str]:
        problems: list[str] = []
        if not isinstance(self.model, str) or not self.model.strip():
            problems.append("model must be a non-empty string")
        for name in ("extra_roots", "disabled_harnesses", "exclude"):
            v = getattr(self, name)
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                problems.append(f"{name} must be a list of strings")
        for name in ("shortlist", "wide_description_chars", "rerank_description_chars", "excerpt_chars", "intent_chars", "context_chars", "choice_chars"):
            if isinstance(getattr(self, name), bool) or not isinstance(getattr(self, name), int):
                problems.append(f"{name} must be an integer")
        for name in ("gate_floor", "gate_threshold", "fits_threshold", "gray_fits_threshold", "timeout", "hook_timeout", "hook_deadline"):
            v = getattr(self, name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                problems.append(f"{name} must be a finite number")
        return problems

    @classmethod
    def load(cls) -> "Config":
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
