from __future__ import annotations

from fastmcp import FastMCP

from ...core.context import Invocation
from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import HistoryEvent
from ..service import EvsService
from ._args import Code, ReleaseArg, TerminologyArg


def register(mcp: FastMCP, service: EvsService, run: Runner) -> None:
    @tool(mcp, name="evs_get_concept_history", title="evs.get_concept_history", tags={"evs", "history"})
    async def evs_get_concept_history(code: Code, terminology: TerminologyArg = "ncit", release: ReleaseArg = None) -> Envelope[list[HistoryEvent]]:
        """History events for a concept (create, modify, merge, retire) and replacement
        concepts for retired codes."""
        async def go(inv: Invocation):
            ctx = await service.release_context(terminology, release)
            return await service.get_concept_history(inv, ctx, code)
        return await run("evs_get_concept_history", go)
