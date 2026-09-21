from __future__ import annotations

import io
import os
import stat
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from skill_router import client as client_mod
from skill_router import hook, service
from skill_router.config import Config
from skill_router.roster import Skill
from skill_router.router import MATCHED, Route


def fake_route(winner):
    return Route("x", MATCHED, winner, "ok")


class HookTests(unittest.TestCase):
    def test_short_or_slash_prompts_are_ignored(self):
        self.assertEqual(hook.run({"prompt": "hi"}), "")
        self.assertEqual(hook.run({"prompt": "/compact please now"}), "")
        self.assertEqual(hook.run(["not", "a", "dict"]), "")

    def test_success_prints_block(self):
        with mock.patch.object(hook, "route_intent", return_value=fake_route("transcriber")):
            self.assertIn("transcriber", hook.run({"prompt": "transcribe this podcast please"}, Config()))

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
                out = hook.run({"prompt": "transcribe this podcast please"}, Config(hook_timeout=0.05, hook_deadline=0.2))
            self.assertEqual(out, "")
            self.assertLess(time.monotonic() - started, 1.5)
            self.assertIn("no answer within", err.getvalue())

    def test_deadline_is_shared_across_every_request_the_roster_needs(self):
        many = [Skill(f"s{i}", "h", f"/x/s{i}/SKILL.md", "d", "b") for i in range(5)]
        built = []

        def fake_client(model, timeout, retry):
            built.append((timeout, retry))
            return mock.MagicMock(__enter__=lambda s: s, __exit__=lambda *a: None)

        with mock.patch.object(service, "roster", return_value=many), \
             mock.patch.object(service, "make_client", side_effect=fake_client), \
             mock.patch.object(service, "route", return_value=fake_route("s1")):
            cfg = Config(shard_size=1, parallel=1, hook_timeout=5, hook_deadline=15)
            service.route_intent("transcribe this podcast please", cfg=cfg, deadline=cfg.hook_deadline)
            cfg = Config(shard_size=50, parallel=4, hook_timeout=5, hook_deadline=15)
            service.route_intent("transcribe this podcast please", cfg=cfg, deadline=cfg.hook_deadline)
            service.route_intent("transcribe this podcast please", cfg=cfg)
        self.assertLessEqual(built[0][0], 15 / 7)
        self.assertGreater(built[0][0], 15 / 7 - 0.5)
        self.assertEqual(built[0][1].max_retries, 0)
        self.assertLessEqual(built[1][0], 5.0)
        self.assertGreater(built[1][0], 4.5)
        self.assertEqual(built[2], (cfg.timeout, None))
        with mock.patch.object(service, "roster", return_value=many), \
             mock.patch.object(service, "make_client", side_effect=fake_client):
            with self.assertRaises(TimeoutError):
                service.route_intent("transcribe this podcast please", cfg=cfg, deadline=0.0)
        self.assertEqual(len(built), 3)

    def test_main_never_fails_on_bad_stdin(self):
        with mock.patch("sys.stdin", io.StringIO("not json")):
            self.assertEqual(hook.main(), 0)

    def test_main_never_fails_on_wrong_types_or_internal_errors(self):
        for raw in ('{"prompt": 42}', '{"prompt": []}', '{"prompt": {}}', '[]', '{"prompt": "a long enough prompt", "cwd": 7}'):
            out = io.StringIO()
            with mock.patch("sys.stdin", io.StringIO(raw)), mock.patch("sys.stdout", out), \
                 mock.patch.object(hook, "route_intent", side_effect=RuntimeError("boom")):
                self.assertEqual(hook.main(), 0, raw)
            self.assertEqual(out.getvalue(), "", raw)
        with mock.patch("sys.stdin", io.StringIO('{"prompt": "a long enough prompt"}')), \
             mock.patch.object(hook, "run", side_effect=SystemExit(9)), mock.patch("sys.stderr", io.StringIO()):
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
            with mock.patch("pathlib.Path.mkdir", side_effect=OSError("read-only filesystem")):
                with self.assertRaises(client_mod.KeyStoreError):
                    client_mod.store_key("third", path)
            with mock.patch("tempfile.mkstemp", side_effect=OSError("no space")):
                with self.assertRaises(client_mod.KeyStoreError):
                    client_mod.store_key("third", path)
            self.assertEqual(client_mod.file_key(path), "first")

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
