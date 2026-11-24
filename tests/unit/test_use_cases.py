"""Offline checks for scripts/run_use_cases.py: the use-case document stays executable against
this server's tool schemas, and the expectation checks can fail as well as pass."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
RELEASES = {"ncit": "26.10d", "previous": "26.09d", "ctcae5": "5.0", "ctcae6": "6.0"}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


runner = _load("run_use_cases", ROOT / "scripts" / "run_use_cases.py")


async def test_every_documented_step_is_a_valid_call_to_this_server():
    target = _load("_mcp_target", ROOT / "scripts" / "_mcp_target.py")
    async with target.open_client("fixtures", profile="unified") as client:
        tools = {t.name: t for t in await client.list_tools()}
    cases = runner.parse_cases()
    assert [c.identifier for c in cases] == [f"EVS-{n:02d}" for n in range(1, 10)]
    for case in cases:
        for step in case.steps:
            assert step["tool"] in tools, f"{case.identifier}.{step['id']}"
            args = runner.substitute(step.get("arguments", {}), RELEASES)
            if "codesFrom" in step:
                args["codes"] = ["C4878"]
            errors = [e.message for e in Draft202012Validator(tools[step["tool"]].inputSchema).iter_errors(args)]
            assert errors == [], f"{case.identifier}.{step['id']}: {errors}"
            runner.substitute(step.get("expect", {}), RELEASES)  # every $release is discoverable


ENVELOPE = {
    "result": {"concepts": [{"code": "C2852", "polarity": "negative", "leaf": True}], "missing": []},
    "provenance": [{"source": "evs_rest", "release": "26.10d"}, {"source": "evs_rest"}],
    "page": {"limit": 5, "nextCursor": "abc"},
    "truncation": {"occurred": True, "bound": "maxDepth"},
    "warnings": ["license gate withheld map targets: MedDRA"],
}


@pytest.mark.parametrize(
    ("expect", "fails"),
    [
        ({"has": {"code": ["C2852"], "polarity": ["negative"], "leaf": [True]}}, False),
        ({"has": {"code": ["C2852", "C3224"]}}, True),
        ({"lacks": {"code": ["C3224"]}}, False),
        ({"lacks": {"code": ["C2852"]}}, True),
        ({"count": {"at": "concepts", "min": 1, "max": 1}}, False),
        ({"count": {"at": "missing", "min": 1}}, True),
        ({"count": {"min": 1}}, True),  # result is an object, not a list
        ({"complete": True}, True),
        ({"paged": True, "truncated": "maxDepth"}, False),
        ({"truncated": "maxNodes"}, True),
        ({"warning": "MedDRA", "release": "26.10d"}, False),
        ({"release": "26.09d"}, True),
    ],
)
def test_expectations_pass_and_fail(expect, fails):
    assert bool(runner.check(ENVELOPE, expect)) is fails


def test_outcomes_for_errors_and_known_issues():
    error = {"error": {"code": "not_found"}}
    assert runner.outcome({"expectedError": "not_found"}, True, error) == ("PASS", [])
    assert runner.outcome({"expectedError": "release_not_available"}, True, error)[0] == "ERROR"
    assert runner.outcome({}, True, error)[0] == "ERROR"
    assert runner.outcome({"expectedError": "not_found"}, False, ENVELOPE)[0] == "FAIL"
    known = {"knownIssue": "x", "expect": {"has": {"code": ["C3224"]}}}
    assert runner.outcome(known, False, ENVELOPE)[0] == "KNOWN_ISSUE"
    fixed = {"knownIssue": "x", "expect": {"has": {"code": ["C2852"]}}}
    assert runner.outcome(fixed, False, ENVELOPE)[0] == "UNEXPECTED_PASS"


def test_codes_from_puts_root_first_and_blocks_on_a_failed_step():
    rows = {"branch": {"status": "PASS", "response": {"result": [{"code": "C2926"}, {"code": "C4878"}]}}}
    assert runner.codes_from({"step": "branch", "root": "C4878"}, rows) == ["C4878", "C2926"]
    with pytest.raises(LookupError, match="branch"):
        runner.codes_from({"step": "branch"}, {"branch": {"status": "ERROR", "response": {}}})
    with pytest.raises(LookupError, match="previous"):
        runner.substitute({"release": "$previous"}, {"ncit": "26.10d"})


def test_child_server_ignores_inherited_settings(monkeypatch):
    monkeypatch.setenv("ECM_CADSR_BASE_URL", "https://cadsrapi.cancer.gov")
    monkeypatch.setenv("ECM_LICENSE_KEY", "inherited")
    env = runner.child_environment("/tmp/icdo")
    assert env["ECM_CADSR_BASE_URL"] == "https://cadsrapi-stage.cancer.gov"
    assert "ECM_LICENSE_KEY" not in env
    assert env["ECM_ICDO_SYNC_INTERVAL_S"] == "0"
