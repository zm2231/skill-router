from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from . import client as client_mod
from . import roster as roster_mod
from .config import Config, config_path
from .router import suggestion_block
from .service import roster, route_intent


def cmd_roster(args) -> int:
    skills = roster(Config.load(), Path.cwd())
    if args.json:
        print(roster_mod.to_json(skills))
        return 0
    for s in skills:
        print(f"{s.name:<44} {s.harness:<20} {s.description[:70]}")
    print(f"\n{len(skills)} skills", file=sys.stderr)
    return 0


def cmd_route(args) -> int:
    r = route_intent(args.intent, args.context or "", Path.cwd())
    if args.json:
        print(json.dumps(asdict(r), indent=1))
        return 0
    if args.block:
        block = suggestion_block(r)
        if block:
            print(block)
        return 0
    print(f"intent: {r.intent}")
    print(f"gate {r.gate:.2f}  {r.reason}  model={r.model}  tokens={r.usage.get('input_tokens')}")
    print(f"{r.outcome}: {r.winner or '-'}")
    for c in r.ranked[:6]:
        fits = f"fits {c.fits:.2f}" if c.fits is not None else ""
        print(f"  {c.probability:.3f}  {c.name:<40} {fits}")
    return 0


def cmd_setup(args) -> int:
    key = args.key
    if not key:
        try:
            out = subprocess.run(
                ["osascript",
                 "-e", 'Tell application "System Events" to display dialog "Enter your TypeSafe (Jev) API key. It is stored in the macOS Keychain (service: typesafe-api-key):" with title "skill-router setup" default answer "" with hidden answer buttons {"OK"} default button "OK"',
                 "-e", "text returned of result"],
                capture_output=True, text=True, check=True,
            )
        except subprocess.CalledProcessError:
            print("cancelled", file=sys.stderr)
            return 1
        key = out.stdout.strip()
    if not key:
        print("empty key", file=sys.stderr)
        return 1
    client_mod.store_key(key)
    cfg = Config.load()
    with client_mod.make_client(cfg.model, cfg.timeout) as client:
        names = [m.name for m in client.models.list().models]
    print(f"key stored in Keychain ({client_mod.KEYCHAIN_SERVICE}); models: {', '.join(names)}")
    print(f"config: {config_path()} ({'present' if config_path().is_file() else 'defaults'})")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="skill-router")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("roster", help="list every skill the harnesses on this machine can load")
    r.add_argument("--json", action="store_true")
    r.set_defaults(fn=cmd_roster)

    q = sub.add_parser("route", help="pick at most one skill for an intent")
    q.add_argument("intent")
    q.add_argument("--context", default="")
    q.add_argument("--json", action="store_true")
    q.add_argument("--block", action="store_true", help="print only the <skill_relevance> block")
    q.set_defaults(fn=cmd_route)

    s = sub.add_parser("setup", help="store the TypeSafe API key in the Keychain and verify it")
    s.add_argument("--key")
    s.set_defaults(fn=cmd_setup)

    args = p.parse_args(argv)
    return args.fn(args)
