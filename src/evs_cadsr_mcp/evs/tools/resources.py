"""MCP resources for the evs_* domain."""

from __future__ import annotations

from fastmcp import FastMCP

from ...core.context import Invocation
from ...core.toolkit import Runner
from ..service import EvsService


def register(mcp: FastMCP, service: EvsService, run: Runner) -> None:
    @mcp.resource("evs://terminologies", name="EVS terminologies", mime_type="application/json")
    async def res_terminologies() -> str:
        env = await run("evs_list_terminologies", service.list_terminologies)
        return env.model_dump_json(exclude_none=True)

    @mcp.resource("evs://ncit/releases", name="NCIt releases", mime_type="application/json")
    async def res_releases() -> str:
        env = await run("evs_list_releases", lambda inv: service.list_releases(inv, "ncit"))
        return env.model_dump_json(exclude_none=True)

    @mcp.resource("evs://ncit/{release}/concept/{code}", name="NCIt concept at release", mime_type="application/json")
    async def res_concept(release: str, code: str) -> str:
        async def go(inv: Invocation):
            ctx = await service.release_context("ncit", None if release in {"active", "latest"} else release)
            return await service.get_concept(inv, ctx, code, ["summary"])
        env = await run("evs_get_concept", go)
        return env.model_dump_json(exclude_none=True)
