from __future__ import annotations

from fastmcp import FastMCP

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import DataElementConcept
from ..service import CadsrService
from ._args import PublicId, VersionArg


def register(mcp: FastMCP, service: CadsrService, run: Runner) -> None:
    @tool(mcp, name="cadsr_get_data_element_concept", title="cadsr.get_data_element_concept", tags={"cadsr", "cde"})
    async def cadsr_get_data_element_concept(publicId: PublicId, version: VersionArg = None) -> Envelope[DataElementConcept]:
        """Data-element-concept view of a CDE: object class and property with their NCIt
        concepts (conceptCodes is the displayOrder-derived 'C25164:C25150' string)."""
        return await run("cadsr_get_data_element_concept", lambda inv: service.get_data_element_concept(inv, publicId, version))
