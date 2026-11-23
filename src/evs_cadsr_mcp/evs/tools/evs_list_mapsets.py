from __future__ import annotations

from fastmcp import FastMCP

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import Mapset
from ..service import EvsService


def register(mcp: FastMCP, service: EvsService, run: Runner) -> None:
    @tool(mcp, name="evs_list_mapsets", title="evs.list_mapsets", tags={"evs", "maps"})
    async def evs_list_mapsets() -> Envelope[list[Mapset]]:
        """List EVS mapsets (e.g. NCIt_Maps_To_GDC, NCIt_Maps_To_ICD10CM) with source and
        target terminology and whether a license key is required."""
        return await run("evs_list_mapsets", service.list_mapsets)
