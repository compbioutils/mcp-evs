#!/usr/bin/env python
"""Direct-call smoke check: is the MCP server working, without an LLM in the loop?

Runs the simplest use case from the specification (proposal UC-11 term resolution; design
doc 3 curator example; proposal Appendix A row 1) through the MCP client, exactly as an
agent would call it:

    1. the server starts and lists the tools an agent needs
    2. evs_lookup_concept "non-small cell lung carcinoma"   -> C2926
    3. evs_lookup_concept "NSCLC" (synonym)                  -> C2926
    4. evs_search_concepts "non-small cell lung carcinoma"   -> C2926 among the hits
    5. evs_get_paths C2926 toRoot                             -> at least one path to the root
    6. evs_lookup_concept "quarterly budget variance"        -> no match (negative control)

Each result must carry an NCIt release in provenance. Exit status is 0 when every step
passes, 1 otherwise.

    python scripts/check_server.py                    # spawn the server over stdio (live EVS)
    python scripts/check_server.py --mode fixtures    # offline, test fakes (needs '.[dev]')
    python scripts/check_server.py --mode live        # in-process, live EVS
    python scripts/check_server.py --mode http --url http://127.0.0.1:8000/mcp
    python scripts/check_server.py -v                 # also print each response envelope

If this passes and an agent run fails, the problem is on the agent/client side. If this
fails, fix the server first.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _mcp_target import add_target_args, call, error_payload, open_client  # noqa: E402

TERM = "non-small cell lung carcinoma"
SYNONYM = "NSCLC"
EXPECTED = "C2926"
NEGATIVE = "quarterly budget variance"
REQUIRED_TOOLS = ("evs_lookup_concept", "evs_search_concepts", "evs_get_paths")


@dataclass
class Step:
    name: str
    status: str = "FAIL"  # PASS | FAIL | SKIP
    detail: str = ""
    ms: float = 0.0
    response: Any = field(default=None, repr=False)


class Check(Exception):
    """A failed expectation inside a step."""


def releases(env: dict) -> set[str]:
    return {p["release"] for p in env.get("provenance", []) if p.get("release")}


def expect_release(env: dict) -> str:
    rel = releases(env)
    if not rel:
        raise Check("no NCIt release in provenance")
    return ", ".join(sorted(rel))


async def run(args) -> list[Step]:
    steps: list[Step] = []

    async def step(name: str, fn, *, skip: str | None = None) -> None:
        s = Step(name)
        steps.append(s)
        if skip:
            s.status, s.detail = "SKIP", skip
            return
        t0 = time.perf_counter()
        try:
            s.detail, s.response = await fn()
            s.status = "PASS"
        except Check as e:
            s.detail = str(e)
        except Exception as e:  # ToolError carries the server's JSON error envelope
            s.detail = f"{type(e).__name__}: {json.dumps(error_payload(e))}"
        finally:
            s.ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    try:
        cm = open_client(args.mode, profile=args.profile, url=args.url, python=args.python)
        client = await cm.__aenter__()
    except Exception as e:
        steps.append(Step("connect", "FAIL", f"{type(e).__name__}: {e}", (time.perf_counter() - t0) * 1000))
        return steps
    steps.append(Step("connect", "PASS", f"mode={args.mode}", (time.perf_counter() - t0) * 1000))

    try:
        async def list_tools():
            tools = await client.list_tools()
            names = {t.name for t in tools}
            missing = [n for n in REQUIRED_TOOLS if n not in names]
            if missing:
                raise Check(f"missing tools: {missing} (server exposes {len(names)})")
            return f"{len(names)} tools exposed", sorted(names)

        async def lookup(identifier: str, kinds: tuple[str, ...]):
            env = await call(client, "evs_lookup_concept", {"identifier": identifier})
            if not env.get("result"):
                raise Check(f"no match for {identifier!r}")
            top = env["result"][0]
            code, kind = top["concept"]["code"], top.get("matchKind")
            if code != EXPECTED:
                raise Check(f"top match {code} ({top['concept'].get('name')}), expected {EXPECTED}")
            if kind not in kinds:
                raise Check(f"matchKind={kind}, expected one of {kinds}")
            rel = expect_release(env)
            return f"{code} {top['concept'].get('name')!r} via {kind} {top.get('matchedTerm')!r}; release {rel}", env

        async def search():
            env = await call(client, "evs_search_concepts", {"term": TERM, "type": "match", "limit": 10})
            codes = [h["concept"]["code"] for h in env.get("result", [])]
            if EXPECTED not in codes:
                raise Check(f"{EXPECTED} not in hits {codes}")
            return f"{len(codes)} hit(s), {EXPECTED} at rank {codes.index(EXPECTED) + 1}; release {expect_release(env)}", env

        async def paths():
            env = await call(client, "evs_get_paths", {"code": EXPECTED, "kind": "toRoot"})
            result = env.get("result") or []
            if not result:
                raise Check("no paths returned")
            first = result[0]["concepts"]
            if first[0]["code"] != EXPECTED:
                raise Check(f"path starts at {first[0]['code']}, expected {EXPECTED}")
            chain = " > ".join(c.get("name") or c["code"] for c in first)
            return f"{len(result)} path(s); e.g. {chain}; release {expect_release(env)}", env

        async def negative():
            env = await call(client, "evs_lookup_concept", {"identifier": NEGATIVE})
            if env.get("result"):
                raise Check(f"expected no match, got {[m['concept']['code'] for m in env['result']]}")
            return "no match, as expected", env

        await step("list tools", list_tools)
        await step(f"lookup {TERM!r}", lambda: lookup(TERM, ("name", "synonym")))
        await step(f"lookup {SYNONYM!r} (synonym)", lambda: lookup(SYNONYM, ("synonym", "name")))
        await step(f"search {TERM!r}", search)
        await step(f"paths {EXPECTED} toRoot", paths,
                   skip="no C2926 pathsToRoot fixture; run --mode live or stdio" if args.mode == "fixtures" else None)
        await step(f"negative {NEGATIVE!r}", negative)
    finally:
        await cm.__aexit__(None, None, None)
    return steps


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    add_target_args(parser)
    parser.add_argument("-v", "--verbose", action="store_true", help="print each response envelope")
    parser.add_argument("--json", action="store_true", help="emit a JSON report instead of text")
    args = parser.parse_args(argv)

    steps = asyncio.run(run(args))
    ok = all(s.status != "FAIL" for s in steps) and any(s.status == "PASS" for s in steps[1:])

    if args.json:
        print(json.dumps({"ok": ok, "mode": args.mode, "profile": args.profile,
                          "steps": [{"name": s.name, "status": s.status, "detail": s.detail, "ms": round(s.ms, 1),
                                     **({"response": s.response} if args.verbose else {})} for s in steps]}, indent=2, default=str))
    else:
        print(f"evs-cadsr-mcp direct-call check  (mode={args.mode}, profile={args.profile})\n")
        for s in steps:
            print(f"  {s.status:4}  {s.name:<45} {s.ms:7.0f} ms  {s.detail}")
            if args.verbose and s.response is not None:
                print("        " + json.dumps(s.response, indent=2, default=str).replace("\n", "\n        "))
        print(f"\n{'OK' if ok else 'FAILED'}: {sum(s.status == 'PASS' for s in steps)} passed, "
              f"{sum(s.status == 'FAIL' for s in steps)} failed, {sum(s.status == 'SKIP' for s in steps)} skipped")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
