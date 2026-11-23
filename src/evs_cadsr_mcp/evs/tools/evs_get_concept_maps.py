from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ...core.context import Invocation
from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import ConceptMaps
from ..service import EvsService
from ._args import Code, ReleaseArg, TerminologyArg


def register(mcp: FastMCP, service: EvsService, run: Runner) -> None:
    @tool(mcp, name="evs_get_concept_maps", title="evs.get_concept_maps", tags={"evs", "maps"})
    async def evs_get_concept_maps(
        code: Code,
        targetTerminology: Annotated[str | None, Field(description="Filter to one target terminology, e.g. GDC, ICD10CM, MedDRA.")] = None,
        terminology: TerminologyArg = "ncit",
        release: ReleaseArg = None,
    ) -> Envelope[ConceptMaps]:
        """Cross-terminology map assertions for a concept. Targets whose terminology requires
        a license key are withheld (listed in result.withheld) unless a key is configured."""
        async def go(inv: Invocation):
            ctx = await service.release_context(terminology, release)
            return await service.get_concept_maps(inv, ctx, code, targetTerminology)
        return await run("evs_get_concept_maps", go)
