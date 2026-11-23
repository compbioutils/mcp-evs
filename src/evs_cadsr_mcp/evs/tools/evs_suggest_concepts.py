from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ...core.context import Invocation
from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import ConceptRef
from ..service import EvsService
from ._args import ReleaseArg, TerminologyArg


def register(mcp: FastMCP, service: EvsService, run: Runner) -> None:
    @tool(mcp, name="evs_suggest_concepts", title="evs.suggest_concepts", tags={"evs", "search"})
    async def evs_suggest_concepts(
        prefix: Annotated[str, Field(min_length=1)],
        limit: Annotated[int, Field(ge=1, le=20)] = 10,
        terminology: TerminologyArg = "ncit",
        release: ReleaseArg = None,
    ) -> Envelope[list[ConceptRef]]:
        """Typeahead: minimal concept refs whose name or synonym starts with the prefix."""
        async def go(inv: Invocation):
            ctx = await service.release_context(terminology, release)
            return await service.suggest_concepts(inv, ctx, prefix, limit)
        return await run("evs_suggest_concepts", go)
