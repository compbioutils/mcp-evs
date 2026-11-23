from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import PvExplanation
from ..service import MapService
from ._args import PublicId, ReleaseArg


def register(mcp: FastMCP, service: MapService, run: Runner) -> None:
    @tool(mcp, name="map_explain_permissible_value", title="map.explain_permissible_value", tags={"map", "cde", "values"})
    async def map_explain_permissible_value(publicId: PublicId, value: Annotated[str, Field(min_length=1)], version: str | None = None, release: ReleaseArg = None) -> Envelope[PvExplanation]:
        """A permissible value's value meaning, its NCIt concept with definition, synonyms and
        status at the release (and replacement if retired)."""
        return await run("map_explain_permissible_value", lambda inv: service.explain_permissible_value(inv, publicId, version, value, release))
