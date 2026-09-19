"""Claude Code UserPromptSubmit hook: read the prompt on stdin, print a suggestion block on stdout."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .config import Config
from .router import suggestion_block
from .service import route_intent

MIN_PROMPT_CHARS = 12


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0
    prompt = (payload.get("prompt") or "").strip()
    if len(prompt) < MIN_PROMPT_CHARS or prompt.startswith("/"):
        return 0
    cwd = payload.get("cwd")
    try:
        cfg = Config.load()
        r = route_intent(prompt, "", Path(cwd) if cwd else None, cfg, timeout=cfg.hook_timeout)
    except BaseException as exc:  # a hook must never block the prompt, whatever failed
        if isinstance(exc, KeyboardInterrupt):
            raise
        print(f"skill-router: {exc}", file=sys.stderr)
        return 0
    block = suggestion_block(r)
    if block:
        print(block)
    return 0


if __name__ == "__main__":
    sys.exit(main())
