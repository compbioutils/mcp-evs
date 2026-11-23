"""MCP conformance: tools/list, structured output, error envelopes, resources and prompts,
exercised through the in-process FastMCP client."""

from __future__ import annotations

import json

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

EXPECTED_TOOLS = {
    "evs_list_terminologies", "evs_list_releases", "evs_get_terminology_metadata",
    "evs_get_concept", "evs_get_concepts", "evs_lookup_concept", "evs_search_concepts", "evs_suggest_concepts",
    "evs_get_hierarchy_neighbors", "evs_get_descendants", "evs_get_paths", "evs_get_relationships",
    "evs_list_subsets", "evs_get_subset_members",
    "evs_get_concept_maps", "evs_list_mapsets", "evs_get_mapset_entries",
    "evs_get_concept_history",
    "evs_traverse", "evs_get_subtree", "evs_find_concepts",
}


async def test_tools_list_is_complete_and_read_only(mcp):
    async with Client(mcp) as client:
        tools = await client.list_tools()
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOLS
    for t in tools:
        assert t.annotations is not None and t.annotations.readOnlyHint is True, t.name
        assert t.description, t.name
        assert t.outputSchema is not None, t.name
        assert {"result", "provenance", "meta"} <= set(t.outputSchema.get("properties", {})), t.name


async def test_recursive_output_schemas_keep_child_references(mcp):
    async with Client(mcp) as client:
        tools = {t.name: t for t in await client.list_tools()}
    subset = tools["evs_list_subsets"].outputSchema["$defs"]["Subset"]
    children = subset["properties"]["children"]["anyOf"]
    assert any(branch.get("items", {}).get("$ref") == "#/$defs/Subset" for branch in children)
    tree = tools["evs_get_subtree"].outputSchema["$defs"]["TreeNode"]
    assert tree["properties"]["children"]["items"]["$ref"] == "#/$defs/TreeNode"


async def test_get_concept_returns_envelope(mcp, fake_evs):
    async with Client(mcp) as client:
        res = await client.call_tool("evs_get_concept", {"code": "C3224"})
    data = res.structured_content if res.structured_content is not None else json.loads(res.content[0].text)
    assert data["result"]["code"] == "C3224"
    assert data["result"]["release"] == fake_evs.active
    assert data["provenance"][0]["release"] == fake_evs.active
    assert data["provenance"][0]["source"] == "evs_rest"
    assert data["meta"]["tool"] == "evs_get_concept" and data["meta"]["outboundRequests"] == 1


async def test_error_is_tool_error_with_json_envelope(mcp):
    async with Client(mcp) as client:
        with pytest.raises(ToolError) as ei:
            await client.call_tool("evs_get_concept", {"code": "C3224", "release": "25.01d"})
    body = json.loads(str(ei.value))
    assert body["error"]["code"] == "release_not_available"
    assert body["error"]["correlationId"]


async def test_invalid_code_pattern_rejected_by_schema(mcp):
    async with Client(mcp) as client:
        with pytest.raises(ToolError):
            await client.call_tool("evs_get_concept", {"code": "melanoma"})


async def test_resources_and_prompts_registered(mcp, fake_evs):
    async with Client(mcp) as client:
        resources = await client.list_resources()
        templates = await client.list_resource_templates()
        prompts = await client.list_prompts()
        rel = await client.read_resource("evs://ncit/releases")
    assert {str(r.uri) for r in resources} == {"evs://terminologies", "evs://ncit/releases"}
    assert any("concept/{code}" in t.uriTemplate for t in templates)
    assert {p.name for p in prompts} == {"resolve_term_with_provenance", "walk_to_root", "expand_value_set", "map_across_terminologies", "expand_cohort_terms"}
    payload = json.loads(rel[0].text)
    assert payload["result"][0]["version"] == fake_evs.active


async def test_traverse_tool_accepts_nested_models_and_reports_truncation(mcp):
    async with Client(mcp) as client:
        res = await client.call_tool(
            "evs_traverse",
            {"start": ["C3224"], "selectors": [{"kind": "children"}, {"kind": "roles"}], "budget": {"maxDepth": 1, "maxEdges": 4}},
        )
    data = res.structured_content if res.structured_content is not None else json.loads(res.content[0].text)
    assert data["truncation"]["bound"] == "maxEdges"
    assert len(data["result"]["edges"]) == 4 and data["result"]["edges"][0]["hop"]["release"]
    assert data["meta"]["outboundRequests"] == 2


async def test_find_concepts_tool_capability_unavailable_carries_plan(mcp):
    async with Client(mcp) as client:
        with pytest.raises(ToolError) as ei:
            await client.call_tool(
                "evs_find_concepts",
                {"criteria": [{"kind": "property", "name": "A", "value": "1"}, {"kind": "property", "name": "B", "value": "2"}]},
            )
    body = json.loads(str(ei.value))
    assert body["error"]["code"] == "capability_unavailable"
    assert body["error"]["details"]["plan"]["path"] == "sparql_required"


CADSR_TOOLS = {
    "cadsr_get_data_element", "cadsr_get_data_elements", "cadsr_get_data_element_versions", "cadsr_get_permissible_values",
    "cadsr_get_value_domain", "cadsr_get_data_element_concept", "cadsr_find_data_elements_by_concept", "cadsr_find_data_elements",
    "cadsr_get_form", "cadsr_get_forms_for_data_element", "cadsr_list_contexts", "cadsr_list_match_backends",
    "cadsr_match_data_elements", "cadsr_match_value_meanings", "cadsr_get_crdc_code_map", "cadsr_get_registry_status",
}


MAP_TOOLS = {
    "map_resolve_cde_concepts", "map_find_data_elements_for_concept", "map_explain_permissible_value", "map_align_value_sets",
    "map_resolve_model_property", "map_suggest_cdes_for_term", "map_validate_model_fragment", "map_assess_release_impact",
    "map_crosswalk_properties", "map_map_icdo_to_ncit", "map_resolve_stored_value",
}


async def test_profile_matrix_evs_only_hides_cadsr(mcp):
    async with Client(mcp) as client:
        names = {t.name for t in await client.list_tools()}
    assert names == EXPECTED_TOOLS and not (names & (CADSR_TOOLS | MAP_TOOLS))


async def test_unified_profile_lists_both_namespaces(unified_mcp):
    async with Client(unified_mcp) as client:
        tools = await client.list_tools()
        resources = await client.list_resources()
        prompts = await client.list_prompts()
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOLS | CADSR_TOOLS | MAP_TOOLS and len(names) == 48
    for t in tools:
        assert t.annotations.readOnlyHint is True and t.outputSchema is not None, t.name
    assert "cadsr://crosswalk/crdc" in {str(r.uri) for r in resources}
    assert {"find_cde_for_question", "map_columns_to_cdes", "ground_gdc_property", "align_enum_to_cde", "harmonize_data_dictionary", "release_impact_review"} <= {p.name for p in prompts}


async def test_cadsr_get_data_element_over_mcp(unified_mcp):
    async with Client(unified_mcp) as client:
        res = await client.call_tool("cadsr_get_data_element", {"publicId": "2192199", "version": "1.0", "include": ["permissibleValues"]})
    data = res.structured_content if res.structured_content is not None else json.loads(res.content[0].text)
    assert data["result"]["longName"] == "Race Category Text"
    assert len(data["result"]["valueDomain"]["permissibleValues"]) == 8
    assert data["provenance"][0]["registry"]["publicId"] == "2192199"


async def test_cadsr_capability_unavailable_is_tool_error(unified_mcp):
    async with Client(unified_mcp) as client:
        with pytest.raises(ToolError) as ei:
            await client.call_tool("cadsr_list_contexts", {})
        body = json.loads(str(ei.value))
        assert body["error"]["code"] == "capability_unavailable"
        assert "cadsr_find_data_elements" in body["error"]["hint"]  # points at tools that need no credential
        with pytest.raises(ToolError):
            await client.call_tool("cadsr_get_data_element", {"publicId": "not-a-number"})


async def test_map_resolve_cde_concepts_over_mcp(unified_mcp):
    async with Client(unified_mcp) as client:
        res = await client.call_tool("map_resolve_cde_concepts", {"publicId": "2192199", "version": "1.0", "includePermissibleValues": True})
    data = res.structured_content if res.structured_content is not None else json.loads(res.content[0].text)
    assert data["result"]["summary"] == {"active": 10, "retired": 1}
    assert {p["source"] for p in data["provenance"]} == {"cadsr_nciapi", "evs_rest"}


async def test_map_align_over_mcp_labels_declared_exception(unified_mcp):
    async with Client(unified_mcp) as client:
        res = await client.call_tool("map_align_value_sets", {"left": {"values": ["White", "Martian"]}, "right": {"cde": {"publicId": "2192199"}}})
    data = res.structured_content if res.structured_content is not None else json.loads(res.content[0].text)
    assert data["result"]["summary"] == {"exact": 1, "unmapped": 1} and data["meta"]["exception"]
