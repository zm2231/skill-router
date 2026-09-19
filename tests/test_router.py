from __future__ import annotations

import unittest
from dataclasses import dataclass, field

from skill_router.config import Config
from skill_router.roster import Skill
from skill_router.router import MATCHED, MISSING, NO_MATCH, NONE_NEEDED, route, suggestion_block


@dataclass
class Choice:
    choice: str
    probabilities: dict


@dataclass
class Noul:
    noul: float


@dataclass
class Usage:
    input_tokens: int = 100
    output_tokens: int = 10


@dataclass
class Response:
    answers: dict
    model: str = "jev-test"
    usage: Usage = field(default_factory=Usage)


class FakeClient:
    """Answers the wide Choice from `wide`, gate nouls from `gate`, and the rerank from `rerank`."""

    def __init__(self, wide, gate, rerank_choice, fits):
        self.wide, self.gate, self.rerank_choice, self.fits = wide, gate, rerank_choice, fits
        self.calls = []

    def system_one(self, state, questions, model=None):
        self.calls.append(questions)
        answers = {}
        which = questions["which"]
        keys = list(which.criteria.keys())
        if NO_MATCH in keys:
            answers["which"] = Choice(self.rerank_choice, {k: 0.0 for k in keys})
            for k, q in questions.items():
                if k.startswith("fits::"):
                    answers[k] = Noul(self.fits[k.removeprefix("fits::")])
        else:
            probs = {k: self.wide.get(k, 0.0) for k in keys}
            answers["which"] = Choice(max(probs, key=probs.get), probs)
            for k in questions:
                if k.startswith("gate::"):
                    answers[k] = Noul(self.gate[k.removeprefix("gate::")])
        return Response(answers)


def skills(n=5):
    return [Skill(f"s{i}", "claude-code", f"/x/s{i}/SKILL.md", f"skill {i} does thing {i}", f"body {i}") for i in range(n)]


NEEDS = {"acts_on_user_system": 0.9, "would_follow_documented_procedure": 0.8, "prose_suffices": 0.1}
NO_NEED = {"acts_on_user_system": 0.02, "would_follow_documented_procedure": 0.05, "prose_suffices": 0.95}
GRAY = {"acts_on_user_system": 0.05, "would_follow_documented_procedure": 0.15, "prose_suffices": 0.5}


class RouteTests(unittest.TestCase):
    def test_matched(self):
        c = FakeClient({"s1": 0.9, "s2": 0.1}, NEEDS, "s1", {"s1": 0.9, "s2": 0.3, "s0": 0.0})
        r = route(c, Config(), skills(), "do thing 1")
        self.assertEqual((r.outcome, r.winner), (MATCHED, "s1"))
        self.assertEqual(len(c.calls), 2)
        self.assertIn(NO_MATCH, c.calls[1]["which"].criteria)
        self.assertIn("s1", suggestion_block(r))

    def test_none_needed_skips_rerank(self):
        c = FakeClient({"s1": 0.9}, NO_NEED, "s1", {})
        r = route(c, Config(), skills(), "what is a monad")
        self.assertEqual(r.outcome, NONE_NEEDED)
        self.assertEqual(len(c.calls), 1)
        self.assertEqual(suggestion_block(r), "")

    def test_missing_when_no_match_chosen(self):
        c = FakeClient({"s1": 0.5, "s2": 0.3}, NEEDS, NO_MATCH, {"s1": 0.3, "s2": 0.2, "s0": 0.1})
        r = route(c, Config(), skills(), "post to mastodon")
        self.assertEqual((r.outcome, r.winner), (MISSING, None))
        self.assertIn("No installed skill", suggestion_block(r))

    def test_missing_when_winner_fits_weakly(self):
        c = FakeClient({"s1": 0.9}, NEEDS, "s1", {"s1": 0.2, "s2": 0.1, "s0": 0.0})
        r = route(c, Config(), skills(), "x")
        self.assertEqual(r.outcome, MISSING)

    def test_gray_zone_requires_strong_fit(self):
        weak = FakeClient({"s1": 0.9}, GRAY, "s1", {"s1": 0.5, "s2": 0.1, "s0": 0.0})
        self.assertEqual(route(weak, Config(), skills(), "x").outcome, NONE_NEEDED)
        strong = FakeClient({"s1": 0.9}, GRAY, "s1", {"s1": 0.95, "s2": 0.1, "s0": 0.0})
        self.assertEqual(route(strong, Config(), skills(), "x").outcome, MATCHED)

    def test_empty_roster(self):
        c = FakeClient({}, NEEDS, "", {})
        self.assertEqual(route(c, Config(), [], "x").outcome, MISSING)
        self.assertEqual(c.calls, [])

    def test_roster_smaller_than_shortlist(self):
        c = FakeClient({"s0": 0.7, "s1": 0.3}, NEEDS, "s0", {"s0": 0.9, "s1": 0.2})
        r = route(c, Config(shortlist=3), skills(2), "x")
        self.assertEqual(r.winner, "s0")

    def test_every_wide_request_stays_within_bound(self):
        from skill_router.router import _cost
        cfg = Config(wide_chunk_chars=200, wide_description_chars=20, shortlist=3)
        many = skills(40)
        wide = {s.name: 0.0 for s in many}
        wide["s33"] = 0.9
        c = FakeClient(wide, NEEDS, "s33", {"s33": 0.9, "s0": 0.1, "s1": 0.1, "s2": 0.1, "s3": 0.1})
        r = route(c, cfg, many, "thing 33")
        self.assertEqual(r.winner, "s33")
        by_name = {s.name: s for s in many}
        wide_calls = [q for q in c.calls if NO_MATCH not in q["which"].criteria]
        self.assertGreater(len(wide_calls), 3)
        for q in wide_calls:
            names = list(q["which"].criteria)
            self.assertLessEqual(sum(_cost(cfg, by_name[n]) for n in names), cfg.wide_chunk_chars, names)
        self.assertEqual(sum(1 for q in wide_calls if any(k.startswith("gate::") for k in q)), 1)

    def test_chunk_too_small_for_one_entry_is_rejected(self):
        from skill_router.config import ConfigError
        with self.assertRaises(ConfigError):
            Config(wide_chunk_chars=400, wide_description_chars=320)

    def test_chunking_merges_leaders(self):
        cfg = Config(wide_chunk_chars=200, wide_description_chars=20, shortlist=2)
        many = skills(12)
        wide = {s.name: 0.0 for s in many}
        wide["s7"] = 0.9
        c = FakeClient(wide, NEEDS, "s7", {"s7": 0.9, "s0": 0.1, "s1": 0.1, "s3": 0.1})
        r = route(c, cfg, many, "thing 7")
        self.assertEqual(r.winner, "s7")
        wide_calls = [q for q in c.calls if NO_MATCH not in q["which"].criteria]
        self.assertGreater(len(wide_calls), 2)
        self.assertEqual(sum(1 for q in wide_calls if any(k.startswith("gate::") for k in q)), 1)


if __name__ == "__main__":
    unittest.main()
