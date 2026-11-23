"""Register the ``cadsr_*`` tools, resources and prompts (proposal Section 7.2).

caDSR items carry no release; provenance pins them by ``registry {publicId, version,
retrievedAt}``. Paging over derived views is server-side over the cached expanded CDE, and
cursors are bound to ``publicId + version`` so a cursor cannot be replayed against another
item.

One module per tool; each exposes ``register(mcp, service, run)``. Add a tool by
creating its module and listing it in ``TOOLS`` (the order is the ``tools/list`` order).
"""

from __future__ import annotations

from fastmcp import FastMCP

from ...core.config import Settings
from ...core.toolkit import make_runner
from ..service import CadsrService
from . import (
    cadsr_find_data_elements,
    cadsr_find_data_elements_by_concept,
    cadsr_get_crdc_code_map,
    cadsr_get_data_element,
    cadsr_get_data_element_concept,
    cadsr_get_data_element_versions,
    cadsr_get_data_elements,
    cadsr_get_form,
    cadsr_get_forms_for_data_element,
    cadsr_get_permissible_values,
    cadsr_get_registry_status,
    cadsr_get_value_domain,
    cadsr_list_contexts,
    cadsr_list_match_backends,
    cadsr_match_data_elements,
    cadsr_match_value_meanings,
    prompts,
    resources,
)

TOOLS = (
    cadsr_get_data_element,
    cadsr_get_data_elements,
    cadsr_get_data_element_versions,
    cadsr_get_permissible_values,
    cadsr_get_value_domain,
    cadsr_get_data_element_concept,
    cadsr_find_data_elements_by_concept,
    cadsr_find_data_elements,
    cadsr_get_form,
    cadsr_get_forms_for_data_element,
    cadsr_list_contexts,
    cadsr_list_match_backends,
    cadsr_match_data_elements,
    cadsr_match_value_meanings,
    cadsr_get_crdc_code_map,
    cadsr_get_registry_status,
)


def register_cadsr_tools(mcp: FastMCP, service: CadsrService, settings: Settings) -> None:
    run = make_runner(settings)
    for module in TOOLS:
        module.register(mcp, service, run)
    resources.register(mcp, service, run)
    prompts.register(mcp)
