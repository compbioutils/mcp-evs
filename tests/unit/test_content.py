"""Content shaping tests against the hand-authored fixtures."""

from __future__ import annotations

import pytest

from evs_cadsr_mcp.core.errors import EvsMcpError
from evs_cadsr_mcp.evs import content
from tests.conftest import load


def test_concept_summary_shaping():
    raw = load("concept_C3224_summary.json")
    c = content.concept(raw, terminology="ncit", release="26.10d", source_uri="u")
    assert c.code == "C3224" and c.name == "Melanoma" and c.release == "26.10d"
    assert c.semanticTypes == ["Neoplastic Process"]
    assert {s.source for s in c.synonyms} >= {"NCI", "CDISC", "GDC"}
    assert c.definitions[0].source == "NCI"
    assert c.parents is None and c.roles is None  # not requested -> absent, not empty
    assert c.sourceUri == "u"


def test_relationship_polarity_and_direction():
    raw = load("concept_C3224_relations.json")
    c = content.concept(raw, terminology="ncit", release="26.10d")
    by_type = {e.type: e for e in c.roles}
    assert by_type["Disease_Excludes_Finding"].polarity == "negative"
    assert by_type["Disease_Has_Abnormal_Cell"].polarity == "positive"
    assert c.inverseRoles[0].direction == "incoming"
    assert c.associations[0].kind == "association" and c.associations[0].qualifiers is None
    assert len(c.maps) == 3 and c.maps[2].targetTerminology == "MedDRA"
    assert c.history[1].action == "modify"


def test_paths_accepts_both_shapes():
    nested = [[{"code": "C1", "name": "a", "level": 0}, {"code": "C2", "name": "b", "level": 1}]]
    wrapped = {"paths": [{"direction": 1, "concepts": nested[0]}]}
    for raw in (nested, wrapped):
        p = content.paths(raw, "toRoot", release="26.10d")
        assert len(p) == 1 and [c.code for c in p[0].concepts] == ["C1", "C2"]
        assert p[0].concepts[1].level == 1


def test_include_normalisation():
    assert content.normalise_include(None) == "summary"
    assert content.normalise_include(["summary", "children,parents", "summary"]) == "summary,children,parents"
    with pytest.raises(EvsMcpError) as ei:
        content.normalise_include(["everything"])
    assert ei.value.code == "invalid_request"


def test_mapset_license_flag():
    raws = load("misc_endpoints.json")["/mapset"]
    gated = {"meddra", "mdr"}
    gdc, mdr = (content.mapset(r, gated=gated) for r in raws)
    assert gdc.targetTerminology == "GDC" and gdc.licenseRequired is False and gdc.downloadOnly is False
    assert mdr.licenseRequired is True
