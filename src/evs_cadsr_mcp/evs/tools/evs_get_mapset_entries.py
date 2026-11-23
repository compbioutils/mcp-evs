from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import MapsetEntries
from ..service import EvsService


def register(mcp: FastMCP, service: EvsService, run: Runner) -> None:
    @tool(mcp, name="evs_get_mapset_entries", title="evs.get_mapset_entries", tags={"evs", "maps"})
    async def evs_get_mapset_entries(
        mapset: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$", description="Mapset code, e.g. NCIt_Maps_To_GDC.")],
        term: Annotated[str | None, Field(description="Optional text filter on source or target names/codes.")] = None,
        limit: Annotated[int, Field(ge=1, le=1000)] = 100,
        cursor: str | None = None,
    ) -> Envelope[MapsetEntries]:
        """Paged map assertions from one mapset. For license-gated targets without a
        configured key, only the assertion count is returned with licenseRequired=true."""
        return await run("evs_get_mapset_entries", lambda inv: service.get_mapset_entries(inv, mapset, term=term, limit=limit, cursor=cursor))
