from __future__ import annotations

from typing import Annotated, Literal

from fastmcp import FastMCP
from pydantic import Field

from ...core.context import Invocation
from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import Edge
from ..service import EvsService
from ._args import Code, ReleaseArg, TerminologyArg


def register(mcp: FastMCP, service: EvsService, run: Runner) -> None:
    @tool(mcp, name="evs_get_relationships", title="evs.get_relationships", tags={"evs", "relationships"})
    async def evs_get_relationships(
        code: Code,
        kinds: Annotated[list[Literal["roles", "inverseRoles", "associations", "inverseAssociations", "disjointWith"]],
                         Field(min_length=1, description="Relationship kinds to include.")] = ["roles", "associations"],
        names: Annotated[list[str] | None, Field(description="Restrict to these relationship names, e.g. ['Disease_Has_Finding'].")] = None,
        terminology: TerminologyArg = "ncit",
        release: ReleaseArg = None,
    ) -> Envelope[list[Edge]]:
        """Roles, associations, their inverses and disjointness for a concept. Edges carry
        polarity ('negative' for exclusion roles such as Disease_Excludes_Finding) and
        qualifiers when present."""
        async def go(inv: Invocation):
            ctx = await service.release_context(terminology, release)
            return await service.get_relationships(inv, ctx, code, list(kinds), names)
        return await run("evs_get_relationships", go)
