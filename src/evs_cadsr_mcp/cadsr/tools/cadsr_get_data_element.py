from __future__ import annotations

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import DataElement
from ..service import CadsrService
from ._args import PublicId, VersionArg


def register(mcp: FastMCP, service: CadsrService, run: Runner) -> None:
    @tool(mcp, name="cadsr_get_data_element", title="cadsr.get_data_element", tags={"cadsr", "cde"})
    async def cadsr_get_data_element(
        publicId: PublicId,
        version: VersionArg = None,
        include: Annotated[list[Literal["valueDomain", "permissibleValues", "dataElementConcept", "alternateNames", "classificationSchemes", "referenceDocuments"]] | None,
                           Field(description="Sections to include. Default: valueDomain and dataElementConcept (header is always present). "
                                             "permissibleValues inlines all PVs; prefer cadsr_get_permissible_values for large domains.")] = None,
    ) -> Envelope[DataElement]:
        """Retrieve one Common Data Element from caDSR (NCI API 1.0) with its object-class,
        property, representation-term and value-meaning NCIt concept annotations by role.
        Pinned by publicId + version; the first fetch is slow (6-10 s) and then cached."""
        return await run("cadsr_get_data_element", lambda inv: service.get_data_element(inv, publicId, version, include))
