from __future__ import annotations

from fastmcp import FastMCP

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import Crosswalk
from ..service import MapService
from ._args import FragmentArg, ReleaseArg


def register(mcp: FastMCP, service: MapService, run: Runner) -> None:
    @tool(mcp, name="map_crosswalk_properties", title="map.crosswalk_properties", tags={"map", "model", "crosswalk"})
    async def map_crosswalk_properties(left: FragmentArg, right: FragmentArg, release: ReleaseArg = None) -> Envelope[Crosswalk]:
        """Do two model properties (possibly from different models) share a CDE, share NCIt
        concepts, overlap partially, or neither? Each side is one property."""
        return await run("map_crosswalk_properties", lambda inv: service.crosswalk_properties(inv, left, right, release))
