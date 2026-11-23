from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from pydantic import Field

from ...core.context import Invocation
from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import SearchHit
from ..service import EvsService, SearchType
from ._args import CODE_PATTERN, IncludeArg, ReleaseArg, TerminologyArg


def register(mcp: FastMCP, service: EvsService, run: Runner) -> None:
    @tool(mcp, name="evs_search_concepts", title="evs.search_concepts", tags={"evs", "search"})
    async def evs_search_concepts(
        term: Annotated[str | None, Field(description="Search text. Optional when a filter is given: "
                                                     "e.g. property='ICD-O-3_Code' with value='8140/3' alone finds C2852. "
                                                     "Given together, the term AND every filter must match.")] = None,
        type: Annotated[SearchType, Field(description="EVS match type: contains | match | startsWith | phrase | AND | OR | fuzzy.")] = "contains",
        include: IncludeArg = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
        cursor: Annotated[str | None, Field(description="Opaque cursor from a previous page.")] = None,
        conceptStatus: Annotated[str | None, Field(description="e.g. Retired_Concept, Header_Concept")] = None,
        property: Annotated[str | None, Field(description="Property name to filter on, e.g. ICD-O-3_Code (use with value).")] = None,
        value: Annotated[str | None, Field(description="Property value to filter on.")] = None,
        synonymSource: str | None = None,
        synonymTermType: str | None = None,
        definitionSource: str | None = None,
        subset: Annotated[str | None, Field(pattern=CODE_PATTERN, description="Subset code to restrict results to, e.g. C54459.")] = None,
        semanticType: Annotated[str | None, Field(description="Semantic type filter, e.g. 'Neoplastic Process' (applied as property Semantic_Type, so not combinable with property/value).")] = None,
        terminology: TerminologyArg = "ncit",
        release: ReleaseArg = None,
    ) -> Envelope[list[SearchHit]]:
        """Full-text search over EVS (upstream Elasticsearch) with EVS filters. Give a term,
        filters, or both (both must match). Paged; follow page.nextCursor for more.
        Default include is 'minimal' to keep pages small."""
        async def go(inv: Invocation):
            ctx = await service.release_context(terminology, release)
            filters = {"conceptStatus": conceptStatus, "property": property, "value": value, "synonymSource": synonymSource,
                       "synonymTermType": synonymTermType, "definitionSource": definitionSource, "subset": subset, "semanticType": semanticType}
            return await service.search_concepts(inv, ctx, term, search_type=type, include=include, limit=limit, cursor=cursor, filters=filters)
        return await run("evs_search_concepts", go)
