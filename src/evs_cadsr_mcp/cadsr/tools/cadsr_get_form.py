from __future__ import annotations

from fastmcp import FastMCP

from ...core.envelopes import Envelope
from ...core.toolkit import Runner, tool
from ..models import Form
from ..service import CadsrService
from ._args import PublicId, VersionArg


def register(mcp: FastMCP, service: CadsrService, run: Runner) -> None:
    @tool(mcp, name="cadsr_get_form", title="cadsr.get_form", tags={"cadsr", "forms"})
    async def cadsr_get_form(publicId: PublicId, version: VersionArg = None, includeModules: bool = True) -> Envelope[Form]:
        """A caDSR form (CRF) with modules, questions, their CDEs and valid values (Form API 2.0)."""
        return await run("cadsr_get_form", lambda inv: service.get_form(inv, publicId, version, include_modules=includeModules))
