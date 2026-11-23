from __future__ import annotations

from fastmcp import FastMCP

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import ValueDomain
from ..service import CadsrService
from ._args import PublicId, VersionArg


def register(mcp: FastMCP, service: CadsrService, run: Runner) -> None:
    @tool(mcp, name="cadsr_get_value_domain", title="cadsr.get_value_domain", tags={"cadsr", "cde"})
    async def cadsr_get_value_domain(publicId: PublicId, version: VersionArg = None) -> Envelope[ValueDomain]:
        """Value-domain view of a CDE (type, datatype, format, bounds, representation term and
        its concepts, PV count). Derived: caDSR has no value-domain-by-id endpoint."""
        return await run("cadsr_get_value_domain", lambda inv: service.get_value_domain(inv, publicId, version))
