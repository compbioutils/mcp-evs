from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ...core.context import Invocation
from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import ConceptRef
from ..service import EvsService
from ._args import Code, ReleaseArg, TerminologyArg


def register(mcp: FastMCP, service: EvsService, run: Runner) -> None:
    @tool(mcp, name="evs_get_descendants", title="evs.get_descendants", tags={"evs", "hierarchy"})
    async def evs_get_descendants(
        code: Code,
        maxLevel: Annotated[int | None, Field(ge=1, le=50, description="Deepest level to include (1 = children only).")] = None,
        limit: Annotated[int, Field(ge=1, le=1000)] = 200,
        cursor: str | None = None,
        terminology: TerminologyArg = "ncit",
        release: ReleaseArg = None,
    ) -> Envelope[list[ConceptRef]]:
        """Flat, paged list of descendants with their level. Bound with maxLevel and limit;
        follow page.nextCursor for more."""
        async def go(inv: Invocation):
            ctx = await service.release_context(terminology, release)
            return await service.get_descendants(inv, ctx, code, max_level=maxLevel, limit=limit, cursor=cursor)
        return await run("evs_get_descendants", go)
