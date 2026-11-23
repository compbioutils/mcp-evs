"""T-IFACE (proposal 12, 13): the running server must not drift from the frozen interface
baseline in a breaking way. Additions are non-breaking (minor version); removals, changed
schemas, new required fields and changed annotations are breaking and need a versioned
change request (docs/change-control.md).

The drift classifier is unit-tested here; the end-to-end check runs only when a baseline for
the current INTERFACE_VERSION has been exported (``evs-cadsr-mcp baseline export``).
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from evs_cadsr_mcp import INTERFACE_VERSION
from evs_cadsr_mcp.server import baseline as bl

ROOT = Path(__file__).resolve().parents[2]
BASELINE_ROOT = ROOT / "spec" / "interface-baseline"


def _snapshot() -> dict:
    tool = {
        "name": "evs_get_concept", "title": "evs.get_concept", "description": "d",
        "annotations": {"readOnlyHint": True, "idempotentHint": True},
        "inputSchema": {"type": "object", "properties": {"code": {"type": "string", "description": "x"}, "release": {"type": "string"}}, "required": ["code"]},
        "outputSchema": {"type": "object", "properties": {"result": {"$ref": "#/$defs/Concept"}, "meta": {"type": "object"}}, "required": ["result", "meta"],
                         "$defs": {"Concept": {"type": "object", "properties": {"code": {"type": "string"}, "name": {"type": "string"}}}}},
    }
    return {
        "interfaceVersion": "1.0",
        "profiles": {"evs-only": {"profile": "evs-only", "tools": {"evs_get_concept": tool}, "resources": {"evs://terminologies": {}}, "resourceTemplates": {}, "prompts": {"walk_to_root": {}}}},
        "envelopes": {"Envelope": {"type": "object", "properties": {"result": {}, "meta": {}}, "required": ["result", "meta"]}},
        "errorCodes": {"not_found": {"retryable": False}, "timeout": {"retryable": True}},
    }


def test_identical_snapshots_have_no_drift():
    assert bl.compare(_snapshot(), _snapshot()).ok


def test_additions_and_description_changes_are_non_breaking():
    old, new = _snapshot(), _snapshot()
    t = new["profiles"]["evs-only"]["tools"]["evs_get_concept"]
    t["inputSchema"]["properties"]["include"] = {"type": "array"}            # new optional argument
    t["inputSchema"]["properties"]["code"]["description"] = "changed text"   # description only
    t["outputSchema"]["$defs"]["Concept"]["properties"]["leaf"] = {"type": "boolean"}  # new optional result field
    new["profiles"]["evs-only"]["tools"]["evs_new_tool"] = copy.deepcopy(t)
    new["profiles"]["evs-only"]["prompts"]["expand_value_set"] = {}
    new["errorCodes"]["rate_limited"] = {"retryable": True}
    d = bl.compare(old, new)
    assert d.ok, d.summary()
    assert any("include" in n for n in d.nonBreaking) and any("evs_new_tool added" in n for n in d.nonBreaking)
    assert any("leaf" in n for n in d.nonBreaking) and any("rate_limited added" in n for n in d.nonBreaking)


def test_removals_and_incompatible_changes_are_breaking():
    old, new = _snapshot(), _snapshot()
    t = new["profiles"]["evs-only"]["tools"]["evs_get_concept"]
    del t["inputSchema"]["properties"]["release"]                       # argument removed
    t["outputSchema"]["$defs"]["Concept"]["properties"]["code"] = {"type": "integer"}  # type changed
    t["annotations"]["readOnlyHint"] = False                             # hint changed
    del new["profiles"]["evs-only"]["resources"]["evs://terminologies"]
    del new["errorCodes"]["timeout"]
    d = bl.compare(old, new)
    assert not d.ok
    joined = "\n".join(d.breaking)
    assert "removed ['release']" in joined and "$defs.Concept" in joined and "annotations changed" in joined
    assert "resource evs://terminologies removed" in joined and "error code timeout removed" in joined


def test_new_required_argument_is_breaking():
    old, new = _snapshot(), _snapshot()
    t = new["profiles"]["evs-only"]["tools"]["evs_get_concept"]
    t["inputSchema"]["properties"]["terminology"] = {"type": "string"}
    t["inputSchema"]["required"].append("terminology")
    d = bl.compare(old, new)
    assert not d.ok and any("new required field" in b for b in d.breaking)


def test_tool_removed_from_profile_is_breaking():
    old, new = _snapshot(), _snapshot()
    del new["profiles"]["evs-only"]["tools"]["evs_get_concept"]
    d = bl.compare(old, new)
    assert d.breaking == ["[evs-only] tool evs_get_concept removed"]


def test_baseline_roundtrip_through_files(tmp_path):
    snap = {**_snapshot(), "serverVersion": "0.1.0", "generatedAt": "now"}
    out = bl.write_baseline(snap, tmp_path)
    assert (out / "manifest.json").exists() and (out / "tools" / "evs-only" / "evs_get_concept.schema.json").exists()
    back = bl.read_baseline(tmp_path, "1.0")
    assert back is not None and bl.compare(back, snap).ok and bl.compare(snap, back).ok
    assert bl.read_baseline(tmp_path, "9.9") is None


def test_conformance_mock_manifest_marks_hand_authored_fixtures():
    m = bl.conformance_mock_manifest(ROOT / "tests" / "fixtures")
    assert "evs/concept_C3224_summary.json" in m["files"]
    assert m["files"]["evs/concept_C3224_summary.json"]["recorded"] is False  # hand-authored until record_fixtures.py runs
    assert all(len(v["sha256"]) == 64 for v in m["files"].values())


@pytest.mark.skipif(not (BASELINE_ROOT / f"v{INTERFACE_VERSION}" / "manifest.json").exists(), reason="no frozen baseline exported yet")
async def test_running_server_matches_frozen_baseline():
    """N vs. frozen N: fails on any breaking drift; additions are reported but allowed."""
    frozen = bl.read_baseline(BASELINE_ROOT, INTERFACE_VERSION)
    current = await bl.collect_all()
    drift = bl.compare(frozen, current)
    assert drift.ok, f"breaking interface drift against spec/interface-baseline/v{INTERFACE_VERSION}:\n{drift.summary()}"
