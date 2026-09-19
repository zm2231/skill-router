from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from skill_router import cli


class RosterCommandTests(unittest.TestCase):
    def test_roster_json_is_valid(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            skill = home / ".claude" / "skills" / "one"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: one\ndescription: does one thing\n---\nbody")
            with mock.patch.dict(os.environ, {"SKILL_ROUTER_CONFIG": str(home / "none.toml")}), \
                 mock.patch("pathlib.Path.home", return_value=home):
                out = io.StringIO()
                with redirect_stdout(out):
                    code = cli.main(["roster", "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out.getvalue())
        self.assertEqual([s["name"] for s in data if s["harness"] == "claude-code"], ["one"])

    def test_bad_config_exits_2(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "c.toml"
            path.write_text("exclude = 1\n")
            with mock.patch.dict(os.environ, {"SKILL_ROUTER_CONFIG": str(path)}):
                err = io.StringIO()
                with mock.patch("sys.stderr", err):
                    self.assertEqual(cli.main(["roster"]), 2)
                self.assertIn("exclude", err.getvalue())
