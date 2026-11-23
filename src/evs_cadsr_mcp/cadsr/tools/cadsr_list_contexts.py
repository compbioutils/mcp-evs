from __future__ import annotations

from fastmcp import FastMCP

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import Context
from ..service import CadsrService


def register(mcp: FastMCP, service: CadsrService, run: Runner) -> None:
    @tool(mcp, name="cadsr_list_contexts", title="cadsr.list_contexts", tags={"cadsr", "metadata"})
    async def cadsr_list_contexts() -> Envelope[list[Context]]:
        """caDSR context names (LOV API). Requires a configured caDSR credential; otherwise
        returns capability_unavailable with the reason."""
        return await run("cadsr_list_contexts", service.list_contexts)
