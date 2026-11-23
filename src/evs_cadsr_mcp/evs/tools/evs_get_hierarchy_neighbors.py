from __future__ import annotations

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from ...core.context import Invocation
from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import Edge
from ..service import EvsService
from ._args import CODE_PATTERN, ReleaseArg, TerminologyArg


def register(mcp: FastMCP, service: EvsService, run: Runner) -> None:
    @tool(mcp, name="evs_get_hierarchy_neighbors", title="evs.get_hierarchy_neighbors", tags={"evs", "hierarchy"})
    async def evs_get_hierarchy_neighbors(
        direction: Annotated[Literal["parents", "children", "roots"], Field(description="Which neighbours to return.")],
        code: Annotated[str | None, Field(pattern=CODE_PATTERN, description="Concept code; required unless direction is roots.")] = None,
        terminology: TerminologyArg = "ncit",
        release: ReleaseArg = None,
    ) -> Envelope[list[Edge]]:
        """Immediate parents or children of a concept, or the hierarchy roots."""
        async def go(inv: Invocation):
            ctx = await service.release_context(terminology, release)
            return await service.get_hierarchy_neighbors(inv, ctx, code, direction)
        return await run("evs_get_hierarchy_neighbors", go)
