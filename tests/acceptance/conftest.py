"""Acceptance suite (T-ACC, proposal 12; SOW 'unified-profile integration and acceptance').

The same behavioural scenarios run over the MCP client surface in two modes:

* **fixture** (default): the unified profile over the fake EVS/caDSR transports;
* **live** (``ECM_LIVE=1 pytest tests/acceptance -m live``): the unified profile against
  the real upstreams.

Scenarios assert the contract (envelope shape, provenance, release pinning, truncation,
error codes), not upstream content, except for a few stable anchors (C3224 is Melanoma,
caDSR 2192199 is the race CDE). Mode-specific identifiers live in :class:`Expect`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import pytest
from fastmcp import Client

from evs_cadsr_mcp.core.config import Settings
from evs_cadsr_mcp.server.mcp_app import build_mcp_server, build_services

LIVE = bool(os.environ.get("ECM_LIVE"))


@dataclass(frozen=True)
class Expect:
    mode: str
    subset_with_members: str      # a subset whose members include melanoma-ish concepts
    gdc_mapset: str = "NCIt_Maps_To_GDC"
    race_cde: str = "2192199"
    race_cde_version: str = "1.0"
    min_race_pvs: int = 5
    icdo_morphology: str = "8140/3"
    icdo_expected: str = "C2852"


@pytest.fixture
def expect() -> Expect:
    return Expect(mode="live", subset_with_members="C54459") if LIVE else Expect(mode="fixture", subset_with_members="C177537")


@pytest.fixture
async def acc(unified_settings: Settings, fake_evs, fake_cadsr):
    """An open MCP client over the unified profile in the selected mode."""
    if LIVE:
        settings = Settings(_env_file=None, profile="unified", log_level="WARNING")
        services = build_services(settings)
    else:
        settings = unified_settings
        services = build_services(settings, transport=fake_evs.transport(), cadsr_transport=fake_cadsr.transport())
    mcp, _ = build_mcp_server(settings, services=services)
    try:
        async with Client(mcp) as client:
            yield client
    finally:
        await services.aclose()


def pytest_collection_modifyitems(config, items):
    """In live mode every acceptance test is also a 'live' test, so `-m live` selects it."""
    if LIVE:
        for item in items:
            if "acceptance" in str(item.fspath):
                item.add_marker(pytest.mark.live)
