from __future__ import annotations

from fastmcp import FastMCP

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import Terminology
from ..service import EvsService


def register(mcp: FastMCP, service: EvsService, run: Runner) -> None:
    @tool(mcp, name="evs_list_terminologies", title="evs.list_terminologies", tags={"evs", "metadata"})
    async def evs_list_terminologies() -> Envelope[list[Terminology]]:
        """List the terminologies EVS serves, their latest release, and license status.
        Runs without a release context."""
        return await run("evs_list_terminologies", service.list_terminologies)
