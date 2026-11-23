from __future__ import annotations

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from ...core.context import Invocation
from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import Criterion, FindConceptsResult
from ..service import EvsService
from ._args import ReleaseArg, TerminologyArg


def register(mcp: FastMCP, service: EvsService, run: Runner) -> None:
    @tool(mcp, name="evs_find_concepts", title="evs.find_concepts", tags={"evs", "search", "sets"})
    async def evs_find_concepts(
        criteria: Annotated[list[Criterion], Field(min_length=1, description=(
            "Criteria: {kind:'property', name, value} | {kind:'term', value, searchType?} | {kind:'subset', value:<code>} | "
            "{kind:'role'|'association', name, targetCode} | {kind:'associationType', name} | "
            "{kind:'conceptStatus'|'semanticType', value} (narrowing only, with AND)."))],
        combinator: Annotated[Literal["AND", "OR"], Field(description="How to combine criteria.")] = "AND",
        limit: Annotated[int, Field(ge=1, le=1000)] = 100,
        cursor: str | None = None,
        terminology: TerminologyArg = "ncit",
        release: ReleaseArg = None,
    ) -> Envelope[FindConceptsResult]:
        """Concept sets by criteria. A planner picks native EVS routes (search for property
        values, text and subsets; inverseRoles/inverseAssociations for relationship targets;
        the terminology-wide associations endpoint for a whole association type) and reports
        the path in result.plan. Combinations only SPARQL can answer return capability_unavailable."""
        async def go(inv: Invocation):
            ctx = await service.release_context(terminology, release)
            return await service.find_concepts(inv, ctx, list(criteria), combinator, limit=limit, cursor=cursor)
        return await run("evs_find_concepts", go)
