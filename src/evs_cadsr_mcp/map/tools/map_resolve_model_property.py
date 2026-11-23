from __future__ import annotations

from fastmcp import FastMCP

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import ModelPropertyMapping
from ..service import MapService
from ._args import FragmentArg, ReleaseArg


def register(mcp: FastMCP, service: MapService, run: Runner) -> None:
    @tool(mcp, name="map_resolve_model_property", title="map.resolve_model_property", tags={"map", "model", "gdc", "mdf"})
    async def map_resolve_model_property(fragment: FragmentArg, release: ReleaseArg = None) -> Envelope[list[ModelPropertyMapping]]:
        """Ground model properties (GDC JSON/YAML or MDF YAML fragment) end to end: read the
        caDSR CDE reference, fetch the CDE, resolve its concepts at the pinned NCIt release, and
        align the property's enum against the CDE's permissible values. Up to 50 properties per call."""
        return await run("map_resolve_model_property", lambda inv: service.resolve_model_property(inv, fragment, release), max_requests=120)
