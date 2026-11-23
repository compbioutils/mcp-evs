from __future__ import annotations

from fastmcp import FastMCP

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import Release
from ..service import EvsService
from ._args import TerminologyArg


def register(mcp: FastMCP, service: EvsService, run: Runner) -> None:
    @tool(mcp, name="evs_list_releases", title="evs.list_releases", tags={"evs", "metadata"})
    async def evs_list_releases(terminology: TerminologyArg = "ncit") -> Envelope[list[Release]]:
        """List the releases of a terminology that EVS currently serves live, and which one
        this server treats as active. Runs without a release context."""
        return await run("evs_list_releases", lambda inv: service.list_releases(inv, terminology))
