"""Contract tests for Phase 2: traversal engine (T-TRAV, T-BUDGET, T-POL, T-PROV, T-BATCH),
filtered sub-tree (SOW-T7) and the concept-set planner (SOW-T5), over the synthetic graph in
tests/fixtures/evs/graph_small.json."""

from __future__ import annotations

import pytest

from evs_cadsr_mcp.core.budget import Budget
from evs_cadsr_mcp.core.context import Invocation
from evs_cadsr_mcp.core.errors import EvsMcpError
from evs_cadsr_mcp.evs.models import Criterion, Selector, TraversalBudget
from evs_cadsr_mcp.server.mcp_app import Services
from tests.conftest import FakeEvs


def inv(max_requests: int = 50) -> Invocation:
    return Invocation(tool="t", budget=Budget(max_requests=max_requests))


CHILDREN_AND_ROLES = [Selector(kind="children"), Selector(kind="roles")]


# ------------------------------------------------------------------- traverse
async def test_traverse_batches_per_depth_and_reports_depth_bound(services: Services, fake_evs: FakeEvs):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.traverse(inv(), ctx, ["C3224"], CHILDREN_AND_ROLES, TraversalBudget(maxDepth=2), include_exclusions=False)
    r = env.result
    codes = {n.code for n in r.nodes}
    assert {"C3224", "C3510", "C7712", "C4236", "C36859", "C12612", "C8410", "C4022", "C12470", "C7713", "C12775"} == codes
    assert "C99901" not in codes  # only reachable through an excluded role
    # one batch request per depth level, never per code
    assert env.meta.outboundRequests == 3 and r.stats.requests == 3
    assert fake_evs.path_counts[f"/concept/ncit_{fake_evs.active}"] == 3
    assert all("list" in r_.url.params for r_ in fake_evs.requests if r_.url.path.endswith(f"/concept/ncit_{fake_evs.active}"))
    # deepest level is described but not expanded; non-leaf nodes there -> maxDepth truncation
    assert env.truncation and env.truncation.bound == "maxDepth" and env.truncation.exact is False
    assert {n.code for n in r.nodes if n.depth == 2 and not n.expanded} >= {"C12470", "C12775"}
    assert r.stats.maxDepthReached == 2 and r.stats.perKind == {"children": 6, "roles": 5}


async def test_traverse_polarity_exclusions_not_expanded_by_default(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.traverse(inv(), ctx, ["C3224"], CHILDREN_AND_ROLES, TraversalBudget(maxDepth=2), include_exclusions=False)
    assert len(env.result.exclusions) == 1
    ex = env.result.exclusions[0]
    assert ex.type == "Disease_Excludes_Finding" and ex.polarity == "negative" and ex.target == "C36122"
    assert ex.hop.polarity == "negative" and ex.hop.release == ctx.release and "C3224" in ex.hop.sourceUri
    assert all(e.polarity == "positive" for e in env.result.edges)
    assert any("includeExclusions" in w for w in env.warnings)


async def test_traverse_include_exclusions_follows_negative_edges(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.traverse(inv(), ctx, ["C3224"], CHILDREN_AND_ROLES, TraversalBudget(maxDepth=2), include_exclusions=True)
    codes = {n.code for n in env.result.nodes}
    assert {"C36122", "C99901"} <= codes and env.result.exclusions == []
    assert any(e.polarity == "negative" for e in env.result.edges)


async def test_traverse_per_hop_provenance_fields(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.traverse(inv(), ctx, ["C3224"], [Selector(kind="associations"), Selector(kind="parents")], TraversalBudget(maxDepth=1), include_exclusions=False)
    by_kind = {}
    for e in env.result.edges:
        by_kind.setdefault(e.kind, e)
    assoc, parent = by_kind["associations"], by_kind["parents"]
    assert assoc.hop.depth == 1 and assoc.hop.relationship == "Concept_In_Subset" and assoc.hop.direction == "outgoing"
    assert assoc.hop.qualifiers and assoc.hop.qualifiers[0].type == "Source" and assoc.hop.evidence == "asserted"
    assert parent.hop.direction == "incoming" and parent.hop.qualifiers is None  # explicitly null, not omitted
    assert parent.hop.release == ctx.release and parent.hop.sourceUri.endswith("include=parents")


async def test_traverse_fair_scheduler_alternates_kinds(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.traverse(inv(), ctx, ["C3224"], CHILDREN_AND_ROLES, TraversalBudget(maxDepth=1, maxEdges=4), include_exclusions=False)
    kinds = [e.kind for e in env.result.edges]
    assert kinds.count("children") == 2 and kinds.count("roles") == 2  # not 3 children + 1 role
    t = env.truncation
    assert t.bound == "maxEdges" and t.limit == 4 and t.reached == 4 and t.omitted == 2 and t.exact is True
    assert t.perKind["children"]["omitted"] == 1 and t.perKind["roles"]["omitted"] == 1


async def test_traverse_max_nodes_drops_edge_and_node_together(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.traverse(inv(), ctx, ["C3224"], CHILDREN_AND_ROLES, TraversalBudget(maxDepth=2, maxNodes=3), include_exclusions=False)
    assert len(env.result.nodes) == 3 and env.truncation.bound == "maxNodes" and env.truncation.limit == 3
    node_codes = {n.code for n in env.result.nodes}
    assert all(e.target in node_codes for e in env.result.edges)


async def test_traverse_per_kind_cap(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.traverse(inv(), ctx, ["C3224"], CHILDREN_AND_ROLES, TraversalBudget(maxDepth=1, perKind={"roles": 1}), include_exclusions=False)
    kinds = [e.kind for e in env.result.edges]
    assert kinds.count("roles") == 1 and kinds.count("children") == 3
    assert env.truncation.bound == "perKind.roles" and env.truncation.perKind["roles"]["omitted"] == 2


async def test_traverse_request_budget_includes_everything(services: Services, fake_evs: FakeEvs):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.traverse(inv(), ctx, ["C3224"], CHILDREN_AND_ROLES, TraversalBudget(maxDepth=2, maxRequests=1), include_exclusions=False)
    assert env.meta.outboundRequests == 1
    t = env.truncation
    assert t.bound == "maxRequests" and t.limit == 1 and t.omitted == 5 and t.exact is False
    assert all(not n.expanded for n in env.result.nodes if n.depth == 1)


async def test_traverse_dedupes_start_and_visited(services: Services, fake_evs: FakeEvs):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.traverse(inv(), ctx, ["C3224", "C3224", "C3510"], [Selector(kind="children")], TraversalBudget(maxDepth=1), include_exclusions=False)
    assert env.result.start == ["C3224", "C3510"]
    # C3510 is both a start node and a child of C3224: fetched once, listed once
    assert [n.code for n in env.result.nodes].count("C3510") == 1
    lists = [r.url.params["list"] for r in fake_evs.requests if "list" in r.url.params]
    assert sum(lst.split(",").count("C3510") for lst in lists) == 1


async def test_traverse_validation(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    with pytest.raises(EvsMcpError) as ei:
        await services.evs.traverse(inv(), ctx, [], CHILDREN_AND_ROLES, TraversalBudget(), include_exclusions=False)
    assert ei.value.code == "invalid_request"


# -------------------------------------------------------------------- subtree
MALIGNANT = [Criterion(kind="semanticType", value="Neoplastic Process"), Criterion(kind="property", name="Neoplastic_Status", value="Malignant")]


async def test_subtree_flags_matches_and_nests(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.get_subtree(inv(), ctx, "C3224", 2, MALIGNANT, TraversalBudget(), prune=False)
    r = env.result
    assert r.root.code == "C3224" and r.root.matches is True
    assert [c.code for c in r.root.children] == ["C3510", "C7712", "C4236"]
    c3510 = r.root.children[0]
    assert [c.code for c in c3510.children] == ["C8410", "C4022"]
    assert r.nodeCount == 7 and r.matchCount == 5
    assert {n.code: n.matches for n in r.root.children}["C4236"] is False
    assert env.meta.outboundRequests == 3 and env.truncation is None


async def test_subtree_prune_drops_non_matching_branches(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.get_subtree(inv(), ctx, "C3224", 2, MALIGNANT, TraversalBudget(), prune=True)
    codes = _codes(env.result.root)
    assert "C4236" not in codes and "C4022" not in codes and env.result.nodeCount == 5


async def test_subtree_status_criterion_and_depth_truncation(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.get_subtree(inv(), ctx, "C3224", 1, [Criterion(kind="conceptStatus", value="Retired_Concept")], TraversalBudget(), prune=False)
    assert env.result.matchCount == 0 and env.truncation.bound == "maxDepth"  # C4022 sits at depth 2
    deeper = await services.evs.get_subtree(inv(), ctx, "C3224", 2, [Criterion(kind="conceptStatus", value="Retired_Concept")], TraversalBudget(), prune=True)
    assert deeper.result.matchCount == 1 and _codes(deeper.result.root) == ["C3224", "C3510", "C4022"]


async def test_subtree_rejects_relationship_criteria_and_missing_root(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    with pytest.raises(EvsMcpError) as ei:
        await services.evs.get_subtree(inv(), ctx, "C3224", 1, [Criterion(kind="role", name="x", targetCode="C1")], TraversalBudget(), prune=False)
    assert ei.value.code == "invalid_request"
    with pytest.raises(EvsMcpError) as ei:
        await services.evs.get_subtree(inv(), ctx, "C12345", 1, [], TraversalBudget(), prune=False)
    assert ei.value.code == "not_found"


def _codes(node) -> list[str]:
    out = [node.code]
    for c in node.children:
        out.extend(_codes(c))
    return out


# -------------------------------------------------------------- find_concepts
PROP_MALIGNANT = Criterion(kind="property", name="Neoplastic_Status", value="Malignant")
ROLE_SKIN = Criterion(kind="role", name="Disease_Has_Primary_Anatomic_Site", targetCode="C12470")
ASSOC_TYPE = Criterion(kind="associationType", name="Has_Data_Element")
SUBSET_GDC = Criterion(kind="subset", value="C177537")


async def test_find_single_property_uses_search_with_upstream_paging(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.find_concepts(inv(), ctx, [PROP_MALIGNANT], "AND", limit=2, cursor=None)
    assert [c.code for c in env.result.concepts] == ["C3224", "C3510"]
    assert env.page.total == 5 and env.page.nextCursor
    assert env.result.plan.path == "single_route" and env.result.plan.steps[0].route == "search"
    assert "property=Neoplastic_Status" in env.result.plan.steps[0].endpoint
    nxt = await services.evs.find_concepts(inv(), ctx, [PROP_MALIGNANT], "AND", limit=2, cursor=env.page.nextCursor)
    assert [c.code for c in nxt.result.concepts] == ["C7712", "C8410"]


async def test_find_role_target_uses_inverse_roles(services: Services, fake_evs: FakeEvs):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.find_concepts(inv(), ctx, [ROLE_SKIN], "AND", limit=10, cursor=None)
    assert [c.code for c in env.result.concepts] == ["C3510", "C4017"]  # other role types on the same target filtered out
    assert env.result.plan.steps[0].route == "inverseRoles" and env.meta.outboundRequests == 1
    assert fake_evs.path_counts[f"/concept/ncit_{fake_evs.active}/C12470/inverseRoles"] == 1


async def test_find_association_type_pages_terminology_wide_endpoint(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.find_concepts(inv(), ctx, [ASSOC_TYPE], "AND", limit=10, cursor=None)
    assert [c.code for c in env.result.concepts] == ["C2926", "C3224", "C3510"]
    assert env.result.plan.steps[0].route == "associationsByType" and env.result.plan.steps[0].complete


async def test_find_and_intersects_enumerated_routes(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.find_concepts(inv(), ctx, [PROP_MALIGNANT, ROLE_SKIN], "AND", limit=10, cursor=None)
    assert [c.code for c in env.result.concepts] == ["C3510"]
    assert env.result.plan.path == "enumerate_and_intersect"
    assert {s.route for s in env.result.plan.steps} == {"search", "inverseRoles"}


async def test_find_and_search_capable_criteria_combine_into_one_query(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.find_concepts(inv(), ctx, [PROP_MALIGNANT, SUBSET_GDC], "AND", limit=10, cursor=None)
    assert [c.code for c in env.result.concepts] == ["C3224"]
    assert env.result.plan.path == "search_combined" and env.meta.outboundRequests == 1
    assert "subset=C177537" in env.result.plan.steps[0].endpoint


async def test_find_or_unions_and_pages_in_memory(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    env = await services.evs.find_concepts(inv(), ctx, [ROLE_SKIN, ASSOC_TYPE], "OR", limit=3, cursor=None)
    assert [c.code for c in env.result.concepts] == ["C2926", "C3224", "C3510"]
    assert env.page.total == 4 and env.page.nextCursor and env.result.plan.path == "enumerate_and_union"
    nxt = await services.evs.find_concepts(inv(), ctx, [ROLE_SKIN, ASSOC_TYPE], "OR", limit=3, cursor=env.page.nextCursor)
    assert [c.code for c in nxt.result.concepts] == ["C4017"] and nxt.page.nextCursor is None


async def test_find_sparql_only_combination_is_capability_unavailable(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    two_props = [PROP_MALIGNANT, Criterion(kind="property", name="ICD-O-3_Code", value="8720/3")]
    with pytest.raises(EvsMcpError) as ei:
        await services.evs.find_concepts(inv(), ctx, two_props, "AND", limit=10, cursor=None)
    assert ei.value.code == "capability_unavailable"
    assert ei.value.details["plan"]["path"] == "sparql_required" and "intersect" in ei.value.hint
    # semanticType is sent as the Semantic_Type property, so it also counts against the one-property limit.
    with pytest.raises(EvsMcpError) as ei:
        await services.evs.find_concepts(
            inv(), ctx, [PROP_MALIGNANT, Criterion(kind="semanticType", value="Neoplastic Process")], "AND", limit=10, cursor=None)
    assert ei.value.details["plan"]["path"] == "sparql_required"


async def test_find_validation(services: Services):
    ctx = await services.evs.release_context("ncit", None)
    for bad in ([], [Criterion(kind="conceptStatus", value="Retired_Concept")], [Criterion(kind="role", name="x")]):
        with pytest.raises(EvsMcpError) as ei:
            await services.evs.find_concepts(inv(), ctx, bad, "AND", limit=10, cursor=None)
        assert ei.value.code == "invalid_request"
