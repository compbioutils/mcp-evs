"""Register the ``evs_*`` tools, resources and prompts on a FastMCP server.

Tool names use underscores (``evs_get_concept``) rather than the dotted names in the
proposal's catalog, because several MCP clients restrict tool names to
``[A-Za-z0-9_-]``. The dotted name is kept in each tool's ``title``.

One module per tool; each exposes ``register(mcp, service, run)``. Add a tool by
creating its module and listing it in ``TOOLS`` (the order is the ``tools/list`` order).
"""

from __future__ import annotations

from fastmcp import FastMCP

from ...core.config import Settings
from ...core.toolkit import make_runner
from ..service import EvsService
from . import (
    evs_find_concepts,
    evs_get_concept,
    evs_get_concept_history,
    evs_get_concept_maps,
    evs_get_concepts,
    evs_get_descendants,
    evs_get_hierarchy_neighbors,
    evs_get_mapset_entries,
    evs_get_paths,
    evs_get_relationships,
    evs_get_subset_members,
    evs_get_subtree,
    evs_get_terminology_metadata,
    evs_list_mapsets,
    evs_list_releases,
    evs_list_subsets,
    evs_list_terminologies,
    evs_lookup_concept,
    evs_search_concepts,
    evs_suggest_concepts,
    evs_traverse,
    prompts,
    resources,
)

TOOLS = (
    evs_list_terminologies,
    evs_list_releases,
    evs_get_terminology_metadata,
    evs_get_concept,
    evs_get_concepts,
    evs_lookup_concept,
    evs_search_concepts,
    evs_suggest_concepts,
    evs_get_hierarchy_neighbors,
    evs_get_descendants,
    evs_get_paths,
    evs_get_relationships,
    evs_list_subsets,
    evs_get_subset_members,
    evs_get_concept_maps,
    evs_list_mapsets,
    evs_get_mapset_entries,
    evs_get_concept_history,
    evs_traverse,
    evs_get_subtree,
    evs_find_concepts,
)


def register_evs_tools(mcp: FastMCP, service: EvsService, settings: Settings) -> None:
    run = make_runner(settings)
    for module in TOOLS:
        module.register(mcp, service, run)
    resources.register(mcp, service, run)
    prompts.register(mcp)
