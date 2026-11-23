from __future__ import annotations

from fastmcp import FastMCP

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import MatchBackend
from ..service import CadsrService


def register(mcp: FastMCP, service: CadsrService, run: Runner) -> None:
    @tool(mcp, name="cadsr_list_match_backends", title="cadsr.list_match_backends", tags={"cadsr", "matching"})
    async def cadsr_list_match_backends() -> Envelope[list[MatchBackend]]:
        """Which matching backends this deployment can use (CDE Match 2.0, CDE AI Match engine
        with its embedding variants, VM Match) and why any is unavailable."""
        return await run("cadsr_list_match_backends", service.list_match_backends)
