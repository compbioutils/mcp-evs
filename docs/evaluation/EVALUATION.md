# Evaluation of the `evs-cadsr-mcp` server

**Date:** 23 November 2026 (runs between 01:23 and 01:30 UTC on 24 November)
**Subject:** `evs-cadsr-mcp` 0.1.0, commit `3cda201` (server source unchanged by this evaluation)
**Upstreams:** live NCI EVS REST API (NCIt 26.10d); caDSR **stage** for the caDSR live tests

This document is at `docs/evaluation/EVALUATION.md`

This report brings together every check run on the server, so it can be submitted as
evidence of completion. It follows the [acceptance report template](../acceptance-report-template.md).
All raw results are in this directory (see [Evidence](#evidence)).



## Summary

| Check | Result |
| --- | --- |
| Lint (`ruff check .`) | Pass |
| Offline test suite: unit, contract, conformance, acceptance (fixtures) | **190 tests, 0 failures**, 2 skipped (see [Results by tier](#results-by-tier)) |
| Live tests: smoke and acceptance against EVS and caDSR stage | **17 of 17 passed** |
| EVS use cases: 9 scenarios, 54 tool calls against live EVS | **52 passed, 2 known issues, 0 failures**; all 9 scenarios met their goal |
| Live latency over the 54 use-case calls | p50 0.18 s, p95 0.32 s, max 0.62 s (SLOs: live single concept < 3 s, bounded traversal < 10 s) |
| Retrieval baseline (67 queries, pre-index `upstream_contains`) | recall@5 0.67, MRR@10 0.63 |
| GitHub Actions on `main` (CI, Secret scan, Dependency audit) | All three pass |
| Secret scan of the full git history (gitleaks) | No leaks |

The server delivers the EVS capabilities it was built for (T1–T8 and S11; see the sign-off
table), with provenance on every answer, release pinning that fails closed, bounded traversal
that reports truncation, and the MedDRA license gate. The evaluation found **six issues**:
four new and two already known. None stops a scenario from reaching its goal. They are
listed under [Findings](#findings) with the evidence and a suggested fix for each.



## Identification

| Item | Value |
| --- | --- |
| Repository commit | `3cda201` (`main`, pushed; evaluation files committed after it) |
| Server version / interface | 0.1.0; interface baseline **not frozen** (finding F4) |
| Tools | 48 in the `unified` profile: 21 `evs_*`, 16 `cadsr_*`, 11 `map_*` |
| Profiles under test | `unified` (use cases, live acceptance); `evs-only` and `unified` (conformance) |
| Active NCIt release | 26.10d (also served: 26.09d, 26.08e monthly; 26.11c weekly) |
| Other releases used | CTCAE 5.0 and 6.0; previous monthly NCIt 26.09d |
| Transport | stdio (use cases); in-process FastMCP client (test suite) |
| Environment | macOS, Python 3.12.13, uv lock file; no license key (to exercise the gate); caDSR stage over NIH VPN |
| Fixtures | Hand-authored from documented EVS and caDSR payload shapes (see README "Tests") |



## Method

| Evidence | How it was produced | What it shows |
| --- | --- | --- |
| Offline tiers | `scripts/run_acceptance.py --out docs/evaluation/test-results` | Behaviour against fake upstreams: release pinning, budgets, traversal, batching, licensing, security middleware, MCP conformance, profiles |
| Live tiers | `scripts/run_live_tests.py --junitxml ...` (caDSR stage only) | The same tools against real EVS and caDSR |
| EVS use cases | `scripts/run_use_cases.py`, reading [the use cases](../evs%20mcp%20use%20cases.md) | Nine end-user workflows, each step checked for specific codes, relationships, paging, truncation, warnings and provenance release |
| Benchmark | `scripts/benchmark.py` (fixtures), run by `run_acceptance.py` | Cache behaviour and outbound-call counts; live latency comes from the use-case run |
| Retrieval | `scripts/evaluate_retrieval.py --retriever upstream_contains --mode live` | Pre-index search quality (SOW D5 baseline) |
| Security | GitHub Actions; `gitleaks git .` | Secret scanning, dependency audit, lock-file checks |

The use-case runner starts an isolated copy of the server over stdio, takes no `ECM_*`
settings from the shell and doesn't read `.env`. It discovers releases from EVS at run time,
validates every call's arguments and answer against the tool's published JSON schemas, and
checks content, not just success. Its own logic has offline tests in
`tests/unit/test_use_cases.py`. These include a test that every documented step is a valid call
to this server, so the document can't drift from the tool schemas unnoticed.



## Results by tier

| Tier | Tests | Failures | Errors | Skipped | Notes |
| --- | ---: | ---: | ---: | ---: | --- |
| unit | 37 | 0 | 0 | 0 | includes 16 tests of the use-case runner |
| contract | 127 | 0 | 0 | 2 | skipped: interface baseline not exported (F4); one strict `xfail` for an open decision (F6) |
| conformance (T-CONF, T-PROF) | 14 | 0 | 0 | 0 | MCP protocol over a client; profile tool sets |
| acceptance, fixtures (T-ACC) | 12 | 0 | 0 | 0 | |
| acceptance, live (T-ACC) | 12 | 0 | 0 | 0 | EVS and caDSR stage |
| live smoke (T-LIVE) | 5 | 0 | 0 | 0 | includes the ICD-O-3.1 file download |
| **Total** | **207** | **0** | **0** | **2** | |

The live tiers ran with a writable ICD-O cache (`ECM_ICDO_CACHE_DIR`). A first live run used
the default cache, which the evaluation sandbox doesn't allow writing to. One test then
failed with `internal_error` (finding F5), and passed once the cache was writable.



## SOW capability sign-off

| SOW | Demonstrated by | Result |
| --- | --- | --- |
| T1 lookup | `test_t1_lookup_by_code_name_synonym`; use cases EVS-01, 04, 06 | Pass |
| T2 full text / typeahead | `test_t2_full_text_and_typeahead`; EVS-02, 07, 08, 09 | Pass |
| T2 vector / hybrid | Pending the NCIt index | n/a |
| T3 traversal | `test_t3_bounded_traversal_with_truncation_and_hop_provenance`; EVS-01 `bounded-walk` | Pass |
| T4 content | `test_t4_synonyms_definitions_properties_associations`; EVS-04, 06, 07 | Pass |
| T5 concept sets | `test_t5_concept_sets_by_criteria`; EVS-03 (ICD-O property), 04 (reverse role), 07 (`Has_Target`) | Pass |
| T6 subsets | `test_t6_subset_membership`; EVS-02 | Pass |
| T7 sub-trees | `test_t7_targeted_subtree`; EVS-09 `subtree` | Pass |
| T8 cross-maps / license | `test_t8_cross_maps_and_license_gate`; EVS-03 | Pass, with finding F1 (filter by target) |
| S11 release identity | `test_s11_release_pinning_fails_closed`; EVS-05 `earlier-release`, `withdrawn-release` | Pass |
| Unified UC-1 / UC-3 | `test_uc1_cde_to_ncit_and_enum_alignment` | Pass |
| Unified UC-4 / UC-9 | `test_uc4_concept_to_cdes_and_uc9_icdo`; EVS-03 `icdo-mapping-file` | Pass (with a writable cache; F5) |
| Release impact | EVS-05 `impact` | Works; finding F2 |



## EVS use cases

Nine scenarios from [the use cases](../evs%20mcp%20use%20cases.md). Full results are in
[use-case-results.md](use-case-results.md) (per step), [use-case-results.json](use-case-results.json)
(every argument and answer) and [use-case-transcript.txt](use-case-transcript.txt).

| Scenario | Result | What the server demonstrated |
| --- | --- | --- |
| EVS-01 Cohort expansion | PASS (4/4) | "Ewing sarcoma" resolves to C4817; all 32 descendants in one complete page; a depth-bounded walk reports `truncation.bound: maxDepth`; exclusion roles are marked `polarity: negative` |
| EVS-02 CDISC Sex value set | PASS (4/4) | All 4 members of C66731; CDISC synonyms on every member; an exact, subset- and source-filtered search for `F` returns only *Female* (C16576) |
| EVS-03 Cross-terminology coding | PASS* (6/7) | ICD-O-3 `8140/3` gives C2852 by property search and by EVS's mapping files; melanoma maps to ICD-O-3 and GDC with MedDRA withheld and a warning; ICD-10-CM `C43.9` reached through C3510 and the `NCIt_Maps_To_ICD10CM` mapset. Known issue F1 |
| EVS-04 Grounded Q&A | PASS (6/6) | NSCLC resolves to C2926 with NCIt definition and synonym; both parents and the root path; melanoma's finding roles incl. an exclusion; reverse role search pages (11,217 hits) |
| EVS-05 Release remediation | PASS* (6/7) | Batch keeps active, retired and unknown codes apart; history shows C28327 merged into C4029; 26.09d content is served and cited; unknown code gives `not_found` and a withdrawn release gives `release_not_available`. Known issue F2 |
| EVS-06 Drug normalization | PASS (7/7) | Tagrisso resolves to the salt (C170266), AZD9291 and osimertinib to the ingredient (C116377); `Has_Free_Acid_Or_Base_Form` links them; the UNII round-trips through property search |
| EVS-07 Biomarker relationships | PASS (6/6) | EGFR L858R (C98515) links to the EGFR gene and gene-mutation concept; 17 agents target it (incl. osimertinib, lazertinib) on one page; diseases with the mutation; disease path |
| EVS-08 CTCAE | PASS (9/9) | CTCAE 5.0 and 6.0 read at their own releases; grade 1–3 children and the grade 3 definition; exact lookup resolves "vomiting" and refuses to guess "throwing up" |
| EVS-09 Term dictionary | PASS (4/4) | Two-level Lung Carcinoma branch (101 codes) complete; one batch call returns synonyms for the root and every code; depth-capped sub-tree flags matches and reports truncation |

`PASS*`: every step passed except a documented known issue. The use cases exercised 20 tools:
18 of the 21 `evs_*` tools, plus `map_map_icdo_to_ncit` and `map_assess_release_impact`.



## Performance

**Live (use-case run, stdio, NCIt 26.10d):** 54 calls; 58 upstream requests; p50 0.18 s,
p95 0.32 s, max 0.62 s (`EVS-04.reverse-finding`, an 11,217-hit search); 9.6 s in total.
Every call met the live SLOs (single concept < 3 s, bounded traversal < 10 s).

**Retrieval latency (live, 67 queries):** p50 68 ms, p95 130 ms.

**Benchmark (fixtures, 3 repeats):** [benchmark.md](test-results/benchmark.md). Warm-cache calls
make no outbound request; cold calls make the expected number (1 per concept, 3 for a depth-2
traversal). Latencies against fixtures are 0–8 ms and measure the server's own overhead only.



## Retrieval evaluation

Pre-index baseline (`upstream_contains`, live, NCIt 26.10d, 67 queries, 0 errors):
[retrieval-upstream-contains.md](retrieval-upstream-contains.md).

| Retriever | Release | recall@5 | recall@10 | MRR@10 | nDCG@10 | Gate |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| upstream_contains (pre-index baseline) | 26.10d | 0.6667 | 0.6667 | 0.6341 | 0.6412 | n/a |
| hybrid | | | | | | pending the NCIt index |

Concept names, drugs and findings score 1.0. Definition-style and CDE-derived phrasing score
0–0.17: that's what the planned semantic index is for. ICD-O codes score 0 through free-text
search by design. The server answers them with `evs_find_concepts` (ICD-O property) and
`map_map_icdo_to_ncit`, which both pass in EVS-03.



## Security and supply chain

- **CI on `main`** (`3cda201`): CI (lint, offline tests on Python 3.11 and 3.12, lock-file
  checks), Secret scan (gitleaks, full history) and Dependency audit (pip-audit) all passed.
- **Secrets:** `gitleaks git .` over the full history finds no leaks. Credentials stay in a
  git-ignored `.env`. The evidence files were checked for the configured credential values (none
  found), and machine hostnames and home-directory paths were redacted from the test logs.
- **License gate:** without `ECM_LICENSE_KEY`, MedDRA map targets are withheld and a warning
  names them (EVS-03 `melanoma-maps`, `test_t8_*`).
- **Fail-closed releases:** a withdrawn release is refused with `release_not_available`
  instead of falling back to current content (EVS-05, `test_s11_*`).
- **caDSR stage only:** the live tests refuse to run unless caDSR points at stage; the use-case
  runner forces stage and doesn't call caDSR.
- **Startup checks** (HTTP off loopback needs auth; JWT needs issuer and audience;
  Databricks mode needs the app's service principal) are covered by `tests/contract/test_platform.py`.



## Findings

| # | Severity | Finding | Evidence | Suggested fix |
| --- | --- | --- | --- | --- |
| F1 | Medium | `evs_get_concept_maps` with `targetTerminology: "ICD10CM"` returns no maps for C3510, though it has ICD-10-CM maps. EVS labels concept maps `"ICD10CM 2017"` and the filter compares exactly. | EVS-03 `cutaneous-icd10cm-filter` (KNOWN_ISSUE); unfiltered call returns `C43.9` | Compare the terminology name without its version (`"ICD10CM 2017"` → `ICD10CM`), case-insensitively, and add a contract test |
| F2 | Medium | `map_assess_release_impact` reports codes that were already retired in `fromRelease` as changes between the two releases (C28327, merged in 2021, appears as `merged` for 26.09d→26.10d). The tool is documented as showing "what changed between two NCIt releases". | EVS-05 `impact` (KNOWN_ISSUE) | Report a change only when the status differs between the releases, or mark it as already retired |
| F3 | Low | `evs_get_terminology_metadata` with `kinds: ["conceptStatuses"]` fails output validation (`'Concept_Pending_Approval' is not of type 'object'`). Already listed as a known issue in `docs/tools/README.md`; still present. | Live call during this evaluation | Model concept statuses as strings |
| F4 | Medium | `evs-cadsr-mcp baseline check`/`export` crash: FastMCP 3.4 has no `FastMCP.get_tools`. The interface baseline (S16) can't be frozen, so its end-to-end contract test is skipped. | `AttributeError: 'FastMCP' object has no attribute 'get_tools'` in `server/baseline.py` | Use the FastMCP 3 tool-listing API, export the baseline, and un-skip the test |
| F5 | Low | `map_map_icdo_to_ncit` returns `internal_error` when the ICD-O cache directory isn't writable, instead of `capability_unavailable` with a hint (as it does when the files aren't downloaded yet). | First live run; `PermissionError` on the cache lock file | Catch `OSError` around the cache and raise `capability_unavailable` naming `ECM_ICDO_CACHE_DIR` |
| F6 | Open decision | What to return for an absent code with replacement history (currently 0 CDEs plus a warning). Tracked by a strict `xfail` contract test. | `test_find_data_elements_for_concept_with_descendants` | NCI decision |

Observations that aren't defects: the brand name *Tagrisso* is a synonym of the salt
(*Osimertinib Mesylate*), not the ingredient; *Melanoma* (C3224) has no direct ICD-10-CM map
(the codes are on site-specific concepts such as C3510); and concept maps cite ICD-10-CM 2017
while the `NCIt_Maps_To_ICD10CM` mapset cites 2026.



## Limitations of this evaluation

- Live EVS content changes monthly. Expectations check stable codes and relationships, not
  exact counts. A rerun after the next release can differ in counts without being a regression.
- The fixture benchmark measures server overhead only. Live latency comes from 54 use-case
  calls and 67 retrieval queries, not a load test.
- Semantic and hybrid search, and the release-aware NCIt index, are not built yet (T2 vector,
  S9, S10), so they weren't evaluated.
- caDSR was evaluated through the live acceptance tests on stage only; the use cases cover EVS.
- The Databricks App deployment wasn't part of this evaluation. Commit `e8d6e12` restored
  Databricks support after a startup crash. A successful deploy should be confirmed with the
  app's `/healthz`.
- The test fixtures are hand-authored from documented payload shapes, not recorded responses.
  The live tiers and use cases cover that gap for the paths they exercise.



## Reproduce

```bash
uv sync --frozen --extra dev
uv run --no-sync ruff check .
uv run --no-sync python scripts/run_acceptance.py --out docs/evaluation/test-results
uv run --no-sync python scripts/run_live_tests.py --junitxml docs/evaluation/test-results/junit-live.xml   # needs .env with caDSR stage, NIH VPN
uv run --no-sync python scripts/run_use_cases.py > docs/evaluation/use-case-transcript.txt
uv run --no-sync python scripts/evaluate_retrieval.py --retriever upstream_contains --mode live --out docs/evaluation/retrieval-upstream-contains.json
```



## Evidence

| File | Contents |
| --- | --- |
| [use-case-results.md](use-case-results.md) | Per-scenario and per-step results of the use-case run |
| [use-case-results.json](use-case-results.json) | Every call's arguments, full answer, checks, timing and outbound-request count |
| [use-case-transcript.txt](use-case-transcript.txt) | Console transcript of the use-case run |
| [test-results/summary.md](test-results/summary.md) | Offline tiers summary |
| `test-results/junit-*.xml`, `test-results/pytest-*.log` | JUnit results and logs for unit, contract, conformance, acceptance and live tiers |
| [test-results/benchmark.md](test-results/benchmark.md) | Fixture benchmark |
| [retrieval-upstream-contains.md](retrieval-upstream-contains.md) and `.json` | Retrieval baseline with per-category scores and misses |

