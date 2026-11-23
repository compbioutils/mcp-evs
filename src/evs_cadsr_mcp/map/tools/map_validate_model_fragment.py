from __future__ import annotations

from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from pydantic import Field

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..service import MapService
from ._args import FragmentArg, ReleaseArg


def register(mcp: FastMCP, service: MapService, run: Runner) -> None:
    @tool(mcp, name="map_validate_model_fragment", title="map.validate_model_fragment", tags={"map", "model", "lint"})
    async def map_validate_model_fragment(
        fragment: FragmentArg,
        release: ReleaseArg = None,
        mode: Annotated[Literal["findings", "report"], Field(description="findings: flat list; report: with counts and release.")] = "report",
    ) -> Envelope[Any]:
        """Lint a model fragment: stale CDE versions, missing or unknown CDEs, NCIt codes invalid
        or retired at the pinned release, enum values absent from or disagreeing with the CDE's
        permissible values. Severity error | warning | info with suggestions."""
        return await run("map_validate_model_fragment", lambda inv: service.validate_model_fragment(inv, fragment, release, mode=mode), max_requests=120)
