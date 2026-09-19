"""TypeSafe client construction; the API key lives in the macOS Keychain or the environment."""
from __future__ import annotations

import os
import subprocess

from typesafe_sdk import TypeSafeClient

KEYCHAIN_SERVICE = "typesafe-api-key"
DEFAULT_MODEL = "jev-latest"


def keychain_key() -> str | None:
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return out.stdout.strip() or None


def api_key() -> str:
    key = os.environ.get("TYPESAFE_API_KEY", "").strip() or keychain_key()
    if not key:
        raise SystemExit(
            "no TypeSafe API key: run `skill-router setup` or set TYPESAFE_API_KEY"
        )
    return key


def store_key(key: str) -> None:
    subprocess.run(
        ["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE],
        capture_output=True,
    )
    subprocess.run(
        ["security", "add-generic-password", "-s", KEYCHAIN_SERVICE,
         "-a", os.environ.get("USER", "skill-router"), "-w", key, "-U"],
        check=True, capture_output=True,
    )


def make_client(timeout: float = 30.0) -> TypeSafeClient:
    return TypeSafeClient(
        api_key=api_key(),
        model=os.environ.get("TYPESAFE_DEFAULT_MODEL", DEFAULT_MODEL),
        timeout=timeout,
    )
