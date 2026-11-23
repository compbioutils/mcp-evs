"""Bounded traversal engine (proposal Section 6.4, SOW-T3/T7/S12).

Breadth-first walk over selected relationship kinds with an explicit budget:

* ``maxDepth`` / ``maxNodes`` / ``maxEdges`` / ``maxRequests`` (requests include retries,
  because the shared :class:`Budget` is charged per HTTP attempt) and optional ``perKind``
  edge caps;
* **batched** expansion through ``GET /concept/{t_ver}?list=...&include=<flags>`` with at
  most 50 codes per request (10 when inverse relations are requested), never per-code
  fan-out; a visited set prevents refetching;
* a **fair scheduler** that admits candidate edges round-robin across relationship kinds so
  one prolific kind (e.g. ``inverseAssociations``) cannot starve the others;
* **exclusion polarity**: roles in the configured negative set are kept as edges with
  ``polarity: negative`` and full provenance but are not expanded unless asked;
* a :class:`Truncation` record naming the first bound that dropped anything, and per-hop
  provenance on every edge.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from ..core.context import Invocation
from ..core.envelopes import Truncation
from ..core.release import ReleaseContext
from .client import EvsClient
from .content import DEFAULT_NEGATIVE_ROLES
from .models import (
    Criterion,
    HopProvenance,
    Qualifier,
    Selector,
    SubtreeResult,
    TraversalBudget,
    TraversalEdge,
    TraversalNode,
    TraversalResult,
    TraversalStats,
    TreeNode,
)

INVERSE_KINDS = {"inverseRoles", "inverseAssociations"}
HIERARCHY_KINDS = {"parents", "children"}
BATCH_SIZE = 50
BATCH_SIZE_INVERSE = 10


# ------------------------------------------------------------------ fetching
@dataclass
class BatchFetcher:
    """Chunked batch retrieval that stops cleanly when the request budget runs out."""

    client: EvsClient
    ctx: ReleaseContext
    inv: Invocation
    chunk: int
    cache: dict[tuple[str, str], dict] = field(default_factory=dict)  # (code, include) -> raw

    async def fetch(self, codes: list[str], include: str) -> tuple[dict[str, dict], bool]:
        """Return ``({code: raw}, exhausted)``; ``exhausted`` is True if some codes were not
        fetched because the outbound budget was used up."""
        out: dict[str, dict] = {}
        todo: list[str] = []
        for c in dict.fromkeys(codes):
            hit = self.cache.get((c, include))
            if hit is not None:
                out[c] = hit
            else:
                todo.append(c)
        for i in range(0, len(todo), self.chunk):
            part = todo[i : i + self.chunk]
            if self.inv.budget.remaining <= 0:
                return out, True
            raws = await self.client.concepts(self.inv, self.ctx, part, include)
            for raw in raws:
                code = str(raw.get("code"))
                self.cache[(code, include)] = raw
                out[code] = raw
        return out, False


def _edges_from_raw(raw: dict[str, Any], kind: str, names: set[str] | None, negative_roles: frozenset[str]) -> list[dict[str, Any]]:
    """Normalise one relationship kind of a raw concept into candidate edge dicts."""
    items = raw.get(kind) or []
    incoming = kind in INVERSE_KINDS or kind == "parents"
    out = []
    for it in items:
        rel_type = it.get("type")
        if names and kind not in HIERARCHY_KINDS and rel_type not in names:
            continue
        target = str(it.get("relatedCode") or it.get("code"))
        quals = it.get("qualifiers")
        out.append(
            {
                "target": target,
                "targetName": it.get("relatedName") or it.get("name"),
                "targetLeaf": it.get("leaf"),
                "kind": kind,
                "type": rel_type,
                "direction": "incoming" if incoming else "outgoing",
                "polarity": "negative" if rel_type in negative_roles else "positive",
                "qualifiers": [Qualifier(type=str(q.get("type")), value=str(q.get("value"))) for q in quals] if quals else None,
            }
        )
    return out


# ----------------------------------------------------------------- traverse
class TraversalEngine:
    def __init__(self, client: EvsClient, *, negative_roles: frozenset[str] = DEFAULT_NEGATIVE_ROLES) -> None:
        self.client = client
        self.negative_roles = negative_roles

    def _fetcher(self, inv: Invocation, ctx: ReleaseContext, kinds: set[str]) -> BatchFetcher:
        chunk = BATCH_SIZE_INVERSE if kinds & INVERSE_KINDS else BATCH_SIZE
        return BatchFetcher(self.client, ctx, inv, chunk)

    def _hop_uri(self, ctx: ReleaseContext, code: str, kind: str) -> str:
        return self.client.http.public_url(f"/concept/{ctx.terminology_version}/{code}", {"include": kind})

    async def traverse(
        self,
        inv: Invocation,
        ctx: ReleaseContext,
        start: list[str],
        selectors: list[Selector],
        budget: TraversalBudget,
        *,
        include_exclusions: bool = False,
    ) -> tuple[TraversalResult, Truncation | None]:
        kinds = [s.kind for s in selectors]
        names_by_kind: dict[str, set[str] | None] = {s.kind: (set(s.names) if s.names else None) for s in selectors}
        include = ",".join(["minimal", *dict.fromkeys(kinds)])
        fetcher = self._fetcher(inv, ctx, set(kinds))
        per_kind_cap = budget.perKind or {}

        nodes: dict[str, TraversalNode] = {}
        edges: list[TraversalEdge] = []
        exclusions: list[TraversalEdge] = []
        edge_keys: set[tuple[str, str, str, str | None]] = set()
        per_kind_count: dict[str, int] = defaultdict(int)
        omitted_per_kind: dict[str, int] = defaultdict(int)
        trunc: Truncation | None = None
        max_depth_reached = 0

        def truncate(bound: str, limit: int, reached: int, omitted: int | None, exact: bool) -> None:
            nonlocal trunc
            if trunc is None:
                trunc = Truncation(occurred=True, bound=bound, limit=limit, reached=reached, omitted=omitted, exact=exact)

        start = list(dict.fromkeys(start))
        for c in start:
            nodes[c] = TraversalNode(code=c, depth=0, expanded=False)
        frontier = list(start)

        for depth in range(0, budget.maxDepth + 1):
            if not frontier:
                break
            # Fetch this depth's frontier in batches (bounded by the request budget).
            raws, exhausted = await fetcher.fetch(frontier, include)
            for code in frontier:
                raw = raws.get(code)
                n = nodes[code]
                if raw is None:
                    continue
                n.name = raw.get("name") or n.name
                n.leaf = raw.get("leaf", n.leaf)
                n.active = raw.get("active", n.active)
                n.expanded = True
                max_depth_reached = max(max_depth_reached, depth)
            if exhausted:
                unfetched = [c for c in frontier if c not in raws]
                truncate("maxRequests", budget.maxRequests, inv.budget.used, len(unfetched), False)
            if depth == budget.maxDepth:
                # Nodes at the deepest level are described but their relationships are not followed.
                pending = [c for c in frontier if c in raws and nodes[c].leaf is not True]
                for c in frontier:
                    if c in raws:
                        nodes[c].expanded = False
                if pending and trunc is None:
                    truncate("maxDepth", budget.maxDepth, depth, None, False)
                break

            # Collect candidate edges per kind, then admit them fairly (round-robin by kind).
            candidates: dict[str, list[tuple[str, dict[str, Any]]]] = {k: [] for k in dict.fromkeys(kinds)}
            for code in frontier:
                raw = raws.get(code)
                if raw is None:
                    continue
                for kind in candidates:
                    for cand in _edges_from_raw(raw, kind, names_by_kind.get(kind), self.negative_roles):
                        key = (code, cand["target"], kind, cand["type"])
                        if key in edge_keys:
                            continue
                        edge_keys.add(key)
                        candidates[kind].append((code, cand))

            next_frontier: list[str] = []
            queues = {k: list(v) for k, v in candidates.items() if v}
            while queues:
                for kind in list(queues):
                    q = queues[kind]
                    if not q:
                        del queues[kind]
                        continue
                    source, cand = q.pop(0)
                    cap = per_kind_cap.get(kind)
                    if cap is not None and per_kind_count[kind] >= cap:
                        omitted_per_kind[kind] += 1 + len(q)
                        truncate(f"perKind.{kind}", cap, per_kind_count[kind], None, False)
                        del queues[kind]
                        continue
                    if len(edges) + len(exclusions) >= budget.maxEdges:
                        omitted = sum(len(v) for v in queues.values()) + 1
                        for k2, v in queues.items():
                            omitted_per_kind[k2] += len(v) + (1 if k2 == kind else 0)
                        truncate("maxEdges", budget.maxEdges, len(edges) + len(exclusions), omitted, True)
                        queues = {}
                        break
                    edge = TraversalEdge(
                        source=source,
                        target=cand["target"],
                        targetName=cand["targetName"],
                        kind=kind,
                        type=cand["type"],
                        direction=cand["direction"],
                        polarity=cand["polarity"],
                        depth=depth + 1,
                        hop=HopProvenance(
                            depth=depth + 1,
                            relationship=cand["type"],
                            kind=kind,
                            direction=cand["direction"],
                            polarity=cand["polarity"],
                            release=ctx.release,
                            sourceUri=self._hop_uri(ctx, source, kind),
                            qualifiers=cand["qualifiers"],
                        ),
                    )
                    per_kind_count[kind] += 1
                    if cand["polarity"] == "negative" and not include_exclusions:
                        exclusions.append(edge)
                        continue
                    target = cand["target"]
                    if target not in nodes:
                        if len(nodes) >= budget.maxNodes:
                            # Drop the edge too, so every edge endpoint is a listed node.
                            per_kind_count[kind] -= 1
                            omitted_per_kind[kind] += 1
                            truncate("maxNodes", budget.maxNodes, len(nodes), None, False)
                            continue
                        nodes[target] = TraversalNode(
                            code=target, name=cand["targetName"], depth=depth + 1, leaf=cand["targetLeaf"], expanded=False
                        )
                        next_frontier.append(target)
                    edges.append(edge)
            frontier = next_frontier

        if trunc is not None and omitted_per_kind:
            trunc.perKind = {k: {"reached": per_kind_count[k], "omitted": omitted_per_kind[k]} for k in set(per_kind_count) | set(omitted_per_kind)}

        result = TraversalResult(
            start=start,
            nodes=list(nodes.values()),
            edges=edges,
            exclusions=exclusions,
            stats=TraversalStats(
                nodes=len(nodes), edges=len(edges), maxDepthReached=max_depth_reached, requests=inv.budget.used, perKind=dict(per_kind_count)
            ),
        )
        return result, trunc

    # ------------------------------------------------------------- subtree
    async def subtree(
        self,
        inv: Invocation,
        ctx: ReleaseContext,
        root: str,
        depth: int,
        criteria: list[Criterion],
        budget: TraversalBudget,
        *,
        prune: bool,
    ) -> tuple[SubtreeResult, Truncation | None]:
        from ..core.errors import invalid_request

        bad = [c.kind for c in criteria if c.kind not in ("property", "conceptStatus", "semanticType")]
        if bad:
            raise invalid_request("subtree criteria must be property, conceptStatus or semanticType", unsupported=bad)
        include = "minimal,children,properties" if criteria else "minimal,children"
        fetcher = BatchFetcher(self.client, ctx, inv, BATCH_SIZE)

        tree: dict[str, TreeNode] = {}
        children_of: dict[str, list[str]] = {}
        trunc: Truncation | None = None
        frontier = [root]
        tree[root] = TreeNode(code=root, depth=0, expanded=False)
        for d in range(0, depth + 1):
            if not frontier:
                break
            raws, exhausted = await fetcher.fetch(frontier, include)
            if d == 0 and root not in raws:
                from ..core.errors import not_found

                raise not_found(f"concept {root} not found", code=root)
            if exhausted and trunc is None:
                trunc = Truncation(occurred=True, bound="maxRequests", limit=budget.maxRequests, reached=inv.budget.used, omitted=len([c for c in frontier if c not in raws]), exact=False)
            next_frontier: list[str] = []
            for code in frontier:
                raw = raws.get(code)
                node = tree[code]
                if raw is None:
                    continue
                node.name = raw.get("name")
                node.leaf = raw.get("leaf")
                node.matches = _matches(raw, criteria) if criteria else None
                kids = raw.get("children") or []
                if d == depth:
                    node.expanded = False
                    if kids and trunc is None:
                        trunc = Truncation(occurred=True, bound="maxDepth", limit=depth, reached=d, omitted=None, exact=False)
                    continue
                node.expanded = True
                children_of[code] = []
                for kid in kids:
                    kc = str(kid.get("code"))
                    if kc in tree:
                        continue  # NCIt is a DAG; keep the first path only
                    if len(tree) >= budget.maxNodes:
                        if trunc is None:
                            trunc = Truncation(occurred=True, bound="maxNodes", limit=budget.maxNodes, reached=len(tree), omitted=None, exact=False)
                        break
                    tree[kc] = TreeNode(code=kc, name=kid.get("name"), depth=d + 1, leaf=kid.get("leaf"), expanded=False)
                    children_of[code].append(kc)
                    next_frontier.append(kc)
            frontier = next_frontier

        # Assemble nesting (and prune non-matching branches if requested).
        def build(code: str) -> TreeNode | None:
            node = tree[code]
            kids = [k for k in (build(c) for c in children_of.get(code, [])) if k is not None]
            node.children = kids
            if prune and criteria and node.matches is not True and not kids and code != root:
                return None
            return node

        root_node = build(root) or tree[root]
        all_nodes = list(_walk(root_node))
        match_count = sum(1 for n in all_nodes if n.matches)
        result = SubtreeResult(
            root=root_node,
            criteria=criteria,
            matchCount=match_count,
            nodeCount=len(all_nodes),
            stats=TraversalStats(nodes=len(all_nodes), edges=max(len(all_nodes) - 1, 0), maxDepthReached=max(n.depth for n in all_nodes), requests=inv.budget.used),
        )
        return result, trunc


def _walk(node: TreeNode):
    yield node
    for c in node.children:
        yield from _walk(c)


def _matches(raw: dict[str, Any], criteria: list[Criterion]) -> bool:
    props = raw.get("properties") or []
    for c in criteria:
        if c.kind == "conceptStatus":
            if (raw.get("conceptStatus") or "").lower() != (c.value or "").lower():
                return False
        elif c.kind == "semanticType":
            if not any(p.get("type") == "Semantic_Type" and (p.get("value") or "").lower() == (c.value or "").lower() for p in props):
                return False
        elif c.kind == "property":
            if not any(p.get("type") == c.name and (c.value is None or str(p.get("value")) == c.value) for p in props):
                return False
    return True
