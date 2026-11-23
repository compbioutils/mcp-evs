from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import FormUsage
from ..service import CadsrService
from ._args import VERSION_PATTERN, PublicId


def register(mcp: FastMCP, service: CadsrService, run: Runner) -> None:
    @tool(mcp, name="cadsr_get_forms_for_data_element", title="cadsr.get_forms_for_data_element", tags={"cadsr", "forms"})
    async def cadsr_get_forms_for_data_element(publicId: PublicId, version: Annotated[str, Field(pattern=VERSION_PATTERN, description="Required: forms are bound to a CDE version.")]) -> Envelope[list[FormUsage]]:
        """Forms whose questions use a given CDE version. Served by the legacy caDSR query DSL,
        the only upstream route for this question."""
        return await run("cadsr_get_forms_for_data_element", lambda inv: service.get_forms_for_data_element(inv, publicId, version))
