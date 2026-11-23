"""MCP resources for the cadsr_* domain."""

from __future__ import annotations

from fastmcp import FastMCP

from ...core.toolkit import Runner
from ..service import CadsrService


def register(mcp: FastMCP, service: CadsrService, run: Runner) -> None:
    @mcp.resource("cadsr://data-element/{publicId}", name="caDSR data element (latest)", mime_type="application/json")
    async def res_de(publicId: str) -> str:
        env = await run("cadsr_get_data_element", lambda inv: service.get_data_element(inv, publicId, None, None))
        return env.model_dump_json(exclude_none=True)

    @mcp.resource("cadsr://data-element/{publicId}/{version}", name="caDSR data element at version", mime_type="application/json")
    async def res_de_version(publicId: str, version: str) -> str:
        env = await run("cadsr_get_data_element", lambda inv: service.get_data_element(inv, publicId, version, None))
        return env.model_dump_json(exclude_none=True)

    @mcp.resource("cadsr://crosswalk/crdc", name="CRDC CDE crosswalk", mime_type="application/json")
    async def res_crdc() -> str:
        env = await run("cadsr_get_crdc_code_map", lambda inv: service.get_crdc_code_map(inv, None, limit=1000, cursor=None))
        return env.model_dump_json(exclude_none=True)
