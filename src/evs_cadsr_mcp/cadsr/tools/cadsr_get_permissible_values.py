from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import PermissibleValue
from ..service import CadsrService
from ._args import PublicId, VersionArg


def register(mcp: FastMCP, service: CadsrService, run: Runner) -> None:
    @tool(mcp, name="cadsr_get_permissible_values", title="cadsr.get_permissible_values", tags={"cadsr", "cde", "values"})
    async def cadsr_get_permissible_values(
        publicId: PublicId,
        version: VersionArg = None,
        limit: Annotated[int, Field(ge=1, le=1000)] = 100,
        cursor: str | None = None,
    ) -> Envelope[list[PermissibleValue]]:
        """Permissible values of a CDE's value domain with their value meanings and NCIt
        concepts, paged server-side over the cached CDE. Non-enumerated domains return none."""
        return await run("cadsr_get_permissible_values", lambda inv: service.get_permissible_values(inv, publicId, version, limit=limit, cursor=cursor))
