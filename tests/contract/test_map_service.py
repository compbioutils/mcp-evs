"""Contract tests for the mapping module (proposal Section 8, UC-1..UC-9) over the fake EVS
and caDSR transports: GDC demographic.race end to end, MDF, alignment verdicts, lint,
release impact, crosswalk, ICD-O, stored values and native CDE suggestion."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evs_cadsr_mcp.core.budget import Budget
from evs_cadsr_mcp.core.context import Invocation
from evs_cadsr_mcp.core.errors import EvsMcpError
from evs_cadsr_mcp.map.fragments import parse_fragment
from evs_cadsr_mcp.map.models import ModelFragment, ValueSetSide
from evs_cadsr_mcp.server.mcp_app import Services
from tests.conftest import FakeCadsr, FakeEvs

FIX = Path(__file__).parent.parent / "fixtures" / "map"
GDC_JSON = (FIX / "gdc_demographic.json").read_text()
MDF_YAML = (FIX / "mdf_participant.yaml").read_text()


def inv(max_requests: int = 50) -> Invocation:
    return Invocation(tool="t", budget=Budget(max_requests=max_requests))


# ------------------------------------------------------------ fragment adapters
def test_gdc_json_adapter():
    props = parse_fragment(ModelFragment(format="gdc_json", content=GDC_JSON))
    by = {p.name: p for p in props}
    assert set(by) == {"race", "vital_status", "days_to_birth"} and by["race"].entity == "demographic"
    race = by["race"]
    assert race.cdeId == "2192199" and race.cdeVersion == "1.0" and race.cdeSource == "caDSR"
    assert len(race.enum) == 9 and race.enum[4].value == "white" and race.enum[4].conceptCode == "C41261"
    assert by["days_to_birth"].cdeId is None and by["days_to_birth"].type == "integer"
    one = parse_fragment(ModelFragment(format="gdc_json", content=GDC_JSON, property="race"))
    assert len(one) == 1
    with pytest.raises(EvsMcpError) as ei:
        parse_fragment(ModelFragment(format="gdc_json", content=GDC_JSON, property="nope"))
    assert ei.value.code == "invalid_request"
    with pytest.raises(EvsMcpError):
        parse_fragment(ModelFragment(format="gdc_json", content="not json"))


def test_gdc_yaml_terms_style_and_mdf_adapter():
    terms_yaml = "race:\n  description: Race\n  termDef:\n    source: caDSR\n    cde_id: 2192199\n    cde_version: 1.0\n"
    props = parse_fragment(ModelFragment(format="gdc_yaml", content=terms_yaml))
    assert props[0].name == "race" and props[0].cdeId == "2192199" and props[0].model == "gdc"
    mdf = parse_fragment(ModelFragment(format="mdf_yaml", content=MDF_YAML))
    by = {p.name: p for p in mdf}
    assert by["race"].entity == "participant" and by["race"].cdeId == "2192199" and by["race"].required is True
    assert [v.value for v in by["race"].enum] == ["White", "Asian", "Caucasian", "Martian"]
    assert by["sample_count"].cdeId is None and by["sample_count"].entity == "sample" and by["sample_count"].required is False


# ------------------------------------------------------------- UC-1 resolve CDE
async def test_resolve_cde_concepts_at_release(unified_services: Services, fake_evs: FakeEvs, fake_cadsr: FakeCadsr):
    env = await unified_services.map.resolve_cde_concepts(inv(), "2192199", "1.0", None, include_pvs=True)
    r = env.result
    assert r.release == fake_evs.active and r.objectClass[0].conceptCode == "C25190" and r.objectClass[0].ncitName == "Person"
    assert r.property[0].conceptStatusAtRelease == "active" and r.property[0].nameAgrees is True
    assert r.representationTerm[0].conceptCode == "C25372"
    vms = {v.conceptCode: v for v in r.valueMeanings}
    assert len(vms) == 8 and vms["C41261"].pvValue == "White" and vms["C41261"].semanticTypes == ["Population Group"]
    assert vms["C17649"].conceptStatusAtRelease == "retired" and vms["C17649"].replacement.code == "C17998"
    assert r.summary == {"active": 10, "retired": 1}
    # composition: one caDSR fetch + one EVS batch call; provenance from both sources
    assert env.meta.outboundRequests == 2
    sources = {p.source for p in env.provenance}
    assert sources == {"cadsr_nciapi", "evs_rest"}
    assert any(p.registry and p.registry.publicId == "2192199" for p in env.provenance)
    assert any(p.release == fake_evs.active for p in env.provenance)
    assert any("retired" in w for w in env.warnings)


async def test_resolve_cde_concepts_header_only_skips_pvs(unified_services: Services):
    env = await unified_services.map.resolve_cde_concepts(inv(), "2192199", None, None, include_pvs=False)
    assert env.result.valueMeanings == [] and env.result.summary == {"active": 3}


# --------------------------------------------------------- UC-4 concept -> CDEs
@pytest.mark.xfail(strict=True, reason="open decision: an absent code with replacement history returns 0 CDEs plus a warning, not not_found")
async def test_find_data_elements_for_concept_with_descendants(unified_services: Services):
    env = await unified_services.map.find_data_elements_for_concept(inv(), "C3224", None, expand=True, max_level=1, max_concepts=3, item_type=None)
    r = env.result
    assert [g.concept.code for g in r.groups] == ["C3224", "C3510"] and r.totalDataElements == 2 and r.groups[1].depth == 1
    assert env.truncation and env.truncation.occurred  # 4 descendants exist, only 2 were followed
    with pytest.raises(EvsMcpError) as ei:
        await unified_services.map.find_data_elements_for_concept(inv(), "C12345", None, expand=False, max_level=1, max_concepts=3, item_type=None)
    assert ei.value.code == "not_found"


# ------------------------------------------------------------- PV explanation
async def test_explain_permissible_value(unified_services: Services):
    env = await unified_services.map.explain_permissible_value(inv(), "2192199", "1.0", "white", None)
    r = env.result
    assert r.value == "White" and r.concept.code == "C41261" and r.synonyms == ["Caucasian"] and r.definitionSource == "NCI"
    other = await unified_services.map.explain_permissible_value(inv(), "2192199", "1.0", "Other", None)
    assert other.result.conceptStatusAtRelease == "retired" and other.result.replacement.code == "C17998"
    with pytest.raises(EvsMcpError) as ei:
        await unified_services.map.explain_permissible_value(inv(), "2192199", "1.0", "Martian", None)
    assert ei.value.code == "invalid_request" and "White" in ei.value.details["knownValues"]


# ------------------------------------------------------------- UC-3 alignment
async def test_align_values_against_cde(unified_services: Services):
    env = await unified_services.map.align_value_sets(inv(), ValueSetSide(values=["White", "caucasian", "Martian", "other"]), ValueSetSide(cde={"publicId": "2192199", "version": "1.0"}), None)
    by = {a.value: a for a in env.result.alignments}
    assert by["White"].status == "exact" and by["White"].matchedConcept == "C41261"
    assert by["caucasian"].status == "synonym" and by["caucasian"].matchedTo == "White" and any("synonym" in e for e in by["caucasian"].evidence)
    assert by["Martian"].status == "unmapped"
    assert by["other"].status == "exact"  # plain string equal to PV 'Other'; no left concept to be retired
    assert env.result.summary == {"exact": 2, "synonym": 1, "unmapped": 1}
    assert len(env.result.unmatchedRight) == 6 and env.meta.exception and "alignment" in env.meta.exception


async def test_align_gdc_enum_def_against_cde_and_subset(unified_services: Services):
    block = json.loads(GDC_JSON)["properties"]["race"]
    env = await unified_services.map.align_value_sets(inv(), ValueSetSide(gdcEnumDef={"enum": block["enum"], "enumDef": block["enumDef"]}), ValueSetSide(cde={"publicId": "2192199"}), None)
    by = {a.value: a for a in env.result.alignments}
    assert by["other"].status == "retired" and by["other"].replacement.code == "C17998" and by["other"].matchedTo == "Other"
    assert by["not allowed to collect"].status == "unmapped"
    assert by["native hawaiian or other pacific islander"].status == "exact"
    assert env.result.summary == {"exact": 7, "retired": 1, "unmapped": 1} and env.result.unmatchedRight == []
    # right side as an NCIt subset
    sub = await unified_services.map.align_value_sets(inv(), ValueSetSide(values=["Melanoma", "NSCLC", "Foo"]), ValueSetSide(ncitSubset="C177537"), None)
    sb = {a.value: a for a in sub.result.alignments}
    assert sb["Melanoma"].status == "exact" and sb["NSCLC"].status == "synonym" and sb["NSCLC"].matchedConcept == "C2926" and sb["Foo"].status == "unmapped"
    with pytest.raises(EvsMcpError) as ei:
        await unified_services.map.align_value_sets(inv(), ValueSetSide(ncitSubset="C177537"), ValueSetSide(values=["x"]), None)
    assert ei.value.code == "invalid_request"


# ------------------------------------------- UC-1 end to end: GDC demographic
async def test_resolve_model_property_gdc_end_to_end(unified_services: Services, fake_evs: FakeEvs):
    env = await unified_services.map.resolve_model_property(inv(), ModelFragment(format="gdc_json", content=GDC_JSON), None)
    by = {m.property.name: m for m in env.result}
    race = by["race"]
    assert race.cdeStatus == "resolved" and race.cde.longName == "Race Category Text" and race.release == fake_evs.active
    assert race.alignment.summary == {"exact": 7, "retired": 1, "unmapped": 1}
    assert by["vital_status"].cdeStatus == "cde_not_found" and by["vital_status"].cde is None
    assert by["days_to_birth"].cdeStatus == "missing_cde_id"
    assert env.meta.outboundRequests == 3  # CDE 2192199, one EVS batch, CDE 5 (404)
    assert env.meta.exception and env.truncation is None


async def test_resolve_model_property_mdf(unified_services: Services):
    env = await unified_services.map.resolve_model_property(inv(), ModelFragment(format="mdf_yaml", content=MDF_YAML, property="race"), None)
    m = env.result[0]
    assert m.property.model == "mdf" and m.cdeStatus == "resolved"
    assert {a.value: a.status for a in m.alignment.alignments} == {"White": "exact", "Asian": "exact", "Caucasian": "synonym", "Martian": "unmapped"}


# ------------------------------------------------------------------ UC-8 lint
async def test_validate_model_fragment_findings(unified_services: Services):
    env = await unified_services.map.validate_model_fragment(inv(), ModelFragment(format="gdc_json", content=GDC_JSON), None, mode="report")
    rep = env.result
    codes = sorted((f.property, f.code) for f in rep.findings)
    assert ("vital_status", "cde_not_found") in codes and ("days_to_birth", "missing_cde_id") in codes
    assert ("race", "retired_annotation_concept") in codes and ("race", "enum_value_retired_concept") in codes and ("race", "enum_value_not_in_cde") in codes
    assert rep.summary == {"error": 1, "warning": 4} and rep.propertiesChecked == 3
    retired = next(f for f in rep.findings if f.code == "enum_value_retired_concept")
    assert retired.value == "other" and "C17998" in retired.suggestion
    flat = await unified_services.map.validate_model_fragment(inv(), ModelFragment(format="gdc_json", content=GDC_JSON), None, mode="findings")
    assert isinstance(flat.result, list) and len(flat.result) == 5 and "lint" in flat.meta.exception


# --------------------------------------------------------- UC-5 release impact
async def test_assess_release_impact_for_cde(unified_services: Services, fake_evs: FakeEvs):
    env = await unified_services.map.assess_release_impact(inv(), fake_evs.previous, None, {"cde": {"publicId": "2192199", "version": "1.0"}}, lookup_cdes=True)
    r = env.result
    assert r.fromRelease == fake_evs.previous and r.toRelease == fake_evs.active and r.checked == 11
    assert [(i.conceptCode, i.change) for i in r.impacts] == [("C17649", "retired")]
    assert r.impacts[0].replacement.code == "C17998" and [d.publicId for d in r.impacts[0].dataElements] == ["2192199"]
    with pytest.raises(EvsMcpError) as ei:
        await unified_services.map.assess_release_impact(inv(), fake_evs.active, fake_evs.active, {"conceptCodes": ["C17649"]}, lookup_cdes=False)
    assert ei.value.code == "invalid_request"
    with pytest.raises(EvsMcpError) as ei:
        await unified_services.map.assess_release_impact(inv(), "20.01d", None, {"conceptCodes": ["C17649"]}, lookup_cdes=False)
    assert ei.value.code == "release_not_available"


# ------------------------------------------------------------ UC-6 crosswalk
async def test_crosswalk_gdc_vs_mdf(unified_services: Services):
    env = await unified_services.map.crosswalk_properties(
        inv(), ModelFragment(format="gdc_json", content=GDC_JSON, property="race"), ModelFragment(format="mdf_yaml", content=MDF_YAML, property="race"), None)
    r = env.result
    assert r.basis == "same_cde" and r.sharedConcepts == ["C17049", "C25190", "C25372"]
    assert r.enumOverlap["sharedValues"] == 2  # white, asian (case-insensitive)
    none = await unified_services.map.crosswalk_properties(
        inv(), ModelFragment(format="gdc_json", content=GDC_JSON, property="race"), ModelFragment(format="mdf_yaml", content=MDF_YAML, property="sample_count"), None)
    assert none.result.basis == "none"


# ---------------------------------------------------------------- UC-9 ICD-O
MORPHOLOGY_URL = "https://evs.nci.nih.gov/ftp1/NCI_Thesaurus/Mappings/ICD-O-3_Mappings/ICD-O-3.1-NCIt_Morphology_Mapping.txt"


async def test_map_icdo_to_ncit_by_code_uses_evs_mapping_files(unified_services: Services, fake_evs: FakeEvs):
    env = await unified_services.map.map_icdo_to_ncit(inv(), icdo_code="8140/3", term=None, axis="auto", include_group=True, release=None)
    [m] = env.result
    assert (m.concept.code, m.icdoTerm, m.icdoTermType, m.icdoVersions, m.ncimCui) == ("C2852", "Adenocarcinoma, NOS", "PT", ["3.1"], "C0001418")
    assert m.axis == "morphology" and m.matchedVia == "ICD-O code" and m.conceptStatusAtRelease == "active"
    assert m.release == fake_evs.active and m.mapRelease == "2026-07-11"
    assert m.group is None and any("group table" in w for w in env.warnings)
    snapshot = next(p for p in env.provenance if p.source == "evs_download")
    assert snapshot.servedBy == "snapshot" and snapshot.sourceUri == MORPHOLOGY_URL
    assert snapshot.retrievedAt.isoformat() == "2026-11-20T21:43:45+00:00"
    # Status is checked with one live batch call; no free-text EVS search.
    assert not [r for r in fake_evs.requests if r.url.path.endswith("/search")]


async def test_map_icdo_to_ncit_code_with_several_concepts_and_statuses(unified_services: Services):
    env = await unified_services.map.map_icdo_to_ncit(inv(), icdo_code="c34.1", term=None, axis="topography", include_group=False, release=None)
    # "Upper lobe, bronchus" has no NCIt code in the EVS file, so it is not a mapping.
    assert [(m.concept.code, m.icdoTermType) for m in env.result] == [("C12285", "PT"), ("C40373", "RT")]
    assert {m.conceptStatusAtRelease for m in env.result} == {"not_found"}  # unknown to the fake EVS
    retired = await unified_services.map.map_icdo_to_ncit(inv(), icdo_code="9990/3", term=None, axis="auto", include_group=False, release=None)
    assert retired.result[0].conceptStatusAtRelease == "retired" and any("retired or absent" in w for w in retired.warnings)
    mesonephric = await unified_services.map.map_icdo_to_ncit(inv(), icdo_code="9110/1", term=None, axis="auto", include_group=False, release=None)
    [m] = mesonephric.result  # PT and SY rows for the same concept collapse into one mapping
    assert (m.icdoTerm, m.concept.code) == ("Mesonephric tumor, NOS", "C4295")


async def test_map_icdo_to_ncit_by_term(unified_services: Services):
    exact = await unified_services.map.map_icdo_to_ncit(inv(), icdo_code=None, term="Adenocarcinoma", axis="auto", include_group=False, release=None)
    assert [(m.concept.code, m.matchedVia) for m in exact.result] == [("C2852", "NCIt name")]
    synonym = await unified_services.map.map_icdo_to_ncit(inv(), icdo_code=None, term="Wolffian duct tumor", axis="auto", include_group=False, release=None)
    assert [(m.concept.code, m.matchedVia) for m in synonym.result] == [("C4295", "ICD-O term")]
    topo_only = await unified_services.map.map_icdo_to_ncit(inv(), icdo_code=None, term="lung", axis="topography", include_group=False, release=None)
    assert {m.concept.code for m in topo_only.result} == {"C12285", "C40373"}


async def test_map_icdo_to_ncit_errors_and_pinned_release(unified_services: Services, fake_evs: FakeEvs):
    with pytest.raises(EvsMcpError) as ei:
        await unified_services.map.map_icdo_to_ncit(inv(), icdo_code="8140/3", term=None, axis="topography", include_group=False, release=None)
    assert ei.value.code == "invalid_request"
    with pytest.raises(EvsMcpError) as ei:
        await unified_services.map.map_icdo_to_ncit(inv(), icdo_code="9999/9", term=None, axis="auto", include_group=False, release=None)
    assert ei.value.code == "not_found"
    pinned = await unified_services.map.map_icdo_to_ncit(inv(), icdo_code="8720/3", term=None, axis="auto", include_group=False, release=fake_evs.previous)
    assert pinned.result[0].release == fake_evs.previous and pinned.result[0].mapRelease == "2026-07-11"


async def test_map_icdo_to_ncit_without_downloaded_files_is_unavailable(unified_settings, fake_evs: FakeEvs, fake_cadsr: FakeCadsr, tmp_path):
    from evs_cadsr_mcp.server.mcp_app import build_services

    s = unified_settings.model_copy(update={"icdo_cache_dir": str(tmp_path)})  # empty cache, auto-sync off
    svc = build_services(s, transport=fake_evs.transport(), cadsr_transport=fake_cadsr.transport())
    try:
        with pytest.raises(EvsMcpError) as ei:
            await svc.map.map_icdo_to_ncit(inv(), icdo_code="8140/3", term=None, axis="auto", include_group=False, release=None)
        assert ei.value.code == "capability_unavailable" and "icdo sync" in ei.value.details["configure"]
        assert "ICD-O-3_Code" in ei.value.hint
        assert not fake_evs.requests  # fails before any upstream call
    finally:
        await svc.aclose()


# ------------------------------------------------------------- stored values
async def test_resolve_stored_value_gdc(unified_services: Services):
    env = await unified_services.map.resolve_stored_value(inv(), "C3224", "gdc", None)
    assert env.result.values[0].storedValue == "Melanoma, NOS" and env.result.values[0].source == "mapset"
    with pytest.raises(EvsMcpError) as ei:
        await unified_services.map.resolve_stored_value(inv(), "C3224", "cds", None)
    assert ei.value.code == "capability_unavailable"


# ------------------------------------------------------ UC-2 native suggestion
async def test_suggest_cdes_native_route(unified_services: Services):
    env = await unified_services.map.suggest_cdes_for_term(inv(), "Race", description=None, sample_values=["White", "Asian"], contexts=None, limit=5, backend=None, release=None)
    s = env.result[0]
    assert s.publicId == "2192199" and s.backend == "native" and s.score == 1.0
    assert any("Property" in e for e in s.evidence) and any("2/2 sample values" in e for e in s.evidence)
    assert "ranking" in env.meta.exception and any("native" in w for w in env.warnings)
    nothing = await unified_services.map.suggest_cdes_for_term(inv(), "quarterly budget variance", description=None, sample_values=None, contexts=None, limit=5, backend=None, release=None)
    assert nothing.result == []  # never fabricates a CDE


async def test_evs_only_profile_has_no_map(services: Services):
    assert services.map is None
