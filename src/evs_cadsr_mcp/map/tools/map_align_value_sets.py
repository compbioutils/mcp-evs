from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import ValueSetAlignment, ValueSetSide
from ..service import MapService
from ._args import ReleaseArg


def register(mcp: FastMCP, service: MapService, run: Runner) -> None:
    @tool(mcp, name="map_align_value_sets", title="map.align_value_sets", tags={"map", "values", "alignment"})
    async def map_align_value_sets(
        left: Annotated[ValueSetSide, Field(description="One of: {cde:{publicId,version?}} | {values:[...]} | {gdcEnumDef:{...}} | {mdfEnum:[...]}")],
        right: Annotated[ValueSetSide, Field(description="One of: {cde:{publicId,version?}} | {values:[...]} | {ncitSubset:'Cxxxx'} | {gdcEnumDef} | {mdfEnum}")],
        release: ReleaseArg = None,
    ) -> Envelope[ValueSetAlignment]:
        """Align two value sets value by value: exact | synonym | retired | unmapped | ambiguous,
        each with evidence (shared concept, label equality, NCIt synonym, retirement). Declared
        exception: the verdicts are computed here, not by caDSR."""
        return await run("map_align_value_sets", lambda inv: service.align_value_sets(inv, left, right, release))
