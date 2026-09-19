from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from skill_router.config import Config, ConfigError


class ConfigTests(unittest.TestCase):
    def test_bounds(self):
        for bad in (dict(shortlist=0), dict(gate_floor=0.5, gate_threshold=0.3), dict(fits_threshold=1.5),
                    dict(timeout=0), dict(hook_deadline=-1), dict(hook_deadline=20), dict(hook_timeout=10, hook_deadline=8),
                    dict(choice_chars=0), dict(shortlist=100), dict(model=" ")):
            with self.assertRaises(ConfigError, msg=bad):
                Config(**bad)

    def test_load_rejects_unknown_and_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.toml"
            with mock.patch.dict(os.environ, {"SKILL_ROUTER_CONFIG": str(path)}):
                path.write_text("nope = 1\n")
                with self.assertRaises(ConfigError):
                    Config.load()
                path.write_text("shortlist = 0\n")
                with self.assertRaises(ConfigError):
                    Config.load()
                path.write_text("shortlist = [\n")
                with self.assertRaises(ConfigError):
                    Config.load()
                path.write_text("shortlist = 2\nmodel = 'jev-1.13.0'\n")
                cfg = Config.load()
                self.assertEqual((cfg.shortlist, cfg.model), (2, "jev-1.13.0"))

    def test_env_model_override(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ, {"SKILL_ROUTER_CONFIG": str(Path(d) / "x.toml"),
                                              "TYPESAFE_DEFAULT_MODEL": "jev-preview"}):
                self.assertEqual(Config.load().model, "jev-preview")


if __name__ == "__main__":
    unittest.main()


class ConfigTypeTests(unittest.TestCase):
    def test_list_fields_must_be_string_lists(self):
        for bad in (dict(extra_roots=[1]), dict(disabled_harnesses=1), dict(exclude="x"), dict(exclude=[None])):
            with self.assertRaises(ConfigError, msg=bad):
                Config(**bad)

    def test_scalar_types(self):
        for bad in (dict(shortlist="3"), dict(shortlist=True), dict(gate_floor="0.1"), dict(model=3)):
            with self.assertRaises(ConfigError, msg=bad):
                Config(**bad)
        Config(gate_floor=0, timeout=10)

    def test_load_names_path_for_list_type(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.toml"
            path.write_text("extra_roots = [1]\n")
            with mock.patch.dict(os.environ, {"SKILL_ROUTER_CONFIG": str(path)}):
                with self.assertRaises(ConfigError) as ctx:
                    Config.load()
            self.assertIn(str(path), str(ctx.exception))


class FiniteTests(unittest.TestCase):
    def test_non_finite_numbers_rejected(self):
        for name in ("timeout", "hook_timeout", "hook_deadline", "gate_floor"):
            for bad in (float("nan"), float("inf"), -float("inf")):
                with self.assertRaises(ConfigError, msg=(name, bad)):
                    Config(**{name: bad})

    def test_nan_in_toml_names_path(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "c.toml"
            path.write_text("hook_deadline = nan\n")
            with mock.patch.dict(os.environ, {"SKILL_ROUTER_CONFIG": str(path)}):
                with self.assertRaises(ConfigError) as ctx:
                    Config.load()
            self.assertIn("hook_deadline", str(ctx.exception))
