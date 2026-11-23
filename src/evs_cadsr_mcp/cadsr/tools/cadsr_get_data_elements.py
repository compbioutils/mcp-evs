from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import BatchDataElements
from ..service import CadsrService
from ._args import DataElementId


def register(mcp: FastMCP, service: CadsrService, run: Runner) -> None:
    @tool(mcp, name="cadsr_get_data_elements", title="cadsr.get_data_elements", tags={"cadsr", "cde"})
    async def cadsr_get_data_elements(
        ids: Annotated[list[DataElementId], Field(min_length=1, max_length=20, description="Up to 20 {publicId, version?} pairs.")],
    ) -> Envelope[BatchDataElements]:
        """Retrieve several CDEs. caDSR has no batch endpoint, so this is one upstream call per
        id (documented, bounded at 20). Unknown ids are listed in result.missing."""
        return await run("cadsr_get_data_elements", lambda inv: service.get_data_elements(inv, [i.model_dump() for i in ids]))
