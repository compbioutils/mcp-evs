from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ...core.context import Invocation
from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import Criterion, SubtreeResult, TraversalBudget
from ..service import EvsService
from ._args import Code, ReleaseArg, TerminologyArg


def register(mcp: FastMCP, service: EvsService, run: Runner) -> None:
    @tool(mcp, name="evs_get_subtree", title="evs.get_subtree", tags={"evs", "hierarchy", "traversal"},
          output_schema=Envelope[SubtreeResult].model_json_schema(mode="serialization"))
    async def evs_get_subtree(
        code: Code,
        depth: Annotated[int, Field(ge=0, le=4, description="Levels of children to include below the root.")] = 2,
        criteria: Annotated[list[Criterion], Field(description="Attribute filters marking nodes as matches: kind property (name, value), conceptStatus (value) or semanticType (value).")] = [],
        prune: Annotated[bool, Field(description="Drop branches with no matching node (requires criteria).")] = False,
        budget: TraversalBudget = TraversalBudget(),
        terminology: TerminologyArg = "ncit",
        release: ReleaseArg = None,
    ) -> Envelope[SubtreeResult]:
        """Nested sub-tree of a concept to a depth cap, with each node flagged against the
        criteria (e.g. semanticType='Neoplastic Process', property Neoplastic_Status=Malignant).
        Children are fetched in batches; NCIt is a DAG, so a node appears under its first parent only."""
        async def go(inv: Invocation):
            ctx = await service.release_context(terminology, release)
            return await service.get_subtree(inv, ctx, code, depth, list(criteria), budget, prune=prune)
        return await run("evs_get_subtree", go, max_requests=budget.maxRequests)
