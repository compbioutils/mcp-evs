from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ...core.context import Invocation
from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import BatchConcepts
from ..service import EvsService
from ._args import IncludeArg, ReleaseArg, TerminologyArg


def register(mcp: FastMCP, service: EvsService, run: Runner) -> None:
    @tool(mcp, name="evs_get_concepts", title="evs.get_concepts", tags={"evs", "concept"})
    async def evs_get_concepts(
        codes: Annotated[list[str], Field(min_length=1, max_length=1000, description="Concept codes (<=1000).")],
        include: IncludeArg = None,
        terminology: TerminologyArg = "ncit",
        release: ReleaseArg = None,
    ) -> Envelope[BatchConcepts]:
        """Retrieve many concepts in one batch call (chunked upstream, never per-code fan-out).
        Codes not found at the release are listed in result.missing."""
        async def go(inv: Invocation):
            ctx = await service.release_context(terminology, release)
            return await service.get_concepts(inv, ctx, codes, include)
        return await run("evs_get_concepts", go)
