from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ...core.context import Invocation
from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import Selector, TraversalBudget, TraversalResult
from ..service import EvsService
from ._args import ReleaseArg, TerminologyArg


def register(mcp: FastMCP, service: EvsService, run: Runner) -> None:
    @tool(mcp, name="evs_traverse", title="evs.traverse", tags={"evs", "traversal"})
    async def evs_traverse(
        start: Annotated[list[str], Field(min_length=1, max_length=20, description="Start concept codes.")],
        selectors: Annotated[list[Selector], Field(min_length=1, description="Relationship kinds to follow, each optionally restricted to named relationships, "
                                                                           "e.g. [{kind: 'children'}, {kind: 'roles', names: ['Disease_Has_Finding']}].")],
        budget: Annotated[TraversalBudget, Field(description="Bounds: maxDepth (default 2, cap 4), maxNodes (200/1000), maxEdges (1000/5000), "
                                                             "maxRequests (50/200, counts retries), perKind caps.")] = TraversalBudget(),
        includeExclusions: Annotated[bool, Field(description="Follow negative-polarity roles (Disease_Excludes_*). Default false: they are returned under result.exclusions but not expanded.")] = False,
        terminology: TerminologyArg = "ncit",
        release: ReleaseArg = None,
    ) -> Envelope[TraversalResult]:
        """Bounded multi-hop walk over hierarchy, roles and associations. Expansion is batched
        (never per-code), fair across relationship kinds, and stops at the first bound hit;
        `truncation` names that bound. Every edge carries per-hop provenance (depth,
        relationship, direction, polarity, release, sourceUri, qualifiers)."""
        async def go(inv: Invocation):
            ctx = await service.release_context(terminology, release)
            return await service.traverse(inv, ctx, start, selectors, budget, include_exclusions=includeExclusions)
        return await run("evs_traverse", go, max_requests=budget.maxRequests)
