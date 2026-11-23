from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ...core.context import Invocation
from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import Concept
from ..service import EvsService
from ._args import Code, IncludeArg, ReleaseArg, TerminologyArg


def register(mcp: FastMCP, service: EvsService, run: Runner) -> None:
    @tool(mcp, name="evs_get_subset_members", title="evs.get_subset_members", tags={"evs", "subsets"})
    async def evs_get_subset_members(
        code: Code,
        include: IncludeArg = None,
        limit: Annotated[int, Field(ge=1, le=1000)] = 100,
        cursor: str | None = None,
        terminology: TerminologyArg = "ncit",
        release: ReleaseArg = None,
    ) -> Envelope[list[Concept]]:
        """Paged members of a subset (value set) at a release. Default include is 'minimal'."""
        async def go(inv: Invocation):
            ctx = await service.release_context(terminology, release)
            return await service.get_subset_members(inv, ctx, code, include=include, limit=limit, cursor=cursor)
        return await run("evs_get_subset_members", go)
