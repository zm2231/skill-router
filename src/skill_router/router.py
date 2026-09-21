"""Score every skill on its own, verify the shortlist against full bodies, then ask whether the
request needed a skill at all when nothing verified."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from typesafe_sdk import (
    Choice,
    ChoiceAnswer,
    Noul,
    NoulAnswer,
    Score,
    ScoreAnswer,
    TypeSafeClient,
)

from .config import Config
from .prompts import (
    DIRECT,
    NEED_CRITERIA,
    NEED_INSTRUCTIONS,
    NO_MATCH,
    NO_MATCH_CRITERIA,
    RERANK_INSTRUCTIONS,
    SCORE_INSTRUCTIONS,
    SCORE_LEVELS,
)
from .roster import Skill, fit_json

MATCHED = "matched"
NONE_NEEDED = "none_needed"
LIKELY_MISSING = "likely_missing"
UNCERTAIN = "uncertain"


@dataclass
class Candidate:
    name: str
    direct: float
    rerank: float | None = None


@dataclass
class Route:
    intent: str
    outcome: str
    winner: str | None
    reason: str
    ranked: list[Candidate] = field(default_factory=list)
    no_match: float | None = None
    need: float | None = None
    truncated: bool = False
    usage: dict[str, int] = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0})
    model: str = ""


def _state(cfg: Config, intent: str, context: str) -> dict:
    return {"request": intent[:cfg.intent_chars], "recent_context": context[:cfg.context_chars]}


def _score_question(cfg: Config, s: Skill) -> Score:
    described = fit_json(s.description, cfg.wide_description_chars)
    return Score(
        instructions=f"{SCORE_INSTRUCTIONS} The skill is named '{s.name}' and is described as: {described}",
        criteria=SCORE_LEVELS,
    )


def _shards(cfg: Config, skills: list[Skill]) -> list[list[Skill]]:
    return [skills[i:i + cfg.shard_size] for i in range(0, len(skills), cfg.shard_size)]


class _Usage:
    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.model = ""

    def add(self, response) -> None:
        self.input_tokens += response.usage.input_tokens or 0
        self.output_tokens += response.usage.output_tokens or 0
        self.model = self.model or response.model

    def as_dict(self) -> dict[str, int]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}


def score_all(client: TypeSafeClient, cfg: Config, skills: list[Skill], state: dict, usage: _Usage) -> list[Candidate]:
    """P(direct) for every skill, each judged in its own Score question; shards run concurrently."""
    def ask(shard: list[Skill]):
        return client.system_one(
            state=state,
            questions={s.name: _score_question(cfg, s) for s in shard},
            model=cfg.model,
        )

    shards = _shards(cfg, skills)
    with ThreadPoolExecutor(max_workers=min(cfg.parallel, len(shards))) as pool:
        responses = list(pool.map(ask, shards))
    ranked: list[Candidate] = []
    for shard, response in zip(shards, responses):
        usage.add(response)
        for s in shard:
            answer = response.answers[s.name]
            assert isinstance(answer, ScoreAnswer)
            ranked.append(Candidate(s.name, answer.probabilities.get(DIRECT, 0.0)))
    ranked.sort(key=lambda c: -c.direct)
    return ranked


def shortlist(cfg: Config, ranked: list[Candidate]) -> tuple[list[Candidate], bool]:
    """Every candidate over the floor, capped; the top few anyway when none clears it.
    The flag says the cap cut candidates that had cleared the floor."""
    cleared = [c for c in ranked if c.direct >= cfg.direct_floor]
    if not cleared:
        return ranked[:cfg.shortlist_min], False
    return cleared[:cfg.shortlist_cap], len(cleared) > cfg.shortlist_cap


def rerank(client: TypeSafeClient, cfg: Config, by_name: dict[str, Skill], names: list[str], state: dict, usage: _Usage) -> dict[str, float]:
    """Choice probabilities over the shortlist's full bodies plus the no-match option."""
    criteria = {
        n: f"{fit_json(by_name[n].description, cfg.rerank_description_chars)}. "
           f"{fit_json(by_name[n].body, cfg.excerpt_chars)}"
        for n in names
    }
    criteria[NO_MATCH] = NO_MATCH_CRITERIA
    response = client.system_one(
        state=state,
        questions={"which": Choice(instructions=RERANK_INSTRUCTIONS, criteria=criteria)},
        model=cfg.model,
    )
    usage.add(response)
    answer = response.answers["which"]
    assert isinstance(answer, ChoiceAnswer)
    return dict(answer.probabilities)


def need(client: TypeSafeClient, cfg: Config, state: dict, usage: _Usage) -> float:
    """P(the request materially requires a specialized procedure), independent of what is installed."""
    response = client.system_one(
        state=state,
        questions={"need": Noul(instructions=NEED_INSTRUCTIONS, criteria=NEED_CRITERIA)},
        model=cfg.model,
    )
    usage.add(response)
    answer = response.answers["need"]
    assert isinstance(answer, NoulAnswer)
    return answer.noul


def accepted(cfg: Config, probabilities: dict[str, float]) -> str | None:
    """The skill the rerank verified, if its probability is high enough and clear of no-match."""
    winner = max(probabilities, key=lambda k: probabilities[k])
    if winner == NO_MATCH:
        return None
    if probabilities[winner] < cfg.accept_probability:
        return None
    if probabilities[winner] - probabilities.get(NO_MATCH, 0.0) < cfg.accept_margin:
        return None
    return winner


def route(client: TypeSafeClient, cfg: Config, skills: list[Skill], intent: str, context: str = "") -> Route:
    state = _state(cfg, intent, context)
    usage = _Usage()
    ranked: list[Candidate] = []
    truncated = False
    no_match: float | None = None
    reason = "roster: no skills discovered"

    if skills:
        by_name = {s.name: s for s in skills}
        ranked = score_all(client, cfg, skills, state, usage)
        short, truncated = shortlist(cfg, ranked)
        probabilities = rerank(client, cfg, by_name, [c.name for c in short], state, usage)
        no_match = probabilities.get(NO_MATCH)
        for c in short:
            c.rerank = probabilities.get(c.name)
        winner = accepted(cfg, probabilities)
        if winner:
            return Route(intent, MATCHED, winner, "rerank verified", ranked, no_match, None, truncated,
                         usage.as_dict(), usage.model)
        top = max(probabilities, key=lambda k: probabilities[k])
        reason = ("no-match chosen" if top == NO_MATCH
                  else f"{top} at {probabilities[top]:.2f} against no-match {no_match:.2f} did not clear "
                       f"{cfg.accept_probability:.2f} with margin {cfg.accept_margin:.2f}")

    p_need = need(client, cfg, state, usage)
    if p_need <= cfg.need_low:
        outcome = NONE_NEEDED
    elif p_need >= cfg.need_high and not truncated:
        outcome = LIKELY_MISSING
    else:
        outcome = UNCERTAIN
    reason = f"{reason}; need {p_need:.2f}" + ("; shortlist truncated" if truncated else "")
    return Route(intent, outcome, None, reason, ranked, no_match, p_need, truncated, usage.as_dict(), usage.model)


def suggestion_block(r: Route) -> str:
    """The context injection for a hook: only a verified match, never advice to install something."""
    if r.outcome != MATCHED:
        return ""
    return (
        "<skill_relevance>\n"
        f"Relevant to the current request: {r.winner}. Load it with the Skill tool before proceeding.\n"
        "</skill_relevance>"
    )
