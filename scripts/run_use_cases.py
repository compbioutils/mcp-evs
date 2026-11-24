"""Run the executable EVS use cases in ``docs/evs mcp use cases.md`` against live EVS.

Each ``## EVS-nn`` section of the document holds one JSON list of steps (MCP tool calls plus
expectations; the step format is described in the document). This script starts an isolated
copy of this checkout's server over stdio, discovers the releases EVS serves, runs every step,
checks its expectations and the tool's output schema, and writes:

    docs/evaluation/use-case-results.json   every call, argument, result and check
    docs/evaluation/use-case-results.md     summary tables for the evaluation report

    uv run --no-sync python scripts/run_use_cases.py --list
    uv run --no-sync python scripts/run_use_cases.py --dry-run
    uv run --no-sync python scripts/run_use_cases.py                  # all scenarios
    uv run --no-sync python scripts/run_use_cases.py --case EVS-03 --out "$TMPDIR/uc"

The child server gets no ECM_* settings from this shell and doesn't read .env: it runs the
unified profile with caDSR pointed at stage (no caDSR call is made), no license key (so the
MedDRA gate is exercised), and the ICD-O-3.1 mapping files synced into a temporary cache.

Exit status: 0 when every step passed or is a known issue, 1 when any step failed, errored,
was blocked or unexpectedly passed, 2 on a usage error.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import re
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).resolve().parent.parent
DOCUMENT = ROOT / "docs" / "evs mcp use cases.md"
OUT = ROOT / "docs" / "evaluation"
CADSR_STAGE = "https://cadsrapi-stage.cancer.gov"
FAILED = {"FAIL", "ERROR", "SCHEMA_ERROR", "UNEXPECTED_PASS", "BLOCKED", "MISSING_TOOL"}
USABLE = {"PASS", "KNOWN_ISSUE"}
EXPECT_KEYS = {"has", "lacks", "count", "complete", "paged", "truncated", "warning", "release"}
STEP_KEYS = {"id", "tool", "arguments", "codesFrom", "expect", "expectedError", "knownIssue", "note"}


@dataclass(frozen=True)
class Case:
    identifier: str
    title: str
    steps: tuple[dict[str, Any], ...]


def parse_cases(path: Path = DOCUMENT) -> list[Case]:
    """One case per ``## EVS-nn Title`` heading, each with exactly one JSON step list."""
    sections = re.split(r"^## (EVS-\d{2}) (.+)$", path.read_text(), flags=re.M)
    cases: list[Case] = []
    for i in range(1, len(sections), 3):
        identifier, title, body = sections[i : i + 3]
        blocks = re.findall(r"^```json\n(.*?)^```", body, flags=re.M | re.S)
        if len(blocks) != 1:
            raise ValueError(f"{identifier}: expected one JSON step list, found {len(blocks)}")
        steps = json.loads(blocks[0])
        if not isinstance(steps, list) or not steps:
            raise ValueError(f"{identifier}: the step list is empty")
        ids = [s.get("id") for s in steps]
        if len(set(ids)) != len(ids) or not all(ids):
            raise ValueError(f"{identifier}: step ids must be present and unique")
        for step in steps:
            unknown = set(step) - STEP_KEYS or set(step.get("expect", {})) - EXPECT_KEYS
            if unknown:
                raise ValueError(f"{identifier}.{step['id']}: unknown field(s) {sorted(unknown)}")
        cases.append(Case(identifier, title.strip(), tuple(steps)))
    if not cases:
        raise ValueError(f"no '## EVS-nn' scenarios in {path}")
    return cases


def select(cases: list[Case], wanted: list[str]) -> list[Case]:
    if not wanted:
        return cases
    for w in wanted:
        if not any(c.identifier == w or c.identifier.startswith(w + "-") for c in cases):
            raise ValueError(f"unknown case: {w}")
    return [c for c in cases if any(c.identifier == w or c.identifier.startswith(w + "-") for w in wanted)]


# ------------------------------------------------------------------ substitution and checks
def substitute(value: Any, releases: dict[str, str]) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        if value[1:] not in releases:
            raise LookupError(f"release {value} was not discovered")
        return releases[value[1:]]
    if isinstance(value, dict):
        return {k: substitute(v, releases) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, releases) for v in value]
    return value


def walk(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def norm(value: Any) -> str:
    return json.dumps(value) if isinstance(value, bool) else str(value)


def field_values(result: Any, field: str) -> set[str]:
    return {norm(obj[field]) for obj in walk(result) if obj.get(field) is not None}


def list_at(result: Any, at: str | None) -> list[Any] | None:
    target = result.get(at) if isinstance(result, dict) and at else result
    return target if isinstance(target, list) else None


def check(envelope: dict[str, Any], expect: dict[str, Any]) -> list[str]:
    """Return the failed expectations, as readable sentences; empty means every check passed."""
    result = envelope.get("result")
    page = envelope.get("page") or {}
    truncation = envelope.get("truncation") or {}
    failures: list[str] = []
    for field, values in (expect.get("has") or {}).items():
        missing = [v for v in values if norm(v) not in field_values(result, field)]
        if missing:
            failures.append(f"no {field} {missing} in result")
    for field, values in (expect.get("lacks") or {}).items():
        present = [v for v in values if norm(v) in field_values(result, field)]
        if present:
            failures.append(f"{field} {present} present in result")
    if "count" in expect:
        spec = expect["count"]
        items = list_at(result, spec.get("at"))
        where = f"result.{spec['at']}" if spec.get("at") else "result"
        if items is None:
            failures.append(f"{where} is not a list")
        elif len(items) < spec.get("min", 0) or len(items) > spec.get("max", len(items)):
            failures.append(f"{where} has {len(items)} items, expected {spec}")
    if expect.get("complete") and (page.get("nextCursor") or truncation.get("occurred")):
        failures.append("result is paged or truncated, expected complete")
    if expect.get("paged") and not page.get("nextCursor"):
        failures.append("expected page.nextCursor")
    if "truncated" in expect:
        bound = expect["truncated"]
        if not truncation.get("occurred") or (isinstance(bound, str) and truncation.get("bound") != bound):
            failures.append(f"expected truncation at {bound}, got {truncation or 'none'}")
    if "warning" in expect and not any(expect["warning"] in w for w in envelope.get("warnings") or []):
        failures.append(f"no warning mentioning {expect['warning']!r}")
    if "release" in expect:
        named = [p.get("release") for p in envelope.get("provenance") or [] if p.get("release")]
        if not named or any(r != expect["release"] for r in named):
            failures.append(f"provenance releases {sorted(set(named))}, expected {expect['release']}")
    return failures


def outcome(step: dict[str, Any], is_error: bool, content: Any) -> tuple[str, list[str]]:
    expected_error = step.get("expectedError")
    if is_error:
        code = (content.get("error") or {}).get("code") if isinstance(content, dict) else None
        if expected_error and code == expected_error:
            return "PASS", []
        return "ERROR", [f"tool error {code or content!r}" + (f", expected {expected_error}" if expected_error else "")]
    if expected_error:
        return "FAIL", [f"call succeeded, expected error {expected_error}"]
    failures = check(content, step.get("expect") or {})
    if step.get("knownIssue"):
        return ("KNOWN_ISSUE", failures) if failures else ("UNEXPECTED_PASS", ["known issue no longer reproduces; remove knownIssue"])
    return ("FAIL", failures) if failures else ("PASS", [])


def codes_from(spec: dict[str, Any], rows: dict[str, dict[str, Any]]) -> list[str]:
    row = rows.get(spec["step"])
    if row is None or row["status"] not in USABLE:
        raise LookupError(f"step {spec['step']} did not return usable content")
    items = list_at(row["response"].get("result"), spec.get("at")) or []
    codes = [spec["root"]] if spec.get("root") else []
    codes += [i["code"] for i in items if isinstance(i, dict) and i.get("code")]
    if not codes:
        raise LookupError(f"step {spec['step']} returned no codes")
    return list(dict.fromkeys(codes))


# ------------------------------------------------------------------------------- the run
class Run:
    def __init__(self, cases: list[Case], out: Path, *, full: bool = False) -> None:
        self.cases, self.out, self.full = cases, out, full
        self.releases: dict[str, str] = {}
        self.rows: list[dict[str, Any]] = []
        self.report: dict[str, Any] = {"startedAt": now(), "complete": False, "environment": environment(),
                                       "cases": [{"id": c.identifier, "title": c.title} for c in cases],
                                       "steps": self.rows}

    async def execute(self, client: Any) -> int:
        tools = {t.name: t for t in await client.list_tools()}
        self.report["toolCount"] = len(tools)
        await self.discover(client)
        for case in self.cases:
            print(f"\n{'=' * 78}\n{case.identifier} {case.title}", flush=True)
            local: dict[str, dict[str, Any]] = {}
            for step in case.steps:
                row = await self.step(client, tools, case, step, local)
                local[step["id"]] = row
        return self.finish()

    async def discover(self, client: Any) -> None:
        """Releases come from EVS at run time, never from the document: the active NCIt release,
        the newest monthly release before it, and the active CTCAE 5 and 6 releases."""
        for terminology in ("ncit", "ctcae5", "ctcae6"):
            res = await client.call_tool("evs_list_releases", {"terminology": terminology}, raise_on_error=False)
            if res.is_error:
                print(f"release discovery failed for {terminology}: {content_of(res)}", file=sys.stderr)
                continue
            releases = content_of(res)["result"]
            active = next((r for r in releases if r.get("active")), None)
            if active:
                self.releases[terminology] = active["version"]
            if terminology == "ncit" and active:
                older = [r for r in releases if r.get("monthly") and (r.get("date") or "") < (active.get("date") or "")]
                if older:
                    self.releases["previous"] = max(older, key=lambda r: r.get("date") or "")["version"]
        self.report["releases"] = dict(self.releases)
        print("Releases discovered:", json.dumps(self.releases), flush=True)

    async def step(self, client: Any, tools: dict[str, Any], case: Case, step: dict[str, Any],
                   local: dict[str, dict[str, Any]]) -> dict[str, Any]:
        row: dict[str, Any] = {"case": case.identifier, "id": f"{case.identifier}.{step['id']}", "tool": step["tool"]}
        for key in ("note", "knownIssue", "expectedError"):
            if step.get(key):
                row[key] = step[key]
        tool = tools.get(step["tool"])
        if tool is None:
            return self.record(row | {"status": "MISSING_TOOL", "failures": ["tool not advertised by the server"]})
        try:
            arguments = substitute(step.get("arguments", {}), self.releases)
            if "codesFrom" in step:
                arguments["codes"] = codes_from(step["codesFrom"], local)
            expect = substitute(step.get("expect", {}), self.releases)
        except LookupError as exc:
            return self.record(row | {"status": "BLOCKED", "failures": [str(exc)]})
        row["arguments"] = arguments
        try:
            Draft202012Validator(tool.inputSchema).validate(arguments)
        except ValidationError as exc:
            return self.record(row | {"status": "SCHEMA_ERROR", "failures": [f"arguments: {exc.message}"]})
        started = time.monotonic()
        res = await client.call_tool(step["tool"], arguments, raise_on_error=False)
        row["seconds"] = round(time.monotonic() - started, 3)
        content = content_of(res)
        row["response"] = content
        status, failures = outcome(step | {"expect": expect}, bool(res.is_error), content)
        if not res.is_error and tool.outputSchema:
            try:
                Draft202012Validator(tool.outputSchema).validate(content)
            except ValidationError as exc:
                status, failures = "SCHEMA_ERROR", [*failures, f"output: {exc.message}"]
        meta = content.get("meta") if isinstance(content, dict) else None
        if meta:
            row["outboundRequests"] = meta.get("outboundRequests")
        return self.record(row | {"status": status, "failures": failures})

    def record(self, row: dict[str, Any]) -> dict[str, Any]:
        self.rows.append(row)
        self.save()
        print(f"\n[{row['status']}] {row['id']}  {row['tool']}  ({row.get('seconds', '-')} s)")
        if "arguments" in row:
            print("  arguments: " + json.dumps(row["arguments"]))
        for key in ("note", "knownIssue"):
            if row.get(key):
                print(f"  {key}: {row[key]}")
        for failure in row.get("failures", []):
            print(f"  - {failure}")
        if "response" in row:
            text = json.dumps(row["response"].get("result", row["response"]), ensure_ascii=False)
            print("  result: " + (text if self.full or len(text) <= 400 else text[:400] + " ..."))
        return row

    def finish(self) -> int:
        counts = Counter(r["status"] for r in self.rows)
        self.report.update(complete=True, finishedAt=now(), counts=dict(counts),
                           caseResults=case_results(self.cases, self.rows))
        self.save()
        write_markdown(self.report, self.out / "use-case-results.md")
        print("\nSUMMARY: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        print(f"Results: {shown(self.out / 'use-case-results.md')} and use-case-results.json")
        return 1 if any(counts[s] for s in FAILED) else 0

    def save(self) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        path = self.out / "use-case-results.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.report, indent=2, ensure_ascii=False, default=str) + "\n")
        tmp.replace(path)


def case_results(cases: list[Case], rows: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for case in cases:
        statuses = {r["status"] for r in rows if r["case"] == case.identifier}
        out[case.identifier] = "FAIL" if statuses & FAILED else ("PASS*" if "KNOWN_ISSUE" in statuses else "PASS")
    return out


def content_of(res: Any) -> Any:
    if res.structured_content is not None and not res.is_error:
        return res.structured_content
    texts = [getattr(c, "text", None) for c in res.content or []]
    texts = [t for t in texts if t]
    try:
        return json.loads(texts[0]) if texts else res.structured_content
    except ValueError:
        return {"error": {"code": None, "message": texts[0]}}


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def shown(path: Path) -> str:
    """Path relative to the checkout when inside it, so results don't record a home directory."""
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def environment() -> dict[str, Any]:
    try:
        server_version = version("evs-cadsr-mcp")
    except PackageNotFoundError:
        server_version = None
    git = {}
    for key, cmd in (("commit", ["git", "rev-parse", "--short", "HEAD"]), ("dirty", ["git", "status", "--porcelain", "--", "src"])):
        try:
            git[key] = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        except OSError:
            git[key] = None
    return {"server": "evs-cadsr-mcp", "serverVersion": server_version, "gitCommit": git["commit"],
            "sourceModified": bool(git["dirty"]), "python": platform.python_version(),
            "platform": platform.platform(terse=True), "transport": "stdio", "profile": "unified",
            "evs": "https://api-evsrest.nci.nih.gov/api/v1", "document": str(DOCUMENT.relative_to(ROOT))}


# ----------------------------------------------------------------------------- markdown
def write_markdown(report: dict[str, Any], path: Path) -> None:
    env, counts, rows = report["environment"], report.get("counts", {}), report["steps"]
    lines = [
        "# EVS use-case results",
        "",
        "Generated by `scripts/run_use_cases.py` from [the use cases](../evs%20mcp%20use%20cases.md). "
        "Rerunning the script replaces this file.",
        "",
        "| Item | Value |", "| --- | --- |",
        f"| Run | {report['startedAt']} to {report.get('finishedAt', '-')} (UTC) |",
        f"| Server | {env['server']} {env['serverVersion']}, commit `{env['gitCommit']}`"
        + (" (with local source changes)" if env["sourceModified"] else "") + f", {report.get('toolCount')} tools ({env['profile']} profile) over {env['transport']} |",
        f"| Upstream | Live NCI EVS REST API ({env['evs']}) |",
        "| Releases | " + ", ".join(f"`{k}` = {v}" for k, v in report.get("releases", {}).items()) + " |",
        f"| Steps | {len(rows)}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) + " |",
        "",
        "## Scenarios", "",
        "| Scenario | Result | Steps | Passed | Known issues | Failed |", "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for case in report["cases"]:
        mine = [r for r in rows if r["case"] == case["id"]]
        c = Counter(r["status"] for r in mine)
        lines.append(f"| {case['id']} {case['title']} | {report.get('caseResults', {}).get(case['id'], '-')} | {len(mine)} | "
                     f"{c['PASS']} | {c['KNOWN_ISSUE']} | {sum(c[s] for s in FAILED)} |")
    lines += ["", "`PASS*`: every step passed except documented known issues.", "", "## Steps", "",
              "| Step | Tool | Result | Time (s) | Detail |", "| --- | --- | --- | ---: | --- |"]
    for r in rows:
        detail = "; ".join(r.get("failures") or []) or r.get("note") or ("expected error " + r["expectedError"] if r.get("expectedError") else "")
        if r["status"] == "KNOWN_ISSUE":
            detail = r["knownIssue"]
        lines.append(f"| {r['id']} | `{r['tool']}` | {r['status']} | {r.get('seconds', '-')} | {detail.replace('|', '/')} |")
    path.write_text("\n".join(lines) + "\n")


# ------------------------------------------------------------------------------- server
def child_environment(icdo_dir: str) -> dict[str, str]:
    """Nothing ECM_* is inherited, so a developer's settings can't retarget or change the run."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("ECM_")}
    env.update({
        "ECM_PROFILE": "unified",
        "ECM_CADSR_BASE_URL": CADSR_STAGE,
        "ECM_ICDO_CACHE_DIR": icdo_dir,
        "ECM_ICDO_SYNC_INTERVAL_S": "0",
        "ECM_LOG_LEVEL": "WARNING",
    })
    return env


def server_command(*args: str) -> list[str]:
    return [sys.executable, "-m", "evs_cadsr_mcp.server.cli", *args]


async def live(cases: list[Case], out: Path, *, full: bool) -> int:
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport

    run = Run(cases, out, full=full)
    with TemporaryDirectory(prefix="evs-use-cases-", dir=os.environ.get("TMPDIR")) as tmp:
        env = child_environment(str(Path(tmp) / "icdo"))
        # cwd is the temporary directory, so the child doesn't read this checkout's .env.
        sync = subprocess.run(server_command("icdo", "sync"), env=env, cwd=tmp, capture_output=True, text=True, timeout=300)
        run.report["icdoSync"] = "ok" if sync.returncode == 0 else f"failed: {sync.stderr.strip()[-300:]}"
        print(f"Isolated stdio server from this checkout; ICD-O-3.1 files: {run.report['icdoSync']}", flush=True)
        transport = StdioTransport(command=sys.executable, args=server_command("serve", "--transport", "stdio")[1:], env=env, cwd=tmp)
        async with Client(transport, timeout=120) as client:
            return await run.execute(client)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--case", action="append", default=[], help="scenario (EVS-03) or group (EVS); repeatable")
    parser.add_argument("--list", action="store_true", help="list the scenarios and exit")
    parser.add_argument("--dry-run", action="store_true", help="print every planned step; no server or network")
    parser.add_argument("--full", action="store_true", help="print whole results instead of a 400-character preview")
    parser.add_argument("--doc", type=Path, default=DOCUMENT, help="use-case document")
    parser.add_argument("--out", type=Path, default=OUT, help="directory for the results files")
    args = parser.parse_args(argv)
    try:
        cases = select(parse_cases(args.doc), args.case)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.list or args.dry_run:
        print(f"No network. {len(cases)} scenario(s), {sum(len(c.steps) for c in cases)} steps from {args.doc.name}.")
        for case in cases:
            print(f"\n{case.identifier} {case.title}")
            for step in case.steps if args.dry_run else ():
                print("  " + json.dumps(step))
        return 0
    return asyncio.run(live(cases, args.out, full=args.full))


if __name__ == "__main__":
    raise SystemExit(main())
