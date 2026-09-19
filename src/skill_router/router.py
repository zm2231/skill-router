"""Two Jev requests per intent: rank every skill and gate, then rerank the shortlist and verify."""
from __future__ import annotations

from dataclasses import dataclass, field

from typesafe_sdk import Choice, Noul, TypeSafeClient

from .roster import Skill

SHORTLIST = 3
WIDE_DESCRIPTION_CHARS = 320
EXCERPT_CHARS = 700
GATE_THRESHOLD = 0.30
FITS_THRESHOLD = 0.30

CHOICE_INSTRUCTIONS = (
    "Which of these skills, if any, is the right one to load to help with the "
    "user's latest request?"
)
RERANK_INSTRUCTIONS = (
    "Exactly one of these skills is the right one to load for the user's latest "
    "request. Which one? Read what each actually does, not just its name."
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


@dataclass
class Route:
    intent: str
    gate: float
    gate_values: dict[str, float]
    ranked: list[Candidate]
    winner: str | None
    reason: str
    usage: dict[str, int] = field(default_factory=dict)
    model: str = ""

    @property
    def shortlist(self) -> list[Candidate]:
        return self.ranked[:SHORTLIST]


def _state(intent: str, context: str) -> dict:
    return {"request": intent, "recent_context": context}


def rank_wide(client: TypeSafeClient, skills: list[Skill], intent: str, context: str):
    questions = {
        "which": Choice(
            instructions=CHOICE_INSTRUCTIONS,
            criteria={s.name: s.description[:WIDE_DESCRIPTION_CHARS] for s in skills},
        )
    }
    for key, text in GATE_QUESTIONS.items():
        questions[f"gate::{key}"] = Noul(instructions=text)
    return client.system_one(state=_state(intent, context), questions=questions)


def rerank(client: TypeSafeClient, by_name: dict[str, Skill], names: list[str], intent: str, context: str):
    questions = {
        "which": Choice(
            instructions=RERANK_INSTRUCTIONS,
            criteria={
                n: f"{by_name[n].description} — {by_name[n].body[:EXCERPT_CHARS]}" for n in names
            },
        )
    }
    for n in names:
        questions[f"fits::{n}"] = Noul(
            instructions=(
                f"Does the skill '{n}' do the specific thing the user's request asks "
                f"for? It is described as: {by_name[n].description}"
            )
        )
    return client.system_one(state=_state(intent, context), questions=questions)


def route(client: TypeSafeClient, skills: list[Skill], intent: str, context: str = "") -> Route:
    by_name = {s.name: s for s in skills}
    wide = rank_wide(client, skills, intent, context)
    probs = wide.answers["which"].probabilities
    ranked = [Candidate(n, p) for n, p in sorted(probs.items(), key=lambda kv: -kv[1])][:12]
    values = {
        k.removeprefix("gate::"): a.noul for k, a in wide.answers.items() if k.startswith("gate::")
    }
    oriented = [(1.0 - v) if k in INVERTED else v for k, v in values.items()]
    gate = sum(oriented) / len(oriented)
    usage = {"input_tokens": wide.usage.input_tokens or 0, "output_tokens": wide.usage.output_tokens or 0}

    if gate < GATE_THRESHOLD:
        return Route(intent, gate, values, ranked, None, "gate: request does not need a skill", usage, wide.model)

    names = [c.name for c in ranked[:SHORTLIST]]
    second = rerank(client, by_name, names, intent, context)
    usage["input_tokens"] += second.usage.input_tokens or 0
    usage["output_tokens"] += second.usage.output_tokens or 0
    fits = {k.removeprefix("fits::"): a.noul for k, a in second.answers.items() if k.startswith("fits::")}
    for c in ranked[:SHORTLIST]:
        c.fits = fits.get(c.name)
    winner = second.answers["which"].choice
    if max(fits.values()) < FITS_THRESHOLD:
        return Route(intent, gate, values, ranked, None, "fits: no shortlisted skill does this", usage, wide.model)
    return Route(intent, gate, values, ranked, winner, "rerank winner", usage, wide.model)


def suggestion_block(r: Route) -> str:
    if not r.winner:
        return ""
    return (
        "<skill_relevance>\n"
        f"Relevant to the current request: {r.winner}. Load it with the Skill tool before "
        "proceeding. Ignore this if it does not fit what the user actually asked for.\n"
        "</skill_relevance>"
    )
