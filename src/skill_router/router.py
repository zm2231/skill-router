"""Two Jev requests per intent: rank every skill and gate, then rerank the shortlist and verify."""
from __future__ import annotations

from dataclasses import dataclass, field

from typesafe_sdk import Choice, Noul, TypeSafeClient

from .config import Config
from .roster import Skill

CHOICE_INSTRUCTIONS = (
    "Which of these skills, if any, is the right one to load to help with the "
    "user's latest request?"
)
RERANK_INSTRUCTIONS = (
    "Which of these skills is the right one to load for the user's latest request? "
    "Read what each actually does, not just its name. Pick the no-match option when "
    "none of them does the specific thing asked, even if one is topically nearby."
)
NO_MATCH = "none-of-these"
NO_MATCH_CRITERIA = (
    "None of these skills does what the request asks for. The specific tool, service, "
    "format, or workflow the user needs is not covered by any of them."
)

GATE_QUESTIONS = {
    "acts_on_user_system": (
        "Is the assistant being asked to act on the user's files, accounts, devices, "
        "or online services, rather than only to explain or advise?"
    ),
    "would_follow_documented_procedure": (
        "Would a careful expert answering this consult a specific documented procedure "
        "or set of commands, rather than answering from general understanding?"
    ),
    "prose_suffices": (
        "Could a knowledgeable generalist fully satisfy this request in prose, with "
        "no tools, no documentation, and no access to the user's files or accounts?"
    ),
}
INVERTED = {"prose_suffices"}


@dataclass
class Candidate:
    name: str
    probability: float
    fits: float | None = None


MATCHED = "matched"
MISSING = "missing"
NONE_NEEDED = "none_needed"


@dataclass
class Route:
    intent: str
    gate: float
    gate_values: dict[str, float]
    ranked: list[Candidate]
    winner: str | None
    outcome: str
    reason: str
    usage: dict[str, int] = field(default_factory=dict)
    model: str = ""



def _state(intent: str, context: str) -> dict:
    return {"request": intent, "recent_context": context}


def rank_wide(client: TypeSafeClient, cfg: Config, skills: list[Skill], intent: str, context: str):
    questions = {
        "which": Choice(
            instructions=CHOICE_INSTRUCTIONS,
            criteria={s.name: s.description[:cfg.wide_description_chars] for s in skills},
        )
    }
    for key, text in GATE_QUESTIONS.items():
        questions[f"gate::{key}"] = Noul(instructions=text)
    return client.system_one(state=_state(intent, context), questions=questions, model=cfg.model)


def rerank(client: TypeSafeClient, cfg: Config, by_name: dict[str, Skill], names: list[str], intent: str, context: str):
    criteria = {n: f"{by_name[n].description}. {by_name[n].body[:cfg.excerpt_chars]}" for n in names}
    criteria[NO_MATCH] = NO_MATCH_CRITERIA
    questions = {
        "which": Choice(instructions=RERANK_INSTRUCTIONS, criteria=criteria),
    }
    for n in names:
        questions[f"fits::{n}"] = Noul(
            instructions=(
                f"Does the skill '{n}' do the specific thing the user's request asks "
                f"for? It is described as: {by_name[n].description}"
            )
        )
    return client.system_one(state=_state(intent, context), questions=questions, model=cfg.model)


def route(client: TypeSafeClient, cfg: Config, skills: list[Skill], intent: str, context: str = "") -> Route:
    if not skills:
        return Route(intent, 0.0, {}, [], None, MISSING, "roster: no skills discovered")
    by_name = {s.name: s for s in skills}
    wide = rank_wide(client, cfg, skills, intent, context)
    probs = wide.answers["which"].probabilities
    ranked = [Candidate(n, p) for n, p in sorted(probs.items(), key=lambda kv: -kv[1])][:12]
    values = {
        k.removeprefix("gate::"): a.noul for k, a in wide.answers.items() if k.startswith("gate::")
    }
    oriented = [(1.0 - v) if k in INVERTED else v for k, v in values.items()]
    gate = sum(oriented) / len(oriented)
    usage = {"input_tokens": wide.usage.input_tokens or 0, "output_tokens": wide.usage.output_tokens or 0}

    if gate < cfg.gate_floor:
        return Route(intent, gate, values, ranked, None, NONE_NEEDED,
                     "gate: request does not need a skill", usage, wide.model)
    needs_skill = gate >= cfg.gate_threshold
    required_fit = cfg.fits_threshold if needs_skill else cfg.gray_fits_threshold

    names = [c.name for c in ranked[:cfg.shortlist]]
    second = rerank(client, cfg, by_name, names, intent, context)
    usage["input_tokens"] += second.usage.input_tokens or 0
    usage["output_tokens"] += second.usage.output_tokens or 0
    fits = {k.removeprefix("fits::"): a.noul for k, a in second.answers.items() if k.startswith("fits::")}
    for c in ranked[:cfg.shortlist]:
        c.fits = fits.get(c.name)
    winner = second.answers["which"].choice
    if winner == NO_MATCH or fits.get(winner, 0.0) < required_fit:
        best = max(fits, key=fits.get)
        why = ("no-match chosen" if winner == NO_MATCH
               else f"winner {winner} fits {fits.get(winner, 0.0):.2f} under {required_fit:.2f}")
        outcome = MISSING if needs_skill else NONE_NEEDED
        return Route(intent, gate, values, ranked, None, outcome,
                     f"{why}; nearest {best} at {fits[best]:.2f}", usage, wide.model)
    return Route(intent, gate, values, ranked, winner, MATCHED, "rerank winner", usage, wide.model)


def suggestion_block(r: Route) -> str:
    if r.outcome == MATCHED:
        body = (
            f"Relevant to the current request: {r.winner}. Load it with the Skill tool before "
            "proceeding. Ignore this if it does not fit what the user actually asked for."
        )
    elif r.outcome == MISSING:
        nearest = ", ".join(c.name for c in r.ranked[:3])
        body = (
            "No installed skill covers this request, though it looks like one would help. "
            f"Nearest installed: {nearest}. Proceed without a skill and tell the user a skill "
            "for this is probably worth installing or creating."
        )
    else:
        return ""
    return f"<skill_relevance>\n{body}\n</skill_relevance>"
