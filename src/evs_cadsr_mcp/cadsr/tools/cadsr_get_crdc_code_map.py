from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import CrdcMapEntry
from ..service import CadsrService


def register(mcp: FastMCP, service: CadsrService, run: Runner) -> None:
    @tool(mcp, name="cadsr_get_crdc_code_map", title="cadsr.get_crdc_code_map", tags={"cadsr", "crdc"})
    async def cadsr_get_crdc_code_map(
        dataElementId: Annotated[str | None, Field(description="Filter to one CDE public id.")] = None,
        limit: Annotated[int, Field(ge=1, le=1000)] = 100,
        cursor: str | None = None,
    ) -> Envelope[list[CrdcMapEntry]]:
        """The CRDC harmonized CDE list / crosswalk (DataElements/getCRDCList), cached and paged."""
        return await run("cadsr_get_crdc_code_map", lambda inv: service.get_crdc_code_map(inv, dataElementId, limit=limit, cursor=cursor))
