from __future__ import annotations

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import CdeSuggestion
from ..service import MapService
from ._args import ReleaseArg


def register(mcp: FastMCP, service: MapService, run: Runner) -> None:
    @tool(mcp, name="map_suggest_cdes_for_term", title="map.suggest_cdes_for_term", tags={"map", "cde", "suggest"})
    async def map_suggest_cdes_for_term(
        term: Annotated[str, Field(min_length=1, description="Property/column name or phrase.")],
        description: str | None = None,
        sampleValues: Annotated[list[str] | None, Field(max_length=50)] = None,
        contexts: list[str] | None = None,
        limit: Annotated[int, Field(ge=1, le=25)] = 5,
        backend: Annotated[Literal["cde_match", "ai_engine", "native"] | None, Field(description="Force a backend; default: a configured caDSR matcher if any, else the native concept route.")] = None,
        release: ReleaseArg = None,
    ) -> Envelope[list[CdeSuggestion]]:
        """Candidate CDEs for a term or column with an evidence chain (declared exception: the
        ranking is this server's). Uses a caDSR matching service when configured; otherwise
        term -> NCIt concepts -> CDEs annotated with them -> permissible-value overlap."""
        return await run("map_suggest_cdes_for_term", lambda inv: service.suggest_cdes_for_term(
            inv, term, description=description, sample_values=sampleValues, contexts=contexts, limit=limit, backend=None if backend == "native" else backend, release=release))
