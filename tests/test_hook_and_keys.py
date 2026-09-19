from __future__ import annotations

import io
import json
import os
import stat
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from skill_router import client as client_mod
from skill_router import hook
from skill_router.config import Config
from skill_router.router import MATCHED, Route


def fake_route(winner):
    return Route("x", 0.9, {}, [], winner, MATCHED, "ok")


class HookTests(unittest.TestCase):
    def test_short_or_slash_prompts_are_ignored(self):
        self.assertEqual(hook.run({"prompt": "hi"}), "")
        self.assertEqual(hook.run({"prompt": "/compact please now"}), "")
        self.assertEqual(hook.run(["not", "a", "dict"]), "")

    def test_success_prints_block(self):
        with mock.patch.object(hook, "route_intent", return_value=fake_route("undertone")):
            self.assertIn("undertone", hook.run({"prompt": "transcribe this podcast please"}, Config()))

    def test_route_error_is_swallowed(self):
        with mock.patch.object(hook, "route_intent", side_effect=SystemExit(3)):
            err = io.StringIO()
            with redirect_stderr(err):
                self.assertEqual(hook.run({"prompt": "transcribe this podcast please"}, Config()), "")
            self.assertIn("skill-router:", err.getvalue())

    def test_deadline_returns_without_block(self):
        def slow(*a, **k):
            time.sleep(2)
            return fake_route("late")
        with mock.patch.object(hook, "route_intent", side_effect=slow):
            started = time.monotonic()
            err = io.StringIO()
            with redirect_stderr(err):
                out = hook.run({"prompt": "transcribe this podcast please"}, Config(hook_deadline=0.2))
            self.assertEqual(out, "")
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertIn("no answer within", err.getvalue())

    def test_main_never_fails_on_bad_stdin(self):
        with mock.patch("sys.stdin", io.StringIO("not json")):
            self.assertEqual(hook.main(), 0)


class KeyStoreTests(unittest.TestCase):
    def test_file_store_is_atomic_and_private(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "sub" / "api_key"
            self.assertEqual(client_mod.store_key("first", path), str(path))
            self.assertEqual(client_mod.file_key(path), "first")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            with mock.patch("os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(client_mod.KeyStoreError):
                    client_mod.store_key("second", path)
            self.assertEqual(client_mod.file_key(path), "first")
            self.assertEqual([p.name for p in path.parent.iterdir()], ["api_key"])

    def test_api_key_precedence_and_missing(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "api_key"
            with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "", "XDG_CONFIG_HOME": d}), \
                 mock.patch.object(client_mod, "keychain_key", return_value=None):
                with self.assertRaises(client_mod.MissingKeyError):
                    client_mod.api_key()
                (Path(d) / "skill-router").mkdir()
                (Path(d) / "skill-router" / "api_key").write_text("fromfile\n")
                self.assertEqual(client_mod.api_key(), "fromfile")
            with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "fromenv"}):
                self.assertEqual(client_mod.api_key(), "fromenv")


if __name__ == "__main__":
    unittest.main()
