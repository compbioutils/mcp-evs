# SOW traceability matrix

Maps the SOW's minimum tool capabilities (T1–T8), scope paragraphs (S9–S16) and deliverables
(D1–D9), as numbered in the proposal, to the code, tools and tests in this repository.
Status: **built** (code present, offline tests written), **verified** (tests executed green),
**pending** (needs an NCI decision or an environment with dependencies).

As of this writing the whole suite is **built but not yet verified** — see README "Tests".

## Tool capabilities

| SOW | Capability | Tools | Code | Tests | Status |
|---|---|---|---|---|---|
| T1 | lookup by code, name, synonym | `evs_lookup_concept`, `evs_get_concept` | `evs/service.py::lookup_concept` | contract `test_lookup_by_code_then_synonym`; acceptance `test_t1_*` | built |
| T2 | full-text / typeahead / vector / hybrid | `evs_search_concepts`, `evs_suggest_concepts`; `evs_semantic_search` **pending** | `evs/service.py`; index: Phase 3 | contract `test_search_paging_cursor_bound_to_release`; acceptance `test_t2_*`; `scripts/evaluate_retrieval.py` | full-text/typeahead built; vector/hybrid pending embedding-model decision |
| T3 | bounded multi-hop traversal with budgets, truncation, polarity, per-hop provenance | `evs_traverse` | `evs/traversal.py` | contract `test_evs_traversal_sets.py` (depth, nodes, edges, perKind, requests incl. retries, fairness, polarity, provenance, dedup); acceptance `test_t3_*` | built |
| T4 | synonyms, definitions, properties, associations | `evs_get_concept`, `evs_get_concepts`, `evs_get_relationships` | `evs/content.py`, `evs/service.py` | contract `test_get_concept_*`, `test_batch_uses_list_endpoint_not_fan_out`, `test_relationships_filter_and_polarity`; acceptance `test_t4_*` | built |
| T5 | concept sets by roles / associations / properties / combinations | `evs_find_concepts` | `evs/find_concepts.py` | contract `test_find_*` (8 planner paths incl. `sparql_required`); acceptance `test_t5_*` | built; SPARQL fallback pending NCI approval |
| T6 | subset / value-set membership | `evs_list_subsets`, `evs_get_subset_members` | `evs/service.py` | contract `test_subsets_and_members`; acceptance `test_t6_*` | built |
| T7 | targeted sub-trees by attribute | `evs_get_subtree` | `evs/traversal.py::subtree` | contract `test_subtree_*`; acceptance `test_t7_*` | built |
| T8 | cross-maps with license gate | `evs_get_concept_maps`, `evs_list_mapsets`, `evs_get_mapset_entries` | `evs/service.py`, `core/config.py` gated list | contract `test_concept_maps_withhold_*`, `test_mapset_entries_gate_*`, `_with_key_*`; acceptance `test_t8_*` | built; "codes without key" policy pending review decision |

## Scope paragraphs

| SOW | Requirement | Where | Tests | Status |
|---|---|---|---|---|
| S9 | hardening; release-aware NCIt index; citation-ready responses; atomic activation/rollback | envelopes/provenance (`core/envelopes.py`); index **pending** | T-CONF, T-PROV | partial: citations built; index pending |
| S10 | retrieval-quality enhancements with before/after reporting | protocol and scorer (`docs/retrieval-evaluation-protocol.md`, `scripts/evaluate_retrieval.py`) | per-retriever runs | protocol built; techniques pending index |
| S11 | release identity structurally required; fail closed; upstream register | `core/release.py`, cursors, cache keys | contract `test_requested_live_release_is_pinned_in_path`, `test_release_not_live_fails_closed`, `test_upstream_version_drift_fails_closed`, cursor tests; acceptance `test_s11_*` | built |
| S12 | budgets incl. retries; truncation; no redundant fetch; fairness; polarity; batch endpoint; approved fallbacks | `core/budget.py`, `core/http_client.py`, `evs/traversal.py` | `test_retries_count_against_budget`, `test_budget_exhaustion_*`, `test_traverse_*` | built |
| S13 | Tier-2 targets; license keys | `terminology` argument; `ECM_LICENSE_KEY`; gated list | T-LIC | built; Tier-2 selection pending review |
| S14 | auth, authz, transport security, secrets, audit with redaction | `core/auth.py`, `server/middleware.py`, `core/audit.py`, `server/app.py` | `test_platform.py` (scopes, rate limit, audit redaction, 400/421/413) | built |
| S15 | benchmarks: release, cache state, size, outbound calls, error rate, p50/p95, gaps | `scripts/benchmark.py` | run via `scripts/run_acceptance.py` | built |
| S16 | shared interface baseline; change control; tests and docs; deployment guidance | `spec/interface-baseline/`, `server/baseline.py`, `docs/change-control.md` | `test_interface_baseline.py` (classifier verified; e2e after export) | built; freeze pending export |

## Deliverables

| SOW | Deliverable | Artifact | Status |
|---|---|---|---|
| D1 | prototype baseline assessment | `design-docs-and-req/nci-si-mcp-prototype-comparison.md` | delivered (design phase) |
| D2 | architecture and design document | `docs/evs-cadsr-mcp-proposal.md`, `design-docs-and-req/*` | delivered (design phase) |
| D3 | MCP server codebase | `src/evs_cadsr_mcp/` (48 tools, three profiles, unified harness `tests/conftest.py`) | built; index pending |
| D4 | test suite with documented results | `tests/` (unit, contract, conformance, acceptance, live), `scripts/run_acceptance.py` → `reports/<stamp>/summary.md` | built; first results pending a dependency-capable run |
| D5 | retrieval evaluation set and protocol | `eval/ncit-retrieval-eval-v1.jsonl`, `scripts/evaluate_retrieval.py`, `docs/retrieval-evaluation-protocol.md` | built; SME validation pending |
| D6 | performance benchmark report | `scripts/benchmark.py` → `reports/<stamp>/benchmark.md` | built; first report pending |
| D7 | upstream EVS API requirements package | `docs/upstream-requirements-package.md` | built; live re-verification pending |
| D8 | deployment guide | `docs/deployment.md`, `docs/runbook.md`, `deploy/` | built |
| D9 | user and developer documentation | `docs/user-guide.md`, `docs/tool-reference.md` (generated), `spec/interface-baseline/`, README | built; tool reference pending generation |

## Test taxonomy (proposal 12) → files

| id | file(s) |
|---|---|
| T-UNIT | `tests/unit/` |
| T-CONTRACT, T-REL, T-FAIL, T-BUDGET, T-BATCH | `tests/contract/test_evs_service.py` |
| T-TRAV, T-POL, T-PROV | `tests/contract/test_evs_traversal_sets.py` |
| T-LIC | `tests/contract/test_evs_service.py` (license gate tests) |
| T-CONF, T-PROF | `tests/conformance/test_mcp.py` |
| T-SEC, T-RED | `tests/contract/test_platform.py` |
| T-IFACE | `tests/contract/test_interface_baseline.py` |
| T-INT | `tests/contract/test_map_service.py` (GDC race end to end), `test_cadsr_service.py` |
| T-ACC | `tests/acceptance/` (fixture and live modes) |
| T-LIVE | `tests/live/` |
| T-PERF | `scripts/benchmark.py` |
| T-RETR, T-EMB, T-ACT | pending Phase 3 (scorer ready) |
