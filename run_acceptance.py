"""Run the documented test tiers and write the results package (SOW D4 'tests with documented
results', D6 benchmark). Produces JUnit XML per tier plus a Markdown summary.

    python scripts/run_acceptance.py                 # offline tiers over fixtures
    ECM_LIVE=1 python scripts/run_acceptance.py --live   # adds live smoke + live acceptance
    python scripts/run_acceptance.py --out reports/2026-11-01

Tiers map to the proposal's test taxonomy (Section 12): unit, contract (incl. T-REL, T-FAIL,
T-BUDGET, T-BATCH, T-TRAV, T-POL, T-PROV, T-LIC, T-SEC, T-RED, T-IFACE), conformance (T-CONF,
T-PROF), acceptance (T-ACC), live (T-LIVE), and the benchmark pack (T-PERF).
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TIERS = {
    "unit": ["tests/unit"],
    "contract": ["tests/contract"],
    "conformance": ["tests/conformance"],
    "acceptance": ["tests/acceptance"],
}
LIVE_TIERS = {"live-smoke": ["tests/live", "-m", "live"], "acceptance-live": ["tests/acceptance", "-m", "live"]}


def run_tier(name: str, args: list[str], out: Path) -> dict:
    junit = out / f"junit-{name}.xml"
    cmd = [sys.executable, "-m", "pytest", "-q", "--junitxml", str(junit), *args]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    (out / f"pytest-{name}.log").write_text(proc.stdout + proc.stderr)
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0, "time": 0.0}
    if junit.exists():
        for suite in ET.parse(junit).getroot().iter("testsuite"):
            for k in ("tests", "failures", "errors", "skipped"):
                totals[k] += int(suite.get(k, 0))
            totals["time"] += float(suite.get("time", 0))
    totals["exit"] = proc.returncode
    return totals


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="results directory (default reports/<timestamp>)")
    ap.add_argument("--live", action="store_true", help="also run live tiers (requires ECM_LIVE=1)")
    ap.add_argument("--no-benchmark", action="store_true")
    a = ap.parse_args()
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    out = Path(a.out) if a.out else ROOT / "reports" / stamp
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    if a.live:
        env.setdefault("ECM_LIVE", "1")
        os.environ.update(env)

    results = {name: run_tier(name, args, out) for name, args in TIERS.items()}
    if a.live:
        results.update({name: run_tier(name, args, out) for name, args in LIVE_TIERS.items()})

    bench_note = "skipped"
    if not a.no_benchmark:
        mode = "live" if a.live else "fixtures"
        proc = subprocess.run([sys.executable, "scripts/benchmark.py", "--mode", mode, "--repeat", "3", "--out", str(out / "benchmark.md")], cwd=ROOT, capture_output=True, text=True)
        bench_note = f"benchmark.md ({mode}, exit {proc.returncode})"
        (out / "benchmark.log").write_text(proc.stdout + proc.stderr)

    try:
        git = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip() or "n/a"
    except OSError:
        git = "n/a"
    lines = [
        f"# Test results — {stamp}", "",
        f"commit: `{git}`  python: {platform.python_version()}  platform: {platform.platform()}  live: {bool(a.live)}", "",
        "| tier | tests | failures | errors | skipped | time (s) | exit |", "|---|---|---|---|---|---|---|",
    ]
    ok = True
    for name, t in results.items():
        ok = ok and t["exit"] == 0
        lines.append(f"| {name} | {t['tests']} | {t['failures']} | {t['errors']} | {t['skipped']} | {t['time']:.1f} | {t['exit']} |")
    lines += ["", f"benchmark: {bench_note}", "", "Artifacts: junit-<tier>.xml, pytest-<tier>.log, benchmark.md in this directory.",
              "", "Fixture status: run `evs-cadsr-mcp baseline export` and read conformance-mock.json to see which fixtures are live recordings.",
              "", f"Overall: {'PASS' if ok else 'FAIL'}"]
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
