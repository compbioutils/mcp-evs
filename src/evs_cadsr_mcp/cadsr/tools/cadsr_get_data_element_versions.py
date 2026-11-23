from __future__ import annotations

from fastmcp import FastMCP

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import VersionSummary
from ..service import CadsrService
from ._args import PublicId


def register(mcp: FastMCP, service: CadsrService, run: Runner) -> None:
    @tool(mcp, name="cadsr_get_data_element_versions", title="cadsr.get_data_element_versions", tags={"cadsr", "cde"})
    async def cadsr_get_data_element_versions(publicId: PublicId) -> Envelope[list[VersionSummary]]:
        """Version lineage of a CDE (newest first) with workflow status and the latest flag."""
        return await run("cadsr_get_data_element_versions", lambda inv: service.get_data_element_versions(inv, publicId))
