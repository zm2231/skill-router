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
        found = {s.name: s for s in discover(self.home, proj)}
        self.assertEqual(found["dup"].description, "project")
        self.assertEqual(found["plug:inner"].harness, "claude-code-plugin")
        self.assertEqual(set(found), {"dup", "only-codex", "only-agents", "plug:inner"})
        self.assertEqual({s.name: s for s in discover(self.home, None)}["dup"].harness, "claude-code")

    def test_body_fallback_description_and_filters(self):
        (self.home / ".claude/skills/bare").mkdir(parents=True)
        (self.home / ".claude/skills/bare/SKILL.md").write_text("# Title\nfirst words of body")
        self.write(".claude/skills/skip")
        found = {s.name: s for s in discover(self.home, None, exclude=["skip"])}
        self.assertEqual(found["bare"].description, "Title first words of body")
        self.assertNotIn("skip", found)
        self.assertEqual(discover(self.home, None, disabled_harnesses=["claude-code"]), [])

    def test_unreadable_skill_is_skipped(self):
        self.write(".claude/skills/good")
        dangling = self.home / ".claude/skills/gone/SKILL.md"
        dangling.parent.mkdir(parents=True)
        dangling.symlink_to(self.home / "nowhere")
        self.assertEqual([s.name for s in discover(self.home, None)], ["good"])

    def test_fit_json_bounds_escaped_text(self):
        from skill_router.roster import fit_json, json_len
        for text in ('"\n\t' * 40, "\\" * 100, "plain " * 30, "\u0001" * 50, ""):
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
        self.assertEqual([s.name for s in discover(self.home, None)], ["a" * NAME_CHARS])


if __name__ == "__main__":
    unittest.main()
