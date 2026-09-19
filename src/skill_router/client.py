"""TypeSafe client construction. The API key comes from the environment, the macOS Keychain,
or a 0600 file, in that order; it is never written anywhere else."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from typesafe_sdk import RetryPolicy, TypeSafeClient

KEYCHAIN_SERVICE = "typesafe-api-key"


class MissingKeyError(RuntimeError):
    pass


class KeyStoreError(RuntimeError):
    pass


def key_file() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / "skill-router" / "api_key"


def keychain_available() -> bool:
    return sys.platform == "darwin" and shutil.which("security") is not None


def keychain_key() -> str | None:
    if not keychain_available():
        return None
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError:
        return None
    return out.stdout.strip() or None


def file_key(path: Path | None = None) -> str | None:
    path = path or key_file()
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def api_key() -> str:
    key = os.environ.get("TYPESAFE_API_KEY", "").strip() or keychain_key() or file_key()
    if not key:
        raise MissingKeyError("no TypeSafe API key: run `skill-router setup` or set TYPESAFE_API_KEY")
    return key


def store_key(key: str, path: Path | None = None) -> str:
    """Store the key and return where. Keychain on macOS, else a 0600 file written atomically.
    The previous value survives any failure."""
    if path is None and keychain_available():
        try:
            subprocess.run(
                ["security", "add-generic-password", "-s", KEYCHAIN_SERVICE,
                 "-a", os.environ.get("USER", "skill-router"), "-w", key, "-U"],
                check=True, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise KeyStoreError(f"keychain write failed: {exc.stderr.strip()}") from exc
        return f"keychain:{KEYCHAIN_SERVICE}"
    path = path or key_file()
    tmp: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".api_key.")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(key + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError as exc:
        if tmp is not None:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        raise KeyStoreError(f"could not write {path}: {exc}") from exc
    return str(path)


def make_client(model: str, timeout: float, retry: RetryPolicy | None = None, key: str | None = None) -> TypeSafeClient:
    return TypeSafeClient(api_key=key or api_key(), model=model, timeout=timeout, retry=retry)


def verify_key(key: str, model: str, timeout: float) -> list[str]:
    """Names of the models the key can use; raises the SDK's error if the key is rejected."""
    with make_client(model, timeout, RetryPolicy(max_retries=0), key=key) as client:
        return [m.name for m in client.models.list().models]
