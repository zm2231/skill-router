"""One entry point the CLI, MCP server, and hook all share."""
from __future__ import annotations

from pathlib import Path

from .client import make_client
from .config import Config
from .roster import Skill, discover
from .router import Route, route


def roster(cfg: Config, cwd: Path | None) -> list[Skill]:
    return discover(
        cwd=cwd,
        extra_roots=cfg.extra_roots,
        disabled_harnesses=cfg.disabled_harnesses,
        exclude=cfg.exclude,
    )


def route_intent(
    intent: str,
    context: str = "",
    cwd: Path | None = None,
    cfg: Config | None = None,
    timeout: float | None = None,
) -> Route:
    cfg = cfg or Config.load()
    skills = roster(cfg, cwd)
    with make_client(cfg.model, timeout or cfg.timeout) as client:
        return route(client, cfg, skills, intent, context)
