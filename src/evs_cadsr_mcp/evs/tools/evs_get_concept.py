from __future__ import annotations

from fastmcp import FastMCP

from ...core.context import Invocation
from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import Concept
from ..service import EvsService
from ._args import Code, IncludeArg, ReleaseArg, TerminologyArg


def register(mcp: FastMCP, service: EvsService, run: Runner) -> None:
    @tool(mcp, name="evs_get_concept", title="evs.get_concept", tags={"evs", "concept"})
    async def evs_get_concept(code: Code, include: IncludeArg = None, terminology: TerminologyArg = "ncit", release: ReleaseArg = None) -> Envelope[Concept]:
        """Retrieve one concept at a pinned release with provenance. Default include is
        'summary' (synonyms, definitions, properties). Add itemised flags such as
        'parents', 'children', 'roles', 'maps' or 'history' as needed; 'full' is expensive."""
        async def go(inv: Invocation):
            ctx = await service.release_context(terminology, release)
            return await service.get_concept(inv, ctx, code, include)
        return await run("evs_get_concept", go)
