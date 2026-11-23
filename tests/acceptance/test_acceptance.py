"""Acceptance scenarios over the MCP tool surface (fixture and live modes; see conftest)."""

from __future__ import annotations

import json

import pytest
from fastmcp.exceptions import ToolError


async def call(client, name, args):
    res = await client.call_tool(name, args)
    return res.structured_content if res.structured_content is not None else json.loads(res.content[0].text)


async def error(client, name, args) -> dict:
    with pytest.raises(ToolError) as ei:
        await client.call_tool(name, args)
    return json.loads(str(ei.value))["error"]


def assert_envelope(data: dict, *, tool: str) -> None:
    assert set(data) >= {"result", "provenance", "warnings", "meta"}
    assert data["meta"]["tool"] == tool and data["meta"]["correlationId"]
    assert isinstance(data["provenance"], list)


# ---------------------------------------------------------------- SOW-T1: lookup
async def test_t1_lookup_by_code_name_synonym(acc):
    for ident, kind in (("C3224", "code"), ("Melanoma", "name")):
        data = await call(acc, "evs_lookup_concept", {"identifier": ident})
        assert_envelope(data, tool="evs_lookup_concept")
        assert data["result"] and data["result"][0]["concept"]["code"] == "C3224" and data["result"][0]["matchKind"] == kind
    syn = await call(acc, "evs_lookup_concept", {"identifier": "NSCLC"})
    assert syn["result"] and syn["result"][0]["concept"]["code"] == "C2926" and syn["result"][0]["matchKind"] in ("synonym", "name")


# -------------------------------------------------------- SOW-T2 (live part): search
async def test_t2_full_text_and_typeahead(acc):
    data = await call(acc, "evs_search_concepts", {"term": "melanoma", "limit": 3})
    assert_envelope(data, tool="evs_search_concepts")
    assert len(data["result"]) <= 3 and data["page"]["limit"] == 3
    assert any(h["concept"]["code"] == "C3224" for h in data["result"])
    rel = {p["release"] for p in data["provenance"] if p.get("release")}
    assert len(rel) == 1  # one pinned release per answer
    sugg = await call(acc, "evs_suggest_concepts", {"prefix": "melan", "limit": 5})
    assert sugg["result"] and all("code" in r for r in sugg["result"])


# ------------------------------------------------------------- SOW-T3: traversal
async def test_t3_bounded_traversal_with_truncation_and_hop_provenance(acc):
    data = await call(acc, "evs_traverse", {"start": ["C3224"], "selectors": [{"kind": "children"}, {"kind": "roles"}], "budget": {"maxDepth": 1, "maxEdges": 4}})
    assert_envelope(data, tool="evs_traverse")
    r = data["result"]
    assert len(r["edges"]) <= 4 and r["stats"]["requests"] >= 1
    assert data["truncation"] and data["truncation"]["occurred"] and data["truncation"]["bound"]
    for e in r["edges"]:
        hop = e["hop"]
        assert hop["depth"] == 1 and hop["direction"] in ("outgoing", "incoming") and hop["polarity"] in ("positive", "negative")
        assert hop["release"] and hop["sourceUri"]
        assert hop.get("qualifiers") is None or isinstance(hop["qualifiers"], list)  # present, or explicitly null/omitted
    assert data["meta"]["outboundRequests"] <= 4  # batched, never per-code fan-out


# ---------------------------------------------------- SOW-T4: content of a concept
async def test_t4_synonyms_definitions_properties_associations(acc):
    data = await call(acc, "evs_get_concept", {"code": "C3224", "include": ["summary", "associations", "parents"]})
    assert_envelope(data, tool="evs_get_concept")
    c = data["result"]
    assert c["name"] == "Melanoma" and c["synonyms"] and c["definitions"] and c["properties"] and c["parents"]
    assert c["release"] == data["provenance"][0]["release"]
    batch = await call(acc, "evs_get_concepts", {"codes": ["C3224", "C2926"], "include": ["minimal"]})
    assert {x["code"] for x in batch["result"]["concepts"]} == {"C3224", "C2926"} and batch["meta"]["outboundRequests"] == 1


# -------------------------------------------------------- SOW-T5: concept sets
async def test_t5_concept_sets_by_criteria(acc):
    data = await call(acc, "evs_find_concepts", {"criteria": [{"kind": "property", "name": "Neoplastic_Status", "value": "Malignant"}], "limit": 5})
    assert_envelope(data, tool="evs_find_concepts")
    assert data["result"]["plan"]["path"] == "single_route" and data["result"]["plan"]["steps"][0]["route"] == "search"
    assert data["page"]["limit"] == 5
    err = await error(acc, "evs_find_concepts", {"criteria": [{"kind": "property", "name": "A", "value": "1"}, {"kind": "property", "name": "B", "value": "2"}]})
    assert err["code"] == "capability_unavailable" and err["details"]["plan"]["path"] == "sparql_required"


# ------------------------------------------------------------- SOW-T6: subsets
async def test_t6_subset_membership(acc, expect):
    subsets = await call(acc, "evs_list_subsets", {})
    assert subsets["result"] and all("code" in s for s in subsets["result"])
    members = await call(acc, "evs_get_subset_members", {"code": expect.subset_with_members, "limit": 5})
    assert_envelope(members, tool="evs_get_subset_members")
    assert members["result"] and members["page"]["limit"] == 5


# ------------------------------------------------------------- SOW-T7: subtrees
async def test_t7_targeted_subtree(acc):
    data = await call(acc, "evs_get_subtree", {"code": "C3224", "depth": 1, "criteria": [{"kind": "semanticType", "value": "Neoplastic Process"}]})
    assert_envelope(data, tool="evs_get_subtree")
    root = data["result"]["root"]
    assert root["code"] == "C3224" and root["matches"] is True and root["children"]
    assert data["result"]["matchCount"] >= 1


# --------------------------------------------------- SOW-T8: cross maps + license
async def test_t8_cross_maps_and_license_gate(acc, expect):
    maps = await call(acc, "evs_get_concept_maps", {"code": "C3224"})
    assert_envelope(maps, tool="evs_get_concept_maps")
    assert "MedDRA" not in {m["targetTerminology"] for m in maps["result"]["maps"]}  # withheld without a key
    mapsets = await call(acc, "evs_list_mapsets", {})
    assert any(m["code"] == expect.gdc_mapset for m in mapsets["result"])
    gated = [m for m in mapsets["result"] if m["licenseRequired"]]
    if gated:
        entries = await call(acc, "evs_get_mapset_entries", {"mapset": gated[0]["code"], "limit": 5})
        assert entries["result"]["licenseRequired"] is True and entries["result"]["entries"] == []


# ---------------------------------------------- SOW-S11: release identity fails closed
async def test_s11_release_pinning_fails_closed(acc):
    rels = await call(acc, "evs_list_releases", {})
    live = [r["version"] for r in rels["result"]]
    active = next(r["version"] for r in rels["result"] if r["active"])
    assert active in live
    pinned = await call(acc, "evs_get_concept", {"code": "C3224", "release": active})
    assert pinned["result"]["release"] == active and pinned["provenance"][0]["release"] == active
    err = await error(acc, "evs_get_concept", {"code": "C3224", "release": "20.01d"})
    assert err["code"] == "release_not_available" and err["details"]["live"]
    cursor_err = await error(acc, "evs_search_concepts", {"term": "melanoma", "cursor": "bm90LWEtY3Vyc29y"})
    assert cursor_err["code"] in ("cursor_expired", "invalid_request")


# ------------------------------------------------------ caDSR + unified (UC-1/3/4)
async def test_uc1_cde_to_ncit_and_enum_alignment(acc, expect):
    cde = await call(acc, "cadsr_get_data_element", {"publicId": expect.race_cde, "version": expect.race_cde_version})
    assert_envelope(cde, tool="cadsr_get_data_element")
    assert cde["result"]["publicId"] == expect.race_cde and cde["provenance"][0]["registry"]["publicId"] == expect.race_cde
    pvs = await call(acc, "cadsr_get_permissible_values", {"publicId": expect.race_cde, "version": expect.race_cde_version, "limit": 100})
    assert len(pvs["result"]) >= expect.min_race_pvs and pvs["page"]["total"] >= expect.min_race_pvs
    resolved = await call(acc, "map_resolve_cde_concepts", {"publicId": expect.race_cde, "version": expect.race_cde_version, "includePermissibleValues": True})
    assert_envelope(resolved, tool="map_resolve_cde_concepts")
    assert {p["source"] for p in resolved["provenance"]} >= {"cadsr_nciapi", "evs_rest"}
    assert resolved["result"]["property"] and sum(resolved["result"]["summary"].values()) >= expect.min_race_pvs
    align = await call(acc, "map_align_value_sets", {"left": {"values": ["White", "Asian", "Martian"]}, "right": {"cde": {"publicId": expect.race_cde, "version": expect.race_cde_version}}})
    by = {a["value"]: a["status"] for a in align["result"]["alignments"]}
    assert by["White"] == "exact" and by["Martian"] == "unmapped" and align["meta"]["exception"]


async def test_uc4_concept_to_cdes_and_uc9_icdo(acc, expect):
    rev = await call(acc, "cadsr_find_data_elements_by_concept", {"conceptCode": "C17049", "limit": 10})
    assert_envelope(rev, tool="cadsr_find_data_elements_by_concept")
    assert any(d["publicId"] == expect.race_cde for d in rev["result"])
    icdo = await call(acc, "map_map_icdo_to_ncit", {"icdoCode": expect.icdo_morphology})
    assert any(m["concept"]["code"] == expect.icdo_expected for m in icdo["result"]) and icdo["result"][0]["axis"] == "morphology"


async def test_credential_gated_tools_degrade_with_reason(acc, expect):
    """Without a caDSR login the gated tools say what to configure; with one (e.g. from .env in
    live mode) they return real content: context names and CDE Match candidates."""
    backends = await call(acc, "cadsr_list_match_backends", {})
    assert {b["name"] for b in backends["result"]} == {"cde_match", "ai_engine", "vm_match"}
    credentialed = next(b["available"] for b in backends["result"] if b["name"] == "cde_match")
    if not credentialed:
        err = await error(acc, "cadsr_list_contexts", {})
        assert err["code"] == "capability_unavailable" and "ECM_CADSR_USERNAME" in err["message"]
        return
    ctxs = await call(acc, "cadsr_list_contexts", {})
    assert_envelope(ctxs, tool="cadsr_list_contexts")
    names = {c["name"] for c in ctxs["result"]}
    assert "NCIP" in names and all(names)
    match = await call(acc, "cadsr_match_data_elements", {
        "entities": [{"name": "Race", "permissibleValues": ["White", "Asian"]}], "matchLimit": 5})
    assert_envelope(match, tool="cadsr_match_data_elements")
    assert match["result"] and all(m["publicId"] and isinstance(m["score"], float) for m in match["result"])
    assert expect.race_cde in {m["publicId"] for m in match["result"]}
    assert "cadsr_match" in {p["source"] for p in match["provenance"]}
