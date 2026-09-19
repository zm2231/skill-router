"""Fixed question text shared by the router and the config bounds."""
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
