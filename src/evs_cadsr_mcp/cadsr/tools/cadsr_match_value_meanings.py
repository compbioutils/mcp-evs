from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import ValueMatch
from ..service import CadsrService


def register(mcp: FastMCP, service: CadsrService, run: Runner) -> None:
    @tool(mcp, name="cadsr_match_value_meanings", title="cadsr.match_value_meanings", tags={"cadsr", "matching", "values"})
    async def cadsr_match_value_meanings(
        values: Annotated[list[str], Field(min_length=1, max_length=10)],
        strictness: Annotated[str | None, Field(description="Backend-specific strictness, e.g. exact | fuzzy.")] = None,
        terminologyScope: Annotated[list[str] | None, Field(description="e.g. ['NCIt']")] = None,
    ) -> Envelope[list[ValueMatch]]:
        """Match value strings to caDSR value meanings via the VM Match service."""
        return await run("cadsr_match_value_meanings", lambda inv: service.match_value_meanings(inv, values, strictness=strictness, scope=terminologyScope))
