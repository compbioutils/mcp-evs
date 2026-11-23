from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import StoredValues
from ..service import MapService
from ._args import Code, ReleaseArg


def register(mcp: FastMCP, service: MapService, run: Runner) -> None:
    @tool(mcp, name="map_resolve_stored_value", title="map.resolve_stored_value", tags={"map", "gdc", "values"})
    async def map_resolve_stored_value(conceptCode: Code, commons: Annotated[str, Field(description="Only 'gdc' is supported.")] = "gdc", release: ReleaseArg = None) -> Envelope[StoredValues]:
        """The string a commons stores for an NCIt concept (GDC: via the NCIt_Maps_To_GDC mapset)."""
        return await run("map_resolve_stored_value", lambda inv: service.resolve_stored_value(inv, conceptCode, commons, release))
