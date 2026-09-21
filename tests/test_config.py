from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from skill_router.config import Config, ConfigError


class ConfigTests(unittest.TestCase):
    def test_bounds(self):
        for bad in (dict(shard_size=0), dict(parallel=0), dict(need_low=0.5, need_high=0.3), dict(direct_floor=1.5),
                    dict(shortlist_min=4, shortlist_cap=3), dict(accept_margin=-0.1),
                    dict(timeout=0), dict(hook_deadline=-1), dict(hook_deadline=20), dict(hook_timeout=10, hook_deadline=8),
                    dict(intent_chars=0), dict(model=" ")):
            with self.assertRaises(ConfigError, msg=bad):
                Config(**bad)

    def test_load_rejects_unknown_and_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.toml"
            with mock.patch.dict(os.environ, {"SKILL_ROUTER_CONFIG": str(path)}):
                path.write_text("nope = 1\n")
                with self.assertRaises(ConfigError):
                    Config.load()
                path.write_text("shard_size = 0\n")
                with self.assertRaises(ConfigError):
                    Config.load()
                path.write_text("shard_size = [\n")
                with self.assertRaises(ConfigError):
                    Config.load()
                path.write_text("shard_size = 2\nmodel = 'jev-1.13.0'\n")
                cfg = Config.load()
                self.assertEqual((cfg.shard_size, cfg.model), (2, "jev-1.13.0"))
                with mock.patch("pathlib.Path.read_text", side_effect=PermissionError("denied")):
                    with self.assertRaises(ConfigError) as ctx:
                        Config.load()
                self.assertIn(str(path), str(ctx.exception))

    def test_env_model_override(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ, {"SKILL_ROUTER_CONFIG": str(Path(d) / "x.toml"),
                                              "TYPESAFE_DEFAULT_MODEL": "jev-preview"}):
                self.assertEqual(Config.load().model, "jev-preview")


if __name__ == "__main__":
    unittest.main()


class ConfigTypeTests(unittest.TestCase):
    def test_list_fields_must_be_string_lists(self):
        for bad in (dict(roots=[1]), dict(roots={"a": 1}), dict(roots={"": "x"}), dict(plugin_cache=1), dict(project_skills=None),
                    dict(disabled_harnesses=1), dict(exclude="x"), dict(exclude=[None])):
            with self.assertRaises(ConfigError, msg=bad):
                Config(**bad)

    def test_scalar_types(self):
        for bad in (dict(shard_size="3"), dict(shard_size=True), dict(direct_floor="0.1"), dict(model=3)):
            with self.assertRaises(ConfigError, msg=bad):
                Config(**bad)
        Config(direct_floor=0, timeout=10)

    def test_source_that_is_a_file_is_rejected_but_absent_or_off_is_fine(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "not-a-dir"
            f.write_text("x")
            for bad in (dict(roots={"pi": str(f)}), dict(plugin_cache=str(f))):
                with self.assertRaises(ConfigError, msg=bad) as ctx:
                    Config(**bad)
                self.assertIn("not a directory", str(ctx.exception))
            broken = Path(d) / "dangling"
            broken.symlink_to(Path(d) / "gone")
            with self.assertRaises(ConfigError):
                Config(roots={"pi": str(broken)})
            Config(roots={"pi": str(Path(d) / "missing")}, plugin_cache="")

    def test_load_names_path_for_list_type(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.toml"
            path.write_text("roots = [1]\n")
            with mock.patch.dict(os.environ, {"SKILL_ROUTER_CONFIG": str(path)}):
                with self.assertRaises(ConfigError) as ctx:
                    Config.load()
            self.assertIn(str(path), str(ctx.exception))


class FiniteTests(unittest.TestCase):
    def test_non_finite_numbers_rejected(self):
        for name in ("timeout", "hook_timeout", "hook_deadline", "direct_floor"):
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
