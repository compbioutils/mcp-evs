from __future__ import annotations

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import FindDataElementsResult
from ..service import CadsrService


def register(mcp: FastMCP, service: CadsrService, run: Runner) -> None:
    @tool(mcp, name="cadsr_find_data_elements", title="cadsr.find_data_elements", tags={"cadsr", "search"})
    async def cadsr_find_data_elements(
        query: Annotated[str, Field(min_length=1, description="Name, question text or id fragment.")],
        by: Annotated[list[Literal["alternateName", "questionText", "classification", "context"]], Field(description="Routes to run. Default: alternateName and questionText.")] = ["alternateName", "questionText"],
        exact: bool = False,
        context: Annotated[str | None, Field(description="Context name for the context route, e.g. 'NCIP', 'CTEP'.")] = None,
        classificationSchemePublicId: Annotated[str | None, Field(description="Scheme public id for the classification route.")] = None,
        classificationSchemeVersion: str | None = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 50,
        cursor: str | None = None,
    ) -> Envelope[FindDataElementsResult]:
        """Declared fan-out search. caDSR has no keyword search, so this runs the named lookup
        routes in parallel, de-duplicates, and reports result.coverage (routes run, skipped,
        capped). It is not exhaustive; say so when citing."""
        return await run("cadsr_find_data_elements", lambda inv: service.find_data_elements(
            inv, query, by=list(by), exact=exact, context=context, scheme_id=classificationSchemePublicId, scheme_version=classificationSchemeVersion, limit=limit, cursor=cursor))
