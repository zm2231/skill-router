"""Fixed question text shared by the router and the config bounds."""
from typesafe_sdk import NoulCriteria

SCORE_INSTRUCTIONS = (
    "How applicable is this installed skill to the user's latest request? Judge the skill on "
    "its own, against what the request specifically asks for."
)
SCORE_LEVELS = [
    (
        "Unrelated: this skill does not cover the tool, service, format, workflow, or local "
        "convention the request involves."
    ),
    (
        "Adjacent: related domain, but loading this skill would not materially change how the "
        "request is carried out."
    ),
    (
        "Direct: this skill's documented procedure, private integration, or local convention "
        "materially changes how to perform this exact request."
    ),
]
DIRECT = 2

RERANK_INSTRUCTIONS = (
    "Which of these installed skills should be loaded for the user's latest request? Read "
    "what each actually does, not just its name. Pick the no-match option when none of them "
    "contains the specific procedure the request needs, even if one is topically nearby."
)
NO_MATCH = "none-of-these"
NO_MATCH_LABEL = "none"
NO_MATCH_CRITERIA = (
    "None of these skills contains the specific procedure, integration, or convention that "
    "would materially change how to fulfill the request."
)

NEED_INSTRUCTIONS = (
    "Would fulfilling the user's latest request correctly and safely materially require a "
    "specialized, documented procedure, private integration, or local convention, beyond "
    "ordinary reasoning and the ordinary tools an agent already has, even if no installed "
    "skill provides it?"
)
NEED_CRITERIA: NoulCriteria = {
    "true": "A specialized procedure, integration, or convention is materially required.",
    "false": "Ordinary reasoning and ordinary already-available tools suffice.",
}
