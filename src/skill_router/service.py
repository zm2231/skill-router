"""One entry point the CLI, MCP server, and hook all share."""
from __future__ import annotations

import time
from pathlib import Path

from typesafe_sdk import RetryPolicy

from .client import make_client
from .config import Config
from .roster import Skill, discover
from .router import Route, request_rounds, route


def roster(cfg: Config, cwd: Path | None) -> list[Skill]:
    return discover(
        cwd=cwd,
        roots=cfg.roots,
        plugin_cache=cfg.plugin_cache,
        project_skills=cfg.project_skills,
        disabled_harnesses=cfg.disabled_harnesses,
        exclude=cfg.exclude,
    )


def route_intent(
    intent: str,
    context: str = "",
    cwd: Path | None = None,
    cfg: Config | None = None,
    deadline: float | None = None,
) -> Route:
    """With a deadline, every request gets an equal share of what is left after discovery, at
    most hook_timeout, with no retries, so the whole route fits inside it."""
    cfg = cfg or Config.load()
    started = time.monotonic()
    skills = roster(cfg, cwd)
    timeout, retry = cfg.timeout, None
    if deadline is not None:
        remaining = deadline - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError(f"discovering skills used the whole {deadline:g}s deadline")
        timeout = min(cfg.hook_timeout, remaining / request_rounds(cfg, len(skills)))
        retry = RetryPolicy(max_retries=0, timeout=timeout)
    with make_client(cfg.model, timeout, retry) as client:
        return route(client, cfg, skills, intent, context)
