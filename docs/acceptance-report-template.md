# Acceptance report — <date>

Template for the unified-profile acceptance record (SOW: "lead final unified-profile
integration and acceptance testing"). Fill from `scripts/run_acceptance.py --live` output,
`scripts/evaluate_retrieval.py`, and `evs-cadsr-mcp baseline check`.

## Identification

| item | value |
|---|---|
| repository commit / tag | |
| server version / interface baseline | `__version__` / `INTERFACE_VERSION` |
| profile(s) under test | evs-only, unified |
| active NCIt release (`/readyz`) | |
| fixtures | recorded on <date> (`conformance-mock.json`: n live / n hand-authored) |
| environment | local / dev / staging; auth mode; shared cache |

## Results by tier (from `reports/<stamp>/summary.md`)

| tier | tests | failures | errors | skipped | notes |
|---|---|---|---|---|---|
| unit | | | | | |
| contract | | | | | includes T-REL, T-FAIL, T-BUDGET, T-BATCH, T-TRAV, T-POL, T-PROV, T-LIC, T-SEC, T-RED, T-IFACE |
| conformance (T-CONF, T-PROF) | | | | | |
| acceptance — fixture (T-ACC) | | | | | |
| acceptance — live (T-ACC) | | | | | |
| live smoke (T-LIVE) | | | | | |

## SOW capability sign-off

| SOW | demonstrated by (test id / scenario) | result | NCI reviewer |
|---|---|---|---|
| T1 lookup | `test_t1_lookup_by_code_name_synonym` | | |
| T2 full-text / typeahead | `test_t2_full_text_and_typeahead` | | |
| T2 vector / hybrid | pending index | n/a | |
| T3 traversal | `test_t3_bounded_traversal_with_truncation_and_hop_provenance` | | |
| T4 content | `test_t4_synonyms_definitions_properties_associations` | | |
| T5 concept sets | `test_t5_concept_sets_by_criteria` | | |
| T6 subsets | `test_t6_subset_membership` | | |
| T7 sub-trees | `test_t7_targeted_subtree` | | |
| T8 cross-maps / license | `test_t8_cross_maps_and_license_gate` | | |
| S11 release identity | `test_s11_release_pinning_fails_closed` | | |
| unified UC-1 / UC-3 | `test_uc1_cde_to_ncit_and_enum_alignment` | | |
| unified UC-4 / UC-9 | `test_uc4_concept_to_cdes_and_uc9_icdo` | | |

## Benchmark (from `benchmark.md`)

Paste the table; note cold vs. warm gap and any SLO misses (proposal 10.6).

## Retrieval evaluation (from `eval/results/`)

| retriever | release | recall@5 | recall@10 | mrr@10 | ndcg@10 | gate |
|---|---|---|---|---|---|---|
| upstream_contains (pre-index baseline) | | | | | | n/a |
| hybrid (when available) | | | | | | |

## Interface baseline

`evs-cadsr-mcp baseline check` output: <paste>. Open change requests: <list>.

## Known limitations and upstream issues at acceptance

Reference `docs/user-guide.md` "Known limitations" and `docs/upstream-requirements-package.md`;
list anything new found during acceptance.

## Decision

| role | name | date | decision |
|---|---|---|---|
| NCI EVS lead | | | accept / accept with conditions / reject |
| NCI caDSR lead (unified) | | | |
| contractor | | | |
