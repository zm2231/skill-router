from __future__ import annotations

import threading
import unittest
from dataclasses import dataclass, field

from typesafe_sdk import Choice, ChoiceAnswer, Noul, NoulAnswer, Score, ScoreAnswer

from skill_router.config import Config
from skill_router.prompts import DIRECT
from skill_router.roster import Skill
from skill_router.router import (
    LIKELY_MISSING,
    MATCHED,
    NO_MATCH,
    NONE_NEEDED,
    UNCERTAIN,
    route,
    suggestion_block,
)


@dataclass
class Usage:
    input_tokens: int = 100
    output_tokens: int = 10


@dataclass
class Response:
    answers: dict
    model: str = "jev-test"
    usage: Usage = field(default_factory=Usage)


def score_answer(direct: float) -> ScoreAnswer:
    return ScoreAnswer(
        type="score", score=2 * direct, confidence=1.0,
        legend={0: "u", 1: "a", 2: "d"},
        probabilities={0: 1.0 - direct, 1: 0.0, DIRECT: direct},
    )


class FakeClient:
    def __init__(self, direct: dict[str, float], rerank: dict[str, float] | None = None, need: float = 0.0):
        self.direct, self.rerank, self.need = direct, rerank or {}, need
        self.calls: list[dict] = []
        self.threads: set[int] = set()
        self.lock = threading.Lock()

    def system_one(self, state, questions, model=None):
        with self.lock:
            self.calls.append(questions)
            self.threads.add(threading.get_ident())
        answers = {}
        for key, q in questions.items():
            if isinstance(q, Score):
                answers[key] = score_answer(self.direct.get(key, 0.0))
            elif isinstance(q, Choice):
                probs = {k: self.rerank.get(k, 0.0) for k in q.criteria}
                answers[key] = ChoiceAnswer(type="choice", choice=max(probs, key=probs.get), confidence=1.0, probabilities=probs)
            elif isinstance(q, Noul):
                answers[key] = NoulAnswer(type="noul", noul=self.need, confidence=1.0)
        return Response(answers)


def skills(n=5):
    return [Skill(f"s{i}", "claude-code", f"/x/s{i}/SKILL.md", f"skill {i} does thing {i}", f"body {i}") for i in range(n)]


def kinds(calls):
    return ["score" if any(isinstance(q, Score) for q in c.values())
            else "rerank" if "which" in c else "need" for c in calls]


class RouteTests(unittest.TestCase):
    def test_matched_needs_two_rounds(self):
        c = FakeClient({"s1": 0.9, "s2": 0.3}, {"s1": 0.8, "s2": 0.1, NO_MATCH: 0.1})
        r = route(c, Config(), skills(), "do thing 1")
        self.assertEqual((r.outcome, r.winner), (MATCHED, "s1"))
        self.assertEqual(kinds(c.calls), ["score", "rerank"])
        self.assertIsNone(r.need)
        self.assertEqual(r.no_match, 0.1)
        self.assertIn("s1", suggestion_block(r))

    def test_rerank_sees_only_candidates_over_the_floor(self):
        c = FakeClient({"s1": 0.9, "s2": 0.3, "s3": 0.19}, {"s1": 0.8})
        route(c, Config(direct_floor=0.2), skills(), "x")
        self.assertEqual(set(c.calls[1]["which"].criteria), {"s1", "s2", NO_MATCH})

    def test_nothing_over_the_floor_still_reranks_the_top_few(self):
        c = FakeClient({"s1": 0.1, "s2": 0.05, "s3": 0.02, "s4": 0.01}, {NO_MATCH: 0.9}, need=0.1)
        r = route(c, Config(shortlist_min=3), skills(), "x")
        self.assertEqual(set(c.calls[1]["which"].criteria), {"s1", "s2", "s3", NO_MATCH})
        self.assertEqual(r.outcome, NONE_NEEDED)

    def test_shortlist_cap_marks_truncation_and_blocks_missing(self):
        c = FakeClient({f"s{i}": 0.5 for i in range(5)}, {NO_MATCH: 0.9}, need=0.95)
        r = route(c, Config(shortlist_cap=3, shortlist_min=1), skills(), "x")
        self.assertTrue(r.truncated)
        self.assertEqual(len(c.calls[1]["which"].criteria), 4)
        self.assertEqual(r.outcome, UNCERTAIN)

    def test_no_match_then_need_decides(self):
        for need, outcome in ((0.05, NONE_NEEDED), (0.5, UNCERTAIN), (0.9, LIKELY_MISSING)):
            c = FakeClient({"s1": 0.5}, {NO_MATCH: 0.9, "s1": 0.1}, need=need)
            r = route(c, Config(), skills(), "x")
            self.assertEqual(r.outcome, outcome, need)
            self.assertEqual(kinds(c.calls), ["score", "rerank", "need"])
            self.assertEqual(r.need, need)
            self.assertIsNone(r.winner)
            self.assertEqual(suggestion_block(r), "")

    def test_winner_below_accept_probability_is_not_verified(self):
        c = FakeClient({"s1": 0.9}, {"s1": 0.5, NO_MATCH: 0.1}, need=0.9)
        r = route(c, Config(accept_probability=0.55), skills(), "x")
        self.assertEqual(r.outcome, LIKELY_MISSING)
        self.assertIn("did not clear", r.reason)

    def test_winner_without_margin_over_no_match_is_not_verified(self):
        c = FakeClient({"s1": 0.9}, {"s1": 0.56, NO_MATCH: 0.44}, need=0.1)
        self.assertEqual(route(c, Config(accept_margin=0.15), skills(), "x").outcome, NONE_NEEDED)
        c = FakeClient({"s1": 0.9}, {"s1": 0.6, NO_MATCH: 0.4})
        self.assertEqual(route(c, Config(accept_margin=0.15), skills(), "x").winner, "s1")

    def test_rerank_probabilities_are_recorded(self):
        c = FakeClient({"s1": 0.9, "s2": 0.4}, {"s1": 0.7, "s2": 0.2, NO_MATCH: 0.1})
        r = route(c, Config(), skills(), "x")
        by = {x.name: x for x in r.ranked}
        self.assertEqual((by["s1"].rerank, by["s2"].rerank), (0.7, 0.2))
        self.assertIsNone(by["s0"].rerank)

    def test_empty_roster_asks_need_only(self):
        c = FakeClient({}, need=0.9)
        r = route(c, Config(), [], "x")
        self.assertEqual(r.outcome, LIKELY_MISSING)
        self.assertEqual(kinds(c.calls), ["need"])
        self.assertIsNone(r.no_match)

    def test_every_skill_is_scored_across_shards(self):
        many = skills(120)
        c = FakeClient({"s77": 0.9}, {"s77": 0.9})
        r = route(c, Config(shard_size=50, parallel=4), many, "thing 77")
        self.assertEqual(r.winner, "s77")
        score_calls = [x for x in c.calls if any(isinstance(q, Score) for q in x.values())]
        self.assertEqual(sorted(len(x) for x in score_calls), [20, 50, 50])
        self.assertEqual({k for x in score_calls for k in x}, {s.name for s in many})
        self.assertEqual(len(r.ranked), 120)

    def test_usage_sums_every_request(self):
        c = FakeClient({"s1": 0.5}, {NO_MATCH: 0.9}, need=0.5)
        r = route(c, Config(shard_size=2), skills(5), "x")
        self.assertEqual(r.usage, {"input_tokens": 500, "output_tokens": 50})
        self.assertEqual(r.model, "jev-test")

    def test_score_question_describes_the_skill(self):
        c = FakeClient({"s1": 0.9}, {"s1": 0.9})
        route(c, Config(wide_description_chars=12), skills(2), "x")
        q = c.calls[0]["s1"]
        self.assertIn("'s1'", q.instructions)
        self.assertIn("skill 1 does", q.instructions)
        self.assertNotIn("thing 1", q.instructions)
        self.assertEqual(len(q.criteria), 3)


if __name__ == "__main__":
    unittest.main()
