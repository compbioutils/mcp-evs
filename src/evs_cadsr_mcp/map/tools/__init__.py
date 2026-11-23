"""Register the ``map_*`` tools and prompts (proposal Section 8.2).

Cross-domain tools carry one composite budget and one provenance record per source
consulted (EVS live/cache per release, caDSR registry items). Capabilities caDSR lacks
(suggestion ranking, alignment verdicts, lint findings) are declared exceptions and are
labelled in ``meta.exception``.

One module per tool; each exposes ``register(mcp, service, run)``. Add a tool by
creating its module and listing it in ``TOOLS`` (the order is the ``tools/list`` order).
"""

from __future__ import annotations

from fastmcp import FastMCP

from ...core.config import Settings
from ...core.toolkit import make_runner
from ..service import MapService
from . import (
    map_align_value_sets,
    map_assess_release_impact,
    map_crosswalk_properties,
    map_explain_permissible_value,
    map_find_data_elements_for_concept,
    map_map_icdo_to_ncit,
    map_resolve_cde_concepts,
    map_resolve_model_property,
    map_resolve_stored_value,
    map_suggest_cdes_for_term,
    map_validate_model_fragment,
    prompts,
)

TOOLS = (
    map_resolve_cde_concepts,
    map_find_data_elements_for_concept,
    map_explain_permissible_value,
    map_align_value_sets,
    map_resolve_model_property,
    map_suggest_cdes_for_term,
    map_validate_model_fragment,
    map_assess_release_impact,
    map_crosswalk_properties,
    map_map_icdo_to_ncit,
    map_resolve_stored_value,
)


def register_map_tools(mcp: FastMCP, service: MapService, settings: Settings) -> None:
    run = make_runner(settings)
    for module in TOOLS:
        module.register(mcp, service, run)
    prompts.register(mcp)
