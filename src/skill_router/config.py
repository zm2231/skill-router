"""Runtime configuration: harness roots, thresholds, model. Read from a TOML file, overridable by env."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


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
    excerpt_chars: int = 700
    timeout: float = 30.0
    hook_timeout: float = 6.0
    hook_deadline: float = 15.0
    intent_chars: int = 4_000
    context_chars: int = 4_000
    wide_chunk_chars: int = 90_000
    extra_roots: list[str] = field(default_factory=list)
    disabled_harnesses: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        problems = []
        if self.shortlist < 1:
            problems.append("shortlist must be at least 1")
        for name in ("gate_floor", "gate_threshold", "fits_threshold", "gray_fits_threshold"):
            v = getattr(self, name)
            if not 0.0 <= v <= 1.0:
                problems.append(f"{name} must be between 0 and 1")
        if self.gate_floor > self.gate_threshold:
            problems.append("gate_floor must not exceed gate_threshold")
        for name in ("timeout", "hook_timeout", "hook_deadline"):
            if getattr(self, name) <= 0:
                problems.append(f"{name} must be positive")
        for name in ("wide_description_chars", "excerpt_chars", "intent_chars", "context_chars", "wide_chunk_chars"):
            if getattr(self, name) < 1:
                problems.append(f"{name} must be at least 1")
        if not self.model.strip():
            problems.append("model must not be empty")
        if problems:
            raise ConfigError("; ".join(problems))

    @classmethod
    def load(cls) -> "Config":
        path = config_path()
        data: dict = {}
        if path.is_file():
            try:
                data = tomllib.loads(path.read_text(encoding="utf-8"))
            except tomllib.TOMLDecodeError as exc:
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
