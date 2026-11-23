from __future__ import annotations

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import MatchEntity, MatchResult
from ..service import CadsrService


def register(mcp: FastMCP, service: CadsrService, run: Runner) -> None:
    @tool(mcp, name="cadsr_match_data_elements", title="cadsr.match_data_elements", tags={"cadsr", "matching"})
    async def cadsr_match_data_elements(
        entities: Annotated[list[MatchEntity], Field(min_length=1, max_length=10, description="Headings/variables to match, each with optional description and value list.")],
        backend: Annotated[Literal["cde_match", "ai_engine"], Field(description="cde_match = rule-based CDE Match 2.0 (credentialed); ai_engine = embedding-based CDE AI Match API (if configured).")] = "cde_match",
        matchLimit: Annotated[int, Field(ge=1, le=25)] = 5,
        contexts: Annotated[list[str] | None, Field(description="Restrict candidates to these caDSR contexts.")] = None,
    ) -> Envelope[list[MatchResult]]:
        """Match column headings / questions (and optionally their values) to candidate CDEs
        using a caDSR matching service. Candidates are resolved against NCI API 1.0 before
        being cited. Unavailable backends return capability_unavailable with the reason."""
        return await run("cadsr_match_data_elements", lambda inv: service.match_data_elements(inv, list(entities), match_limit=matchLimit, contexts=contexts, backend=backend))
