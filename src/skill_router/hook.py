"""Claude Code UserPromptSubmit hook: read the prompt on stdin, print a suggestion block on stdout.
Whatever happens, it exits 0 inside its deadline and prints nothing it is not sure of."""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

from .config import Config
from .router import suggestion_block
from .service import route_intent

MIN_PROMPT_CHARS = 12


def _route_in_thread(prompt: str, cwd: str | None, cfg: Config, box: dict) -> None:
    try:
        box["route"] = route_intent(prompt, "", Path(cwd) if cwd else None, cfg, deadline=cfg.hook_deadline)
    except BaseException as exc:
        box["error"] = exc


def run(payload: object, cfg: Config | None = None) -> str:
    """The block to print for this payload, or an empty string. Never raises."""
    if not isinstance(payload, dict) or not isinstance(payload.get("prompt"), str):
        return ""
    prompt = payload["prompt"].strip()
    if len(prompt) < MIN_PROMPT_CHARS or prompt.startswith("/"):
        return ""
    cwd = payload.get("cwd")
    if not isinstance(cwd, str):
        cwd = None
    try:
        cfg = cfg or Config.load()
    except BaseException as exc:
        print(f"skill-router: {exc}", file=sys.stderr)
        return ""
    box: dict = {}
    worker = threading.Thread(target=_route_in_thread, args=(prompt, cwd, cfg, box), daemon=True)
    worker.start()
    worker.join(cfg.hook_deadline)
    if worker.is_alive():
        print(f"skill-router: no answer within {cfg.hook_deadline:.0f}s", file=sys.stderr)
        return ""
    if "error" in box:
        print(f"skill-router: {box['error']}", file=sys.stderr)
        return ""
    return suggestion_block(box["route"])


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError, ValueError):
        return 0
    try:
        block = run(payload)
        if block:
            print(block)
    except BrokenPipeError:
        pass
    except BaseException as exc:
        print(f"skill-router: {exc!r}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
