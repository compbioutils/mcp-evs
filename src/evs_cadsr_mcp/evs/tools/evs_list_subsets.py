from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ...core.context import Invocation
from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import Subset
from ..service import EvsService
from ._args import CODE_PATTERN, ReleaseArg, TerminologyArg


def register(mcp: FastMCP, service: EvsService, run: Runner) -> None:
    @tool(mcp, name="evs_list_subsets", title="evs.list_subsets", tags={"evs", "subsets"},
          output_schema=Envelope[list[Subset]].model_json_schema(mode="serialization"))
    async def evs_list_subsets(
        code: Annotated[str | None, Field(pattern=CODE_PATTERN, description="A subset code to describe; omit to list the top-level subset tree.")] = None,
        terminology: TerminologyArg = "ncit",
        release: ReleaseArg = None,
    ) -> Envelope[list[Subset]]:
        """List NCIt subsets (value sets) as a tree, or describe one subset."""
        async def go(inv: Invocation):
            ctx = await service.release_context(terminology, release)
            return await service.list_subsets(inv, ctx, code, "minimal")
        return await run("evs_list_subsets", go)
