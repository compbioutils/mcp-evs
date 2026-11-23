from __future__ import annotations

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from ...core.context import Invocation
from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import Path
from ..service import EvsService
from ._args import CODE_PATTERN, Code, ReleaseArg, TerminologyArg


def register(mcp: FastMCP, service: EvsService, run: Runner) -> None:
    @tool(mcp, name="evs_get_paths", title="evs.get_paths", tags={"evs", "hierarchy"})
    async def evs_get_paths(
        code: Code,
        kind: Annotated[Literal["toRoot", "fromRoot", "toAncestor"], Field(description="Path direction.")] = "toRoot",
        ancestorCode: Annotated[str | None, Field(pattern=CODE_PATTERN, description="Required for kind=toAncestor.")] = None,
        terminology: TerminologyArg = "ncit",
        release: ReleaseArg = None,
    ) -> Envelope[list[Path]]:
        """All hierarchy paths from a concept to the root (or from the root, or to a given
        ancestor). There is no ancestors endpoint in EVS; this is the way to get ancestors."""
        async def go(inv: Invocation):
            ctx = await service.release_context(terminology, release)
            return await service.get_paths(inv, ctx, code, kind, ancestorCode)
        return await run("evs_get_paths", go)
