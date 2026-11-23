from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import CdeConceptMap
from ..service import MapService
from ._args import PublicId, ReleaseArg


def register(mcp: FastMCP, service: MapService, run: Runner) -> None:
    @tool(mcp, name="map_resolve_cde_concepts", title="map.resolve_cde_concepts", tags={"map", "cde", "concept"})
    async def map_resolve_cde_concepts(
        publicId: PublicId,
        version: str | None = None,
        release: ReleaseArg = None,
        includePermissibleValues: Annotated[bool, Field(description="Also resolve each permissible value's value-meaning concept.")] = False,
    ) -> Envelope[CdeConceptMap]:
        """CDE -> NCIt at a pinned release. Every concept annotation (object class, property,
        representation term, optionally value meanings) is resolved against EVS: name,
        status at the release (active | retired | not_found), replacement when retired, and
        whether caDSR's name agrees with NCIt."""
        return await run("map_resolve_cde_concepts", lambda inv: service.resolve_cde_concepts(inv, publicId, version, release, include_pvs=includePermissibleValues))
