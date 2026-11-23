from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import ReleaseImpact
from ..service import MapService


def register(mcp: FastMCP, service: MapService, run: Runner) -> None:
    @tool(mcp, name="map_assess_release_impact", title="map.assess_release_impact", tags={"map", "release", "impact"})
    async def map_assess_release_impact(
        fromRelease: Annotated[str, Field(description="Earlier NCIt release, must still be live, e.g. '26.09d'.")],
        toRelease: Annotated[str | None, Field(description="Later release; omit for the active release.")] = None,
        conceptCodes: Annotated[list[str] | None, Field(max_length=200)] = None,
        cdePublicId: str | None = None,
        cdeVersion: str | None = None,
        subset: Annotated[str | None, Field(description="NCIt subset code whose members to check.")] = None,
        lookupDataElements: Annotated[bool, Field(description="For each impacted concept, list the CDEs annotated with it (first 20).")] = True,
    ) -> Envelope[ReleaseImpact]:
        """What changed between two NCIt releases for a set of concepts (given directly, from a
        CDE's annotations, or from a subset): retired, merged (with replacement), renamed, or
        missing in the target release, and which CDEs are affected."""
        scope: dict = {}
        if conceptCodes:
            scope["conceptCodes"] = conceptCodes
        elif cdePublicId:
            scope["cde"] = {"publicId": cdePublicId, "version": cdeVersion}
        elif subset:
            scope["subset"] = subset
        return await run("map_assess_release_impact", lambda inv: service.assess_release_impact(inv, fromRelease, toRelease, scope, lookup_cdes=lookupDataElements), max_requests=100)
