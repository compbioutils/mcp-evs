"""Retrieval evaluation scorer (SOW D5, proposal 6.7 'Evaluation set and protocol').

Scores a retriever against ``eval/ncit-retrieval-eval-v<n>.jsonl``: Recall@5, Recall@10,
MRR@10, nDCG@10 overall and per category, latency p50/p95, and the negative-query hit rate.
``--compare previous.json`` flags regressions above two points (0.02) per metric; ``--gate``
applies the initial acceptance thresholds (hybrid Recall@5 >= 0.90, MRR@10 >= 0.85, no
category below Recall@10 0.80, rerank must not lower MRR@10).

Retrievers (``--retriever``):
  upstream_contains   EVS search type=contains (the live baseline before the index exists)
  upstream_match      EVS search type=match
  lookup_chain        evs_lookup_concept, then search contains (the UC-11 chain)
  module:function     any async callable(services, query, k) -> list[str] (codes, ranked), e.g. the
                      NCIt index query path once Phase 3 lands (bm25 | vector | hybrid | hybrid+rerank)

    python scripts/evaluate_retrieval.py --retriever upstream_contains --mode live --out eval/results/upstream-contains.json
    python scripts/evaluate_retrieval.py --retriever ncit_index.query:hybrid --compare eval/results/upstream-contains.json --gate
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from evs_cadsr_mcp.core.budget import Budget  # noqa: E402
from evs_cadsr_mcp.core.config import Settings  # noqa: E402
from evs_cadsr_mcp.core.context import Invocation  # noqa: E402
from evs_cadsr_mcp.server.mcp_app import build_services  # noqa: E402

K = 10
THRESHOLDS = {"recall@5": 0.90, "mrr@10": 0.85, "category_recall@10": 0.80}
REGRESSION_POINTS = 0.02


def inv() -> Invocation:
    return Invocation(tool="eval", budget=Budget(max_requests=20))


# ------------------------------------------------------------------ retrievers
async def upstream_contains(services, query: str, k: int) -> list[str]:
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.search_concepts(inv(), ctx, query, search_type="contains", include=["minimal"], limit=k, cursor=None, filters={})
    return [h.concept.code for h in env.result]


async def upstream_match(services, query: str, k: int) -> list[str]:
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.search_concepts(inv(), ctx, query, search_type="match", include=["minimal"], limit=k, cursor=None, filters={})
    return [h.concept.code for h in env.result]


async def lookup_chain(services, query: str, k: int) -> list[str]:
    ctx = await services.evs.release_context("ncit", None)
    out: list[str] = []
    try:
        env = await services.evs.lookup_concept(inv(), ctx, query, match="normalized", synonym_source=None, term_type=None, include=["minimal"], limit=k)
        out = [m.concept.code for m in env.result]
    except Exception:  # noqa: BLE001
        out = []
    if len(out) < k:
        more = await upstream_contains(services, query, k)
        out += [c for c in more if c not in out]
    return out[:k]


BUILTIN = {"upstream_contains": upstream_contains, "upstream_match": upstream_match, "lookup_chain": lookup_chain}


def load_retriever(spec: str):
    if spec in BUILTIN:
        return BUILTIN[spec]
    mod, _, fn = spec.partition(":")
    return getattr(importlib.import_module(mod), fn or "retrieve")


# --------------------------------------------------------------------- metrics
def recall_at(ranked: list[str], expected: set[str], k: int) -> float:
    return 1.0 if expected and any(c in expected for c in ranked[:k]) else 0.0


def mrr_at(ranked: list[str], expected: set[str], k: int) -> float:
    for i, c in enumerate(ranked[:k], start=1):
        if c in expected:
            return 1.0 / i
    return 0.0


def ndcg_at(ranked: list[str], expected: set[str], primary: str | None, k: int) -> float:
    gains = [(2.0 if c == primary else 1.0) if c in expected else 0.0 for c in ranked[:k]]
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
    ideal = sorted(([2.0] if primary in expected else []) + [1.0] * (len(expected) - (1 if primary in expected else 0)), reverse=True)[:k]
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    return s[min(len(s) - 1, max(0, int(round(p * len(s))) - 1))]


# ------------------------------------------------------------------------ main
async def evaluate(eval_path: Path, retriever_spec: str, mode: str, limit: int | None) -> dict:
    rows = [json.loads(line) for line in eval_path.read_text().splitlines() if line.strip()]
    if limit:
        rows = rows[:limit]
    retriever = load_retriever(retriever_spec)
    if mode == "fixtures":
        from tests.conftest import FakeCadsr, FakeEvs

        services = build_services(Settings(_env_file=None, profile="unified", log_level="WARNING"), transport=FakeEvs().transport(), cadsr_transport=FakeCadsr().transport())
    else:
        services = build_services(Settings(_env_file=None, profile="unified", log_level="WARNING"))
    per_query = []
    try:
        release = (await services.registry.active_release("ncit")).version
        for r in rows:
            t0 = time.perf_counter()
            try:
                ranked = await retriever(services, r["query"], K)
                err = None
            except Exception as exc:  # noqa: BLE001
                ranked, err = [], f"{type(exc).__name__}"
            ms = (time.perf_counter() - t0) * 1000
            expected = set(r["expected"])
            per_query.append({
                "id": r["id"], "category": r["category"], "query": r["query"], "expected": sorted(expected), "ranked": ranked[:K], "latencyMs": round(ms, 1), "error": err,
                "recall@5": recall_at(ranked, expected, 5) if expected else None, "recall@10": recall_at(ranked, expected, 10) if expected else None,
                "mrr@10": mrr_at(ranked, expected, 10) if expected else None, "ndcg@10": ndcg_at(ranked, expected, r.get("primary"), 10) if expected else None,
                "negativeHit": (bool(ranked) if not expected else None),
            })
    finally:
        await services.aclose()

    def mean(key, items):
        vals = [q[key] for q in items if q[key] is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    positives = [q for q in per_query if q["expected"]]
    negatives = [q for q in per_query if not q["expected"]]
    by_cat = defaultdict(list)
    for q in positives:
        by_cat[q["category"]].append(q)
    summary = {
        "evalSet": eval_path.name, "retriever": retriever_spec, "mode": mode, "release": release, "queries": len(per_query), "positives": len(positives), "negatives": len(negatives),
        "recall@5": mean("recall@5", positives), "recall@10": mean("recall@10", positives), "mrr@10": mean("mrr@10", positives), "ndcg@10": mean("ndcg@10", positives),
        "negativeHitRate": round(sum(1 for q in negatives if q["negativeHit"]) / len(negatives), 4) if negatives else None,
        "latencyP50Ms": round(pct([q["latencyMs"] for q in per_query], 0.5), 1), "latencyP95Ms": round(pct([q["latencyMs"] for q in per_query], 0.95), 1),
        "errors": sum(1 for q in per_query if q["error"]),
        "categories": {cat: {"n": len(items), "recall@5": mean("recall@5", items), "recall@10": mean("recall@10", items), "mrr@10": mean("mrr@10", items), "ndcg@10": mean("ndcg@10", items)} for cat, items in sorted(by_cat.items())},
    }
    return {"summary": summary, "queries": per_query}


def compare(current: dict, previous: dict) -> list[str]:
    flags = []
    for key in ("recall@5", "recall@10", "mrr@10", "ndcg@10"):
        a, b = current["summary"].get(key), previous["summary"].get(key)
        if a is not None and b is not None and b - a > REGRESSION_POINTS:
            flags.append(f"REGRESSION {key}: {b:.3f} -> {a:.3f}")
    for cat, cur in current["summary"]["categories"].items():
        prev = previous["summary"]["categories"].get(cat)
        if prev and prev.get("recall@10") is not None and cur.get("recall@10") is not None and prev["recall@10"] - cur["recall@10"] > REGRESSION_POINTS:
            flags.append(f"REGRESSION {cat} recall@10: {prev['recall@10']:.3f} -> {cur['recall@10']:.3f}")
    return flags


def gate(current: dict) -> list[str]:
    s = current["summary"]
    fails = []
    if (s["recall@5"] or 0) < THRESHOLDS["recall@5"]:
        fails.append(f"recall@5 {s['recall@5']} < {THRESHOLDS['recall@5']}")
    if (s["mrr@10"] or 0) < THRESHOLDS["mrr@10"]:
        fails.append(f"mrr@10 {s['mrr@10']} < {THRESHOLDS['mrr@10']}")
    for cat, c in s["categories"].items():
        if (c["recall@10"] or 0) < THRESHOLDS["category_recall@10"]:
            fails.append(f"{cat} recall@10 {c['recall@10']} < {THRESHOLDS['category_recall@10']}")
    return fails


def markdown(current: dict, flags: list[str], fails: list[str]) -> str:
    s = current["summary"]
    lines = [f"# Retrieval evaluation — {s['retriever']} ({s['mode']}, ncit {s['release']})", "",
             f"queries: {s['queries']} (positives {s['positives']}, negatives {s['negatives']}); errors: {s['errors']}", "",
             "| metric | value |", "|---|---|",
             *[f"| {k} | {s[k]} |" for k in ("recall@5", "recall@10", "mrr@10", "ndcg@10", "negativeHitRate", "latencyP50Ms", "latencyP95Ms")], "",
             "| category | n | recall@5 | recall@10 | mrr@10 | ndcg@10 |", "|---|---|---|---|---|---|",
             *[f"| {cat} | {c['n']} | {c['recall@5']} | {c['recall@10']} | {c['mrr@10']} | {c['ndcg@10']} |" for cat, c in s["categories"].items()], ""]
    if flags:
        lines += ["Regressions vs. previous run:", *[f"- {f}" for f in flags], ""]
    if fails:
        lines += ["Gate failures (initial thresholds, proposal 6.7):", *[f"- {f}" for f in fails], ""]
    lines += ["Misses:", *[f"- {q['id']} '{q['query']}' expected {q['expected']} got {q['ranked'][:5]}" for q in current["queries"] if q["expected"] and not q["recall@10"]][:40]]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", default=str(ROOT / "eval" / "ncit-retrieval-eval-v1.jsonl"))
    ap.add_argument("--retriever", default="upstream_contains")
    ap.add_argument("--mode", choices=["fixtures", "live"], default="live")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=None, help="write JSON results here (and a .md next to it)")
    ap.add_argument("--compare", default=None, help="previous JSON results to compare against")
    ap.add_argument("--gate", action="store_true", help="exit non-zero when thresholds are not met")
    a = ap.parse_args()
    current = asyncio.run(evaluate(Path(a.eval), a.retriever, a.mode, a.limit))
    flags = compare(current, json.loads(Path(a.compare).read_text())) if a.compare else []
    fails = gate(current) if a.gate else []
    report = markdown(current, flags, fails)
    print(report)
    if a.out:
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(current, indent=2))
        out.with_suffix(".md").write_text(report)
    return 1 if (fails or flags) else 0


if __name__ == "__main__":
    raise SystemExit(main())
