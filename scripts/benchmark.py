"""Benchmark pack (proposal 10.6, SOW-S15).

Runs representative scenarios cold (empty cache) and warm, and reports per scenario:
terminology/release, cache state, result size, outbound call count, error rate, p50 and p95
latency. ``--mode fixtures`` runs offline over the test fakes (deterministic, no network);
``--mode live`` runs against the real upstreams (be a good citizen: low repeat counts).

    python scripts/benchmark.py --mode fixtures --repeat 5 --out benchmark.md
    python scripts/benchmark.py --mode live --repeat 3
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from evs_cadsr_mcp.core.budget import Budget  # noqa: E402
from evs_cadsr_mcp.core.config import Settings  # noqa: E402
from evs_cadsr_mcp.core.context import Invocation  # noqa: E402
from evs_cadsr_mcp.evs.models import Selector, TraversalBudget  # noqa: E402
from evs_cadsr_mcp.server.mcp_app import build_services  # noqa: E402


def inv() -> Invocation:
    return Invocation(tool="bench", budget=Budget(max_requests=100))


def scenarios(svc):
    async def get_concept():
        ctx = await svc.evs.release_context("ncit", None)
        return await svc.evs.get_concept(inv(), ctx, "C3224", ["summary"])

    async def batch():
        ctx = await svc.evs.release_context("ncit", None)
        return await svc.evs.get_concepts(inv(), ctx, ["C3224", "C2926"], ["minimal"])

    async def search():
        ctx = await svc.evs.release_context("ncit", None)
        return await svc.evs.search_concepts(inv(), ctx, "melanoma", search_type="contains", include=None, limit=10, cursor=None, filters={})

    async def traverse():
        ctx = await svc.evs.release_context("ncit", None)
        return await svc.evs.traverse(inv(), ctx, ["C3224"], [Selector(kind="children"), Selector(kind="roles")], TraversalBudget(maxDepth=2), include_exclusions=False)

    async def paths():
        ctx = await svc.evs.release_context("ncit", None)
        return await svc.evs.get_paths(inv(), ctx, "C3224", "toRoot", None)

    out = {"evs_get_concept (summary)": get_concept, "evs_get_concepts (batch of 2)": batch, "evs_search_concepts (10)": search,
           "evs_traverse (depth 2)": traverse, "evs_get_paths (toRoot)": paths}
    if svc.cadsr is not None:
        async def cde():
            return await svc.cadsr.get_data_element(inv(), "2192199", "1.0", None)

        async def pvs():
            return await svc.cadsr.get_permissible_values(inv(), "2192199", "1.0", limit=100, cursor=None)

        out["cadsr_get_data_element (2192199)"] = cde
        out["cadsr_get_permissible_values"] = pvs
    if svc.map is not None:
        async def resolve():
            return await svc.map.resolve_cde_concepts(inv(), "2192199", "1.0", None, include_pvs=True)

        out["map_resolve_cde_concepts (+PVs)"] = resolve
    return out


async def run_scenario(name, fn, repeat):
    rows = []
    for state in ("cold", "warm"):
        lat, outbound, sizes, errors = [], [], [], 0
        n = 1 if state == "cold" else repeat
        for _ in range(n):
            t0 = time.perf_counter()
            try:
                env = await fn()
                lat.append((time.perf_counter() - t0) * 1000)
                outbound.append(env.meta.outboundRequests)
                sizes.append(len(env.model_dump_json(exclude_none=True)))
            except Exception as exc:  # noqa: BLE001
                errors += 1
                lat.append((time.perf_counter() - t0) * 1000)
                print(f"  {name} [{state}] error: {type(exc).__name__}: {exc}", file=sys.stderr)
        p50 = statistics.median(lat) if lat else float("nan")
        p95 = sorted(lat)[max(int(round(0.95 * len(lat))) - 1, 0)] if lat else float("nan")
        rows.append((name, state, f"{p50:.0f}", f"{p95:.0f}", max(outbound) if outbound else "-", max(sizes) if sizes else "-", f"{errors}/{n}"))
    return rows


async def main(mode: str, repeat: int, out: str | None) -> None:
    if mode == "fixtures":
        from tests.conftest import FakeCadsr, FakeEvs

        fe, fc = FakeEvs(), FakeCadsr()
        svc = build_services(Settings(_env_file=None, profile="unified", log_level="WARNING"), transport=fe.transport(), cadsr_transport=fc.transport())
    else:
        svc = build_services(Settings(_env_file=None, profile="unified", log_level="WARNING"))
    try:
        active = await svc.registry.active_release("ncit")
        rows = []
        for name, fn in scenarios(svc).items():
            rows.extend(await run_scenario(name, fn, repeat))
        header = f"# Benchmark ({mode}; ncit {active.version}; repeat={repeat})\n\n| scenario | cache | p50 ms | p95 ms | outbound calls | result bytes | errors |\n|---|---|---|---|---|---|---|\n"
        table = "".join(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | {r[6]} |\n" for r in rows)
        slo = ("\nSLOs (proposal 10.6): cached concept tools p95 < 800 ms; live single-concept < 3 s; bounded traversal at default "
               "budgets < 10 s. The 'demonstrated-versus-upstream-gap' column is the difference between cold and warm rows.\n")
        report = header + table + slo
        print(report)
        if out:
            Path(out).write_text(report)
    finally:
        await svc.aclose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["fixtures", "live"], default="fixtures")
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    asyncio.run(main(a.mode, a.repeat, a.out))
