"""Runtime configuration: harness roots, thresholds, model. Read from a TOML file, overridable by env."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


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
    wide_chunk_chars: int = 90_000
    extra_roots: list[str] = field(default_factory=list)
    disabled_harnesses: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)

    @classmethod
    def load(cls) -> "Config":
        path = config_path()
        data: dict = {}
        if path.is_file():
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        cfg = cls(**known)
        env_model = os.environ.get("TYPESAFE_DEFAULT_MODEL")
        if env_model:
            cfg.model = env_model
        return cfg
