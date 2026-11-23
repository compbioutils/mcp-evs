from __future__ import annotations

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from ...core.context import Invocation
from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import Match
from ..service import EvsService
from ._args import IncludeArg, ReleaseArg, TerminologyArg


def register(mcp: FastMCP, service: EvsService, run: Runner) -> None:
    @tool(mcp, name="evs_lookup_concept", title="evs.lookup_concept", tags={"evs", "search"})
    async def evs_lookup_concept(
        identifier: Annotated[str, Field(min_length=1, description="A concept code, preferred name, or synonym.")],
        match: Annotated[Literal["exact", "normalized"], Field(description="exact: case-insensitive string equality; normalized: ignore punctuation and whitespace.")] = "normalized",
        synonymSource: Annotated[str | None, Field(description="Restrict synonym matches to a source, e.g. NCI, CDISC, GDC.")] = None,
        termType: Annotated[str | None, Field(description="Restrict synonym matches to a term type, e.g. PT, SY, AB.")] = None,
        include: IncludeArg = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
        terminology: TerminologyArg = "ncit",
        release: ReleaseArg = None,
    ) -> Envelope[list[Match]]:
        """Resolve an identifier to concepts by exact code, exact preferred name, or exact
        synonym. Each match reports matchKind (code | name | synonym). Use evs_search_concepts
        for fuzzy or partial matching."""
        async def go(inv: Invocation):
            ctx = await service.release_context(terminology, release)
            return await service.lookup_concept(inv, ctx, identifier, match=match, synonym_source=synonymSource, term_type=termType, include=include, limit=limit)
        return await run("evs_lookup_concept", go)
