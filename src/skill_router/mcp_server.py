"""MCP server exposing the router as a tool an agent calls with its intent."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from .client import MissingKeyError
from .config import Config
from .router import suggestion_block
from .service import roster, route_intent

server = MCPServer(
    "skill-router",
    instructions=(
        "Call route_skill with what the user is trying to do before choosing a skill. "
        "It returns at most one skill name that fits, chosen across every skill installed on "
        "this machine, with the runner-ups and their fit scores."
    ),
)


@server.tool()
def route_skill(intent: str, context: str = "", cwd: str = "") -> dict:
    """Pick the one installed skill that fits an intent, or none.

    intent: what the user is trying to do, in their words.
    context: optional recent conversation or task context that sharpens the intent.
    cwd: optional working directory, so project-local skills are included.
    """
    try:
        r = route_intent(intent, context, Path(cwd) if cwd else None)
    except MissingKeyError as exc:
        return {"error": str(exc), "outcome": "error"}
    out = asdict(r)
    out["ranked"] = out["ranked"][:6]
    out["suggestion"] = suggestion_block(r)
    return out


@server.tool()
def list_skills(cwd: str = "") -> list[dict]:
    """Every skill the router can route to: name, harness, and description."""
    skills = roster(Config.load(), Path(cwd) if cwd else None)
    return [{"name": s.name, "harness": s.harness, "description": s.description} for s in skills]


def main() -> None:
    server.run("stdio")
