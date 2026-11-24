"""Shared helper for the direct-call check scripts: open a FastMCP client in one of four modes.

    fixtures  in-process server over the test fakes (offline; needs the dev extra for pytest)
    live      in-process server against the real EVS / caDSR APIs
    stdio     spawn ``python -m evs_cadsr_mcp.server.cli serve --transport stdio`` as a
              subprocess, the way Claude Desktop / Claude Code launch it
    http      connect to an already-running Streamable HTTP server (``--url``)

The scripts talk to the server only through the MCP client, so a pass here means the
same tool calls will work for an agent.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

MODES = ("fixtures", "live", "stdio", "http")
PROFILES = ("evs-only", "cadsr-only", "unified")


def add_target_args(parser) -> None:
    parser.add_argument("--mode", choices=MODES, default="stdio", help="how to reach the server (default: stdio)")
    parser.add_argument("--profile", choices=PROFILES, default="evs-only", help="tool profile (ignored for --mode http)")
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp", help="server URL for --mode http")
    parser.add_argument("--python", default=sys.executable, help="interpreter used to spawn the server for --mode stdio")


@asynccontextmanager
async def open_client(mode: str, *, profile: str = "evs-only", url: str | None = None, python: str | None = None) -> AsyncIterator[Any]:
    """Yield an open ``fastmcp.Client`` connected to the server in the requested mode."""
    from fastmcp import Client

    if mode in ("fixtures", "live"):
        from evs_cadsr_mcp.core.config import Settings
        from evs_cadsr_mcp.server.mcp_app import build_mcp_server, build_services

        if mode == "fixtures":
            from tests.conftest import FakeCadsr, FakeEvs  # needs pytest (dev extra)

            settings = Settings(_env_file=None, profile=profile, log_level="WARNING")
            services = build_services(settings, transport=FakeEvs().transport(), cadsr_transport=FakeCadsr().transport())
        else:
            settings = Settings(profile=profile, log_level="WARNING")
            services = build_services(settings)
        server, _ = build_mcp_server(settings, services=services)
        try:
            async with Client(server) as client:
                yield client
        finally:
            await services.aclose()
        return

    if mode == "stdio":
        from fastmcp.client.transports import StdioTransport

        env = {**os.environ, "ECM_PROFILE": profile, "ECM_LOG_LEVEL": os.environ.get("ECM_LOG_LEVEL", "WARNING")}
        transport = StdioTransport(
            command=python or sys.executable,
            args=["-m", "evs_cadsr_mcp.server.cli", "serve", "--transport", "stdio", "--profile", profile],
            env=env,
            cwd=str(ROOT),
        )
        async with Client(transport) as client:
            yield client
        return

    if mode == "http":
        async with Client(url or "http://127.0.0.1:8000/mcp") as client:
            yield client
        return

    raise ValueError(f"unknown mode {mode!r}")


async def call(client, name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Call a tool and return the envelope as a dict. Tool errors raise ``ToolError`` whose
    message is the server's JSON error envelope; use :func:`error_payload` to decode it."""
    res = await client.call_tool(name, args)
    if res.structured_content is not None:
        return res.structured_content
    return json.loads(res.content[0].text)


def error_payload(exc: BaseException) -> dict[str, Any] | str:
    try:
        return json.loads(str(exc))
    except (TypeError, ValueError):
        return str(exc)
