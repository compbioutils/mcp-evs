from __future__ import annotations

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import DataElementSummary
from ..service import CadsrService


def register(mcp: FastMCP, service: CadsrService, run: Runner) -> None:
    @tool(mcp, name="cadsr_find_data_elements_by_concept", title="cadsr.find_data_elements_by_concept", tags={"cadsr", "search", "concept"})
    async def cadsr_find_data_elements_by_concept(
        conceptCode: Annotated[str, Field(pattern=r"^C[1-9][0-9]*$", description="NCIt concept code.")],
        itemType: Annotated[Literal["ObjectClass", "Property", "RepresentationTerm", "ValueMeaning"] | None, Field(description="Restrict to CDEs annotated with the concept in this role.")] = None,
        workflowStatus: Annotated[str | None, Field(description="e.g. RELEASED, DRAFT NEW, RETIRED ARCHIVED")] = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 50,
        cursor: str | None = None,
    ) -> Envelope[list[DataElementSummary]]:
        """CDEs annotated with an NCIt concept (native caDSR reverse lookup; the key enabler of
        NCIt-to-CDE mapping). Paged server-side; matchedRole is known only when itemType is set."""
        return await run("cadsr_find_data_elements_by_concept", lambda inv: service.find_data_elements_by_concept(inv, conceptCode, item_type=itemType, workflow_status=workflowStatus, limit=limit, cursor=cursor))
