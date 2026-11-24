# NCIt retrieval evaluation set and scoring protocol (SOW D5)

## Purpose

The SOW states that no approved query set exists at award. This document and
`eval/ncit-retrieval-eval-v1.jsonl` are the contractor's initial evaluation set and scoring
protocol, delivered for NCI SME validation **before** formal acceptance testing and rerun for
every production embedding rebuild (proposal 6.7). Until an index exists, the same set is
scored against the live EVS search tools to establish the pre-index baseline that the index
and each retrieval-quality enhancement must beat.

## The set

`eval/ncit-retrieval-eval-v1.jsonl`, one JSON object per line:

| field | meaning |
|---|---|
| `id` | stable identifier, `<category>-<nnn>` |
| `category` | `concept_name`, `synonym_abbreviation`, `definition_style`, `lay_language`, `icdo_morphology`, `icdo_topography`, `cde_derived`, `anatomy`, `gene`, `drug`, `finding`, `negative` |
| `query` | the text an agent would send |
| `expected` | acceptable NCIt codes (empty for negatives) |
| `primary` | the single best answer (gets double gain in nDCG) |
| `confidence` | author confidence in the expected codes: `high`, `medium`, `low` |
| `validation` | `pending SME` until an NCI SME approves or corrects the row; then `approved <date> <initials>` |
| `note` | provenance of the expectation or what the SME should decide |

v1 has 67 rows (63 positives, 4 negatives) seeded from proposal Appendix A: concept names,
abbreviations/synonyms, definition-style and lay-language queries, ICD-O-3 morphology and
topography strings, CDE-derived queries from GDC property descriptions, and anatomy, gene,
drug and finding names by semantic type. **Expected codes were written from the author's
knowledge of NCIt and are unverified**; rows with `confidence: low` name the decision the SME
must make. The target for the frozen set is several hundred rows with at least 25 per
category, extended with ICD-O strings drawn from the EVS ICD-O crosswalk and CDE-derived
queries drawn from GDC `_terms.yaml` once fixtures are recorded.

### Versioning

The set is immutable once approved: corrections and additions produce `v2`, and results are
always reported against a named version. Rows are never deleted; a row an SME rejects gets
`validation: rejected <reason>` and is excluded by the scorer only when `--approved-only` is
added (planned once a first approval exists).

## Scoring

`scripts/evaluate_retrieval.py` scores a retriever over the set:

| measure | definition |
|---|---|
| Recall@5, Recall@10 | fraction of positive queries with any expected code in the top 5 / 10 |
| MRR@10 | mean reciprocal rank of the first expected code within the top 10 |
| nDCG@10 | graded: primary code gain 2, other expected codes gain 1 |
| negative hit rate | fraction of negative queries that return anything (informational; the index should return low-score or empty results) |
| latency p50 / p95 | wall-clock per query, per mode |

Results are reported overall and per category, as JSON (`eval/results/<name>.json`) and
Markdown, with the NCIt release and retriever named in the header.

### Retrievers and modes

Before the index: `upstream_contains`, `upstream_match`, `lookup_chain` (the UC-11 chain).
After Phase 3: `ncit_index.query:bm25`, `:vector`, `:hybrid`, `:hybrid_rerank`, and each
enhancer line (synonym/abbreviation expansion, chunking, client-side multi-query) scored
separately so the before/after table required by SOW-S10 can be produced.

### Acceptance thresholds (initial; NCI confirms at the architecture review)

| gate | threshold |
|---|---|
| hybrid Recall@5 | ≥ 0.90 |
| hybrid MRR@10 | ≥ 0.85 |
| every category Recall@10 | ≥ 0.80 |
| reranking | must not reduce MRR@10 |
| regression flag | any metric more than 2 points below the previous run of the same retriever |

`--gate` fails the run on threshold misses; `--compare previous.json` fails on regressions.

## Procedure per production embedding rebuild

1. Build the candidate index for the approved monthly release; record provider, model id and
   revision, dimension, normalisation and chunking in the manifest.
2. `python scripts/evaluate_retrieval.py --retriever ncit_index.query:hybrid --compare eval/results/<previous>.json --gate --out eval/results/<release>-hybrid.json`
   and the same for `bm25`, `vector` and `hybrid_rerank`.
3. Attach the four Markdown reports and the manifest to the activation request; activate only
   when the gates pass (or NCI accepts a documented exception).
4. Keep the previous build for rollback; the previous results file is the next comparison base.

## SME validation package

For each row the SME sees query, category, expected code(s) with NCIt preferred names and
definitions (produced with `evs_get_concepts`), the author's note, and three choices:
approve, correct (new codes), reject. The package is generated as a spreadsheet from the
JSONL once fixtures are recorded; approvals are written back into the `validation` field.
