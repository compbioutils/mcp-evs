from __future__ import annotations

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import DataElementsForConcept
from ..service import MapService
from ._args import Code, ReleaseArg


def register(mcp: FastMCP, service: MapService, run: Runner) -> None:
    @tool(mcp, name="map_find_data_elements_for_concept", title="map.find_data_elements_for_concept", tags={"map", "concept", "cde"})
    async def map_find_data_elements_for_concept(
        conceptCode: Code,
        release: ReleaseArg = None,
        expandDescendants: Annotated[bool, Field(description="Also look up CDEs for descendant concepts (bounded).")] = False,
        maxLevel: Annotated[int, Field(ge=1, le=10)] = 2,
        maxConcepts: Annotated[int, Field(ge=1, le=100, description="Cap on concepts (root + descendants) queried against caDSR; one caDSR call each.")] = 20,
        itemType: Literal["ObjectClass", "Property", "RepresentationTerm", "ValueMeaning"] | None = None,
    ) -> Envelope[DataElementsForConcept]:
        """NCIt -> CDEs ("which CDEs use C12345?"), grouped by concept, with optional bounded
        descendant expansion. Uses caDSR's native concept lookup; reports truncation."""
        return await run("map_find_data_elements_for_concept", lambda inv: service.find_data_elements_for_concept(
            inv, conceptCode, release, expand=expandDescendants, max_level=maxLevel, max_concepts=maxConcepts, item_type=itemType), max_requests=maxConcepts + 10)
