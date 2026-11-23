from __future__ import annotations

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from ...core.context import Invocation
from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import MetadataBundle
from ..service import EvsService
from ._args import ReleaseArg, TerminologyArg


def register(mcp: FastMCP, service: EvsService, run: Runner) -> None:
    @tool(mcp, name="evs_get_terminology_metadata", title="evs.get_terminology_metadata", tags={"evs", "metadata"})
    async def evs_get_terminology_metadata(
        kinds: Annotated[list[Literal["roles", "associations", "properties", "qualifiers", "termTypes", "synonymSources",
                                      "definitionSources", "conceptStatuses", "synonymTypes", "definitionTypes"]],
                         Field(min_length=1, description="Metadata kinds to fetch.")],
        terminology: TerminologyArg = "ncit",
        release: ReleaseArg = None,
    ) -> Envelope[MetadataBundle]:
        """Roles, associations, properties, qualifiers, term types, sources and statuses
        defined for a terminology at a release. Use this to learn valid relationship and
        property names before calling evs_get_relationships or evs_search_concepts."""
        async def go(inv: Invocation):
            ctx = await service.release_context(terminology, release)
            return await service.get_terminology_metadata(inv, ctx, list(kinds))
        return await run("evs_get_terminology_metadata", go)
