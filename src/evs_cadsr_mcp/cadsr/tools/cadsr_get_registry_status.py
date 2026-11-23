from __future__ import annotations

from fastmcp import FastMCP

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import RegistryStatus
from ..service import CadsrService


def register(mcp: FastMCP, service: CadsrService, run: Runner) -> None:
    @tool(mcp, name="cadsr_get_registry_status", title="cadsr.get_registry_status", tags={"cadsr", "metadata"})
    async def cadsr_get_registry_status() -> Envelope[RegistryStatus]:
        """What is known about caDSR registry state. caDSR publishes no release identity, so
        this always reports published=false plus the daily export date when a listing is configured."""
        return await run("cadsr_get_registry_status", service.get_registry_status)
