from __future__ import annotations

import argparse
import getpass
import json
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from typesafe_sdk import (
    TypeSafeAuthenticationError,
    TypeSafeError,
    TypeSafePermissionDeniedError,
)

from . import client as client_mod
from .client import KeyStoreError, MissingKeyError
from .config import Config, ConfigError, config_path
from .roster import to_json
from .router import MalformedResponse, suggestion_block
from .service import roster, route_intent


def cmd_roster(args) -> int:
    skills = roster(Config.load(), Path.cwd())
    if args.json:
        print(to_json(skills))
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
    print(f"{r.outcome}: {r.winner or '-'}")
    detail = [r.reason]
    if r.no_match is not None:
        detail.append(f"no-match {r.no_match:.2f}")
    print(f"  {'; '.join(detail)}  model={r.model}  tokens={r.usage.get('input_tokens')}")
    for c in r.ranked[:8]:
        rerank = f"rerank {c.rerank:.2f}" if c.rerank is not None else ""
        print(f"  direct {c.direct:.2f}  {c.name:<40} {rerank}")
    return 0


def cmd_setup(args) -> int:
    key = args.key
    if not key and shutil.which("osascript"):
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
    elif not key:
        key = getpass.getpass("TypeSafe API key: ").strip()
    if not key:
        print("empty key", file=sys.stderr)
        return 1
    cfg = Config.load()
    try:
        names = client_mod.verify_key(key, cfg.model, cfg.timeout)
    except (TypeSafeAuthenticationError, TypeSafePermissionDeniedError) as exc:
        print(f"key rejected, nothing stored: {exc}", file=sys.stderr)
        return 1
    where = client_mod.store_key(key)
    print(f"key verified and stored at {where}; models: {', '.join(names)}")
    print(f"config: {config_path()} ({'present' if config_path().is_file() else 'defaults'})")
    return 0


def main(argv=None) -> int:
    try:
        return _main(argv)
    except (MissingKeyError, ConfigError, KeyStoreError) as exc:
        print(exc, file=sys.stderr)
        return 2
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except OSError:
            pass
        return 0
    except (TypeSafeError, MalformedResponse) as exc:
        print(f"typesafe: {exc}", file=sys.stderr)
        return 3
    except OSError as exc:
        print(f"skill-router: {exc}", file=sys.stderr)
        return 2


def _main(argv=None) -> int:
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
