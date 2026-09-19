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
                    dict(timeout=0), dict(hook_deadline=-1), dict(wide_chunk_chars=0), dict(model=" ")):
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
