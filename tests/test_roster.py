from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from skill_router.roster import discover, parse_skill_md


class ParseTests(unittest.TestCase):
    def test_folded_description(self):
        fields, body = parse_skill_md("---\nname: a\ndescription: >\n  first line\n  second line\n---\n# Body\ntext")
        self.assertEqual(fields["description"], "first line second line")
        self.assertTrue(body.startswith("# Body"))

    def test_no_frontmatter(self):
        self.assertEqual(parse_skill_md("# Just a body")[0], {})

    def test_unclosed_frontmatter(self):
        fields, body = parse_skill_md("---\nname: a\ndescription: b\n")
        self.assertEqual(fields, {})

    def test_invalid_yaml_falls_back(self):
        fields, _ = parse_skill_md("---\ndescription: [unclosed\n---\nbody")
        self.assertEqual(fields, {})

    def test_non_string_values_flattened(self):
        fields, _ = parse_skill_md("---\ndescription:\n  - a\n  - b\nmetadata:\n  k: v\n---\nbody")
        self.assertIn("a", fields["description"])


class DiscoverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def discover(self, cwd=None, **kw):
        roots = {
            "claude-code": str(self.home / ".claude/skills"),
            "codex": str(self.home / ".codex/skills"),
            "agents": str(self.home / ".agents/skills"),
        }
        return discover(cwd, roots=roots | kw.pop("roots", {}),
                        plugin_cache=kw.pop("plugin_cache", str(self.home / ".claude/plugins/cache")), **kw)

    def write(self, rel: str, desc: str = "d", body: str = "b"):
        p = self.home / rel / "SKILL.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"---\nname: {p.parent.name}\ndescription: {desc}\n---\n{body}")

    def test_sources_and_precedence(self):
        self.write(".claude/skills/dup", "claude")
        self.write(".codex/skills/dup", "codex")
        self.write(".codex/skills/only-codex")
        self.write(".agents/skills/only-agents")
        self.write(".claude/plugins/cache/market/plug/1.0.0/skills/inner", "plugin")
        proj = self.home / "proj" / "sub"
        proj.mkdir(parents=True)
        self.write("proj/.claude/skills/dup", "project")
        found = {s.name: s for s in self.discover(proj)}
        self.assertEqual(found["dup"].description, "project")
        self.assertEqual(found["plug:inner"].harness, "claude-code-plugin")
        self.assertEqual(set(found), {"dup", "only-codex", "only-agents", "plug:inner"})
        self.assertEqual({s.name: s for s in self.discover()}["dup"].harness, "claude-code")

    def test_body_fallback_description_and_filters(self):
        (self.home / ".claude/skills/bare").mkdir(parents=True)
        (self.home / ".claude/skills/bare/SKILL.md").write_text("# Title\nfirst words of body")
        self.write(".claude/skills/skip")
        found = {s.name: s for s in self.discover(exclude=["skip"])}
        self.assertEqual(found["bare"].description, "Title first words of body")
        self.assertNotIn("skip", found)
        self.assertEqual(self.discover(disabled_harnesses=["claude-code"]), [])

    def test_configured_roots_are_recursive_and_disableable(self):
        self.write("pi/skills/flat")
        self.write("pi/skills/group/nested")
        self.write(".codex/skills/only-codex")
        found = {s.name: s.harness for s in self.discover(roots={"pi": str(self.home / "pi/skills")})}
        self.assertEqual(found, {"flat": "pi", "nested": "pi", "only-codex": "codex"})
        found = self.discover(roots={"pi": str(self.home / "pi/skills")}, disabled_harnesses=["codex", "pi"])
        self.assertEqual(found, [])
        self.assertEqual(self.discover(roots={"codex": ""}), [])

    def test_project_skills_path_that_is_a_file_fails_explicitly(self):
        proj = self.home / "proj"
        (proj / ".claude").mkdir(parents=True)
        (proj / ".claude/skills").write_text("x")
        with self.assertRaises(NotADirectoryError):
            self.discover(proj)
        (self.home / "pi").mkdir()
        (self.home / "pi/skills").write_text("x")
        with self.assertRaises(NotADirectoryError):
            self.discover(roots={"pi": str(self.home / "pi/skills")})

    def test_plugin_cache_and_project_dir_can_be_turned_off(self):
        self.write(".claude/plugins/cache/market/plug/1.0.0/skills/inner")
        proj = self.home / "proj"
        self.write("proj/.claude/skills/local")
        self.assertEqual([s.name for s in self.discover(proj)], ["local", "plug:inner"])
        self.assertEqual(self.discover(proj, plugin_cache="", project_skills=""), [])
        self.assertEqual([s.name for s in self.discover(proj, disabled_harnesses=["project", "claude-code-plugin"])], [])

    def test_unreadable_skill_is_skipped(self):
        self.write(".claude/skills/good")
        dangling = self.home / ".claude/skills/gone/SKILL.md"
        dangling.parent.mkdir(parents=True)
        dangling.symlink_to(self.home / "nowhere")
        self.assertEqual([s.name for s in self.discover()], ["good"])

    def test_fit_json_bounds_escaped_text(self):
        from skill_router.roster import fit_json, json_len
        self.assertEqual(fit_json("\U0001F600" * 100, 13), "\U0001F600")
        for text in ('"\n\t' * 40, "\\" * 100, "plain " * 30, "\u0001" * 50, "\U0001F600" * 40, "a\U0001F600\u0001" * 20, ""):
            for limit in (0, 1, 7, 50, 1000):
                out = fit_json(text, limit)
                self.assertLessEqual(json_len(out), limit)
                self.assertTrue(text.startswith(out))
                if len(out) < len(text):
                    self.assertGreater(json_len(text[: len(out) + 1]), limit)

    def test_overlong_names_are_skipped(self):
        from skill_router.roster import NAME_CHARS
        self.write(f".claude/skills/{'a' * NAME_CHARS}")
        self.write(f".claude/skills/{'b' * (NAME_CHARS + 1)}")
        self.assertEqual([s.name for s in self.discover()], ["a" * NAME_CHARS])


if __name__ == "__main__":
    unittest.main()
