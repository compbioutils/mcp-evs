from __future__ import annotations

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import IcdoMapping
from ..service import MapService
from ._args import ReleaseArg


def register(mcp: FastMCP, service: MapService, run: Runner) -> None:
    @tool(mcp, name="map_map_icdo_to_ncit", title="map.map_icdo_to_ncit", tags={"map", "icdo"})
    async def map_map_icdo_to_ncit(
        icdoCode: Annotated[str | None, Field(description="ICD-O-3 morphology '8140/3' or topography 'C34.1'.")] = None,
        term: Annotated[str | None, Field(description="ICD-O term or NCIt name when no code is known, e.g. 'adenocarcinoma'.")] = None,
        axis: Literal["auto", "morphology", "topography"] = "auto",
        includeGroup: bool = False,
        release: ReleaseArg = None,
    ) -> Envelope[list[IcdoMapping]]:
        """ICD-O-3 code or term -> NCIt concept(s) from EVS's published ICD-O-3.1 mapping files
        (downloaded and refreshed daily), with each concept's status checked at the pinned release.
        A code can map to several concepts. Diagnosis-group roll-up needs the ICD-O group table (not configured)."""
        return await run("map_map_icdo_to_ncit", lambda inv: service.map_icdo_to_ncit(inv, icdo_code=icdoCode, term=term, axis=axis, include_group=includeGroup, release=release))
