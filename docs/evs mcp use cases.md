# EVS MCP use cases

Nine EVS scenarios, written as executable test cases for **this server** (`evs-cadsr-mcp`,
`evs_*` and `map_*` tools). [`scripts/run_use_cases.py`](../scripts/run_use_cases.py) reads the
JSON block under each scenario, calls the tools over MCP against live EVS, checks the
expectations and writes the results to [`docs/evaluation/`](evaluation/). The
[evaluation report](evaluation/EVALUATION.md) summarises the latest run.

Each scenario keeps the goal of the original use case. Codes in the steps are seeds chosen
for the scenario; lookups and searches that should find them are steps of their own, and
their expectations check that the search really returns the seed.

| Workflow | How this server covers it |
| --- | --- |
| EVS-01 Cohort expansion | `evs_get_descendants` returns the complete branch; exclusion roles are kept apart by `polarity` |
| EVS-02 Standards value sets | Subset members, subset description, member details, and a subset-filtered search for a submission value |
| EVS-03 Cross-terminology coding | ICD-O reverse lookup (property search and EVS mapping files), concept maps, mapsets and mapset entries |
| EVS-04 Grounded Q&A | Lookup, definitions, parents, paths to root, roles, and reverse role search |
| EVS-05 Release remediation | Release list, batch status, history with replacements, an earlier release, release impact, fail-closed errors |
| EVS-06 Drug normalization | Brand, code-name and generic lookups, salt-to-ingredient association, UNII property search, class path |
| EVS-07 Biomarker relationships | Variant search, variant-to-gene roles, reverse `Has_Target` agent search, disease links and path |
| EVS-08 CTCAE | Version-specific (5.0 and 6.0) terms, grade children and grade definitions; lay-term lookup |
| EVS-09 Term dictionary | Bounded branch (`maxLevel`), batch synonyms for the root and every returned code, bounded sub-tree |

## Step format

Each JSON block is a list of steps. A step is one MCP call:

| Field | Meaning |
| --- | --- |
| `id` | Step name, unique within the scenario. Reported as `EVS-01.lookup`. |
| `tool`, `arguments` | The MCP call. `$ncit`, `$previous`, `$ctcae5` and `$ctcae6` are releases discovered at run time with `evs_list_releases` (`$previous` is the newest monthly release before the active one). |
| `codesFrom` | Adds `codes` from an earlier step's result: `{"step", "at"?, "root"?}`. `at` names the list inside a result object; `root` is put first. |
| `expect` | Checks on the answer (below). A step with none passes when the call succeeds and matches the tool's output schema. |
| `expectedError` | The call must fail with this error code (negative test). |
| `knownIssue` | The expectations describe correct behaviour this server doesn't have yet. The step reports `KNOWN_ISSUE` while it fails and `UNEXPECTED_PASS` once fixed, so the marker can be removed, like `xfail(strict=True)` in the test suite. |
| `note` | Explanation shown in the results. |

`expect` checks:

| Check | Passes when |
| --- | --- |
| `has: {field: [values]}` | Each value appears as `field` on some object anywhere in `result`. |
| `lacks: {field: [values]}` | None of the values appears as `field` anywhere in `result`. |
| `count: {at?, min?, max?}` | The list (`result`, or `result[at]`) has that many items. |
| `complete: true` | No `page.nextCursor` and no `truncation.occurred`. |
| `paged: true` | `page.nextCursor` is set (more results exist). |
| `truncated: "<bound>"` | `truncation.occurred` is true and `truncation.bound` is that bound. |
| `warning: "<text>"` | A warning contains the text. |
| `release: "<release>"` | Every provenance record that names a release names this one. |

## EVS-01 Cohort and eligibility expansion

**Goal / who:** A cohort analyst starts with "Ewing sarcoma" and needs codes for the root
and all its subtypes, keeping exclusion assertions apart from the cohort.

```json
[
  {"id": "lookup", "tool": "evs_lookup_concept", "arguments": {"identifier": "Ewing sarcoma", "release": "$ncit"},
   "expect": {"has": {"code": ["C4817"]}, "release": "$ncit"}},
  {"id": "descendants", "tool": "evs_get_descendants", "arguments": {"code": "C4817", "limit": 500, "release": "$ncit"},
   "expect": {"has": {"code": ["C4835", "C7135", "C189002"]}, "count": {"min": 20}, "complete": true}},
  {"id": "bounded-walk", "tool": "evs_traverse", "arguments": {"start": ["C4817"], "selectors": [{"kind": "children"}], "budget": {"maxDepth": 2, "maxNodes": 100}, "release": "$ncit"},
   "expect": {"truncated": "maxDepth"},
   "note": "A depth-bounded walk must say it stopped early rather than look complete."},
  {"id": "exclusions", "tool": "evs_get_relationships", "arguments": {"code": "C4817", "kinds": ["roles"], "release": "$ncit"},
   "expect": {"has": {"type": ["Disease_Excludes_Finding"], "polarity": ["negative", "positive"]}}}
]
```

**What's checked:** the name resolves to C4817; the flat descendant list is complete (no
cursor, no truncation); a depth-bounded traversal reports `truncation.bound: maxDepth`; and
exclusion roles carry `polarity: negative`, so they can't be mistaken for cohort members.

**Limits:** Cohort membership is a hierarchy question; whether to include subtypes such as
*Childhood* or *Recurrent* Ewing sarcoma is the analyst's decision.

## EVS-02 Standards value sets: CDISC Sex

**Goal / who:** A standards analyst needs the members of C66731 (CDISC SDTM Sex of
Individual) and checks that a study value such as `F` is a published CDISC submission value.

```json
[
  {"id": "members", "tool": "evs_get_subset_members", "arguments": {"code": "C66731", "limit": 50, "release": "$ncit"},
   "expect": {"has": {"code": ["C16576", "C20197", "C17998", "C45908"]}, "complete": true}},
  {"id": "describe", "tool": "evs_list_subsets", "arguments": {"code": "C66731", "release": "$ncit"},
   "expect": {"has": {"code": ["C66731"]}}},
  {"id": "member-details", "tool": "evs_get_concepts", "arguments": {"include": ["synonyms"], "release": "$ncit"},
   "codesFrom": {"step": "members"},
   "expect": {"count": {"at": "concepts", "min": 4}, "has": {"source": ["CDISC"]}}},
  {"id": "submission-value", "tool": "evs_search_concepts", "arguments": {"term": "F", "type": "match", "subset": "C66731", "synonymSource": "CDISC", "limit": 10, "release": "$ncit"},
   "expect": {"has": {"code": ["C16576"]}, "count": {"min": 1, "max": 1}}}
]
```

**What's checked:** all four members come back on one page; member details carry CDISC
synonyms; and an exact (`match`) search for `F`, limited to the subset and to CDISC synonyms,
returns only *Female* (C16576).

**Limits:** Use `type: match`. A `contains` search for `F` also returns *Intersex*, because
its CDISC synonym contains the letter.

## EVS-03 Cross-terminology coding

**Goal / who:** A registrar converts ICD-O-3 `8140/3` to NCIt and finds what melanoma maps
to in other code systems, including ICD-10-CM.

```json
[
  {"id": "icdo-property", "tool": "evs_find_concepts", "arguments": {"criteria": [{"kind": "property", "name": "ICD-O-3_Code", "value": "8140/3"}], "release": "$ncit"},
   "expect": {"has": {"code": ["C2852"]}, "count": {"at": "concepts", "max": 1}, "complete": true}},
  {"id": "icdo-mapping-file", "tool": "map_map_icdo_to_ncit", "arguments": {"icdoCode": "8140/3", "release": "$ncit"},
   "expect": {"has": {"code": ["C2852"], "icdoTerm": ["Adenocarcinoma, NOS"]}}},
  {"id": "melanoma-maps", "tool": "evs_get_concept_maps", "arguments": {"code": "C3224", "release": "$ncit"},
   "expect": {"has": {"targetTerminology": ["ICDO3", "GDC"]}, "warning": "MedDRA"},
   "note": "MedDRA targets are withheld without ECM_LICENSE_KEY (license gate)."},
  {"id": "cutaneous-maps", "tool": "evs_get_concept_maps", "arguments": {"code": "C3510", "release": "$ncit"},
   "expect": {"has": {"targetCode": ["C43.9"]}}},
  {"id": "cutaneous-icd10cm-filter", "tool": "evs_get_concept_maps", "arguments": {"code": "C3510", "targetTerminology": "ICD10CM", "release": "$ncit"},
   "expect": {"has": {"targetCode": ["C43.9"]}},
   "knownIssue": "targetTerminology is compared exactly, but EVS labels these concept maps 'ICD10CM 2017', so the documented filter value ICD10CM returns no maps."},
  {"id": "mapsets", "tool": "evs_list_mapsets", "arguments": {},
   "expect": {"has": {"code": ["NCIt_Maps_To_ICD10CM", "NCIt_Maps_To_GDC"]}}},
  {"id": "icd10cm-entries", "tool": "evs_get_mapset_entries", "arguments": {"mapset": "NCIt_Maps_To_ICD10CM", "term": "melanoma", "limit": 100},
   "expect": {"has": {"targetCode": ["C43.9"], "sourceCode": ["C3510"]}, "complete": true}}
]
```

**What's checked:** both reverse routes (the `ICD-O-3_Code` property and EVS's ICD-O-3.1
mapping files) give C2852 *Adenocarcinoma*; melanoma's maps include ICD-O-3 and GDC, with
MedDRA withheld and a warning; and ICD-10-CM codes are reachable from *Cutaneous Melanoma*
(C3510), both on the concept and in the `NCIt_Maps_To_ICD10CM` mapset.

**Limits:** *Melanoma* (C3224) itself has no ICD-10-CM map; the ICD-10-CM codes are on the
site-specific concept C3510. Concept maps cite ICD-10-CM 2017 while the mapset cites 2026.

## EVS-04 Grounded terminology Q&A

**Goal / who:** A researcher asks what NSCLC means, what it is a kind of, and which findings
define melanoma.

```json
[
  {"id": "lookup", "tool": "evs_lookup_concept", "arguments": {"identifier": "NSCLC", "release": "$ncit"},
   "expect": {"has": {"code": ["C2926"]}}},
  {"id": "definition", "tool": "evs_get_concept", "arguments": {"code": "C2926", "include": ["definitions", "synonyms"], "release": "$ncit"},
   "expect": {"has": {"source": ["NCI"], "name": ["NSCLC"]}, "release": "$ncit"}},
  {"id": "parents", "tool": "evs_get_hierarchy_neighbors", "arguments": {"direction": "parents", "code": "C2926", "release": "$ncit"},
   "expect": {"has": {"code": ["C4878", "C65151"]}}},
  {"id": "paths", "tool": "evs_get_paths", "arguments": {"code": "C2926", "release": "$ncit"},
   "expect": {"has": {"code": ["C4878"]}}},
  {"id": "findings", "tool": "evs_get_relationships", "arguments": {"code": "C3224", "kinds": ["roles"], "release": "$ncit"},
   "expect": {"has": {"type": ["Disease_Has_Finding", "Disease_Excludes_Finding"], "code": ["C36115"], "polarity": ["negative"]}}},
  {"id": "reverse-finding", "tool": "evs_find_concepts", "arguments": {"criteria": [{"kind": "role", "name": "Disease_Has_Finding", "targetCode": "C36115"}], "limit": 5, "release": "$ncit"},
   "expect": {"count": {"at": "concepts", "min": 5}, "paged": true}}
]
```

**What's checked:** the abbreviation resolves; the definition and the `NSCLC` synonym come
from NCIt; both parents (*Lung Carcinoma*, *Non-Small Cell Carcinoma*) and the path to the root
are returned; melanoma's roles include *Malignant Cellular Infiltrate* (C36115) and an
exclusion marked `negative`; and a reverse role search pages instead of returning thousands
of rows at once.

**Limits:** Ontology relationships are not a diagnostic checklist. Cite the code and the
release in `provenance`.

## EVS-05 Release-change remediation

**Goal / who:** A data manager checks stored codes against the current release, finds
replacements for retired ones, and compares with the previous monthly release.

```json
[
  {"id": "releases", "tool": "evs_list_releases", "arguments": {},
   "expect": {"has": {"version": ["$ncit", "$previous"]}}},
  {"id": "batch", "tool": "evs_get_concepts", "arguments": {"codes": ["C3224", "C2926", "C28327", "C7681", "C9324", "C99999999"], "include": ["minimal"], "release": "$ncit"},
   "expect": {"has": {"code": ["C3224", "C28327"], "conceptStatus": ["Retired_Concept"]}, "count": {"at": "missing", "min": 1, "max": 1}}},
  {"id": "history", "tool": "evs_get_concept_history", "arguments": {"code": "C28327", "release": "$ncit"},
   "expect": {"has": {"action": ["merge", "retire"], "replacementCode": ["C4029"]}}},
  {"id": "earlier-release", "tool": "evs_get_concepts", "arguments": {"codes": ["C3224", "C2926"], "release": "$previous"},
   "expect": {"has": {"code": ["C3224", "C2926"]}, "release": "$previous"}},
  {"id": "impact", "tool": "map_assess_release_impact", "arguments": {"fromRelease": "$previous", "conceptCodes": ["C3224", "C2926", "C28327"], "lookupDataElements": false},
   "expect": {"lacks": {"conceptCode": ["C28327"]}},
   "knownIssue": "Codes already retired in fromRelease are reported as changes between the two releases: C28327 was merged in 2021 but appears as 'merged' for the previous-to-current comparison."},
  {"id": "unknown-code", "tool": "evs_get_concept", "arguments": {"code": "C99999999", "release": "$ncit"},
   "expectedError": "not_found"},
  {"id": "withdrawn-release", "tool": "evs_get_concept", "arguments": {"code": "C3224", "release": "25.01d"},
   "expectedError": "release_not_available",
   "note": "Release pinning fails closed: no silent fallback to current content."}
]
```

**What's checked:** both releases are served; the batch keeps active, retired
(`Retired_Concept`) and unknown (`missing`) codes apart; history gives the merge into C4029;
the earlier release is really used (provenance); and an unknown code or withdrawn release
fails with a specific error instead of returning current content.

**Limits:** EVS serves only the last few releases. A retired code with no replacement needs a
curator.

## EVS-06 Drug and intervention normalization

**Goal / who:** A trial abstractor normalizes *Tagrisso*, *AZD9291* and *osimertinib* to
one active ingredient.

```json
[
  {"id": "brand", "tool": "evs_lookup_concept", "arguments": {"identifier": "Tagrisso", "release": "$ncit"},
   "expect": {"has": {"code": ["C170266"]}},
   "note": "The brand name is a synonym of the salt, Osimertinib Mesylate."},
  {"id": "code-name", "tool": "evs_lookup_concept", "arguments": {"identifier": "AZD9291", "release": "$ncit"},
   "expect": {"has": {"code": ["C116377"]}}},
  {"id": "generic", "tool": "evs_lookup_concept", "arguments": {"identifier": "osimertinib", "release": "$ncit"},
   "expect": {"has": {"code": ["C116377"]}}},
  {"id": "salt-to-ingredient", "tool": "evs_get_relationships", "arguments": {"code": "C170266", "kinds": ["associations"], "names": ["Has_Free_Acid_Or_Base_Form"], "release": "$ncit"},
   "expect": {"has": {"code": ["C116377"], "type": ["Has_Free_Acid_Or_Base_Form"]}}},
  {"id": "ingredient", "tool": "evs_get_concept", "arguments": {"code": "C116377", "include": ["properties", "definitions", "synonyms"], "release": "$ncit"},
   "expect": {"has": {"type": ["FDA_UNII_Code"], "value": ["3C06JJ0Z2O"]}}},
  {"id": "unii", "tool": "evs_search_concepts", "arguments": {"property": "FDA_UNII_Code", "value": "3C06JJ0Z2O", "limit": 5, "release": "$ncit"},
   "expect": {"has": {"code": ["C116377"]}, "count": {"max": 1}}},
  {"id": "class", "tool": "evs_get_paths", "arguments": {"code": "C116377", "release": "$ncit"},
   "expect": {"has": {"code": ["C2167"]}}}
]
```

**What's checked:** all three names resolve, the brand to the salt and the other two to the
ingredient; the published `Has_Free_Acid_Or_Base_Form` association links salt to ingredient;
the ingredient's UNII round-trips through a property search; and the class path reaches
*EGFR Tyrosine Kinase Inhibitor* (C2167).

**Limits:** Rolling a salt up to its ingredient is the abstractor's choice; the server only
reports the published link. Salt and ingredient have different UNIIs.

## EVS-07 Biomarker-to-gene, disease and agent relationships

**Goal / who:** A molecular-data curator links EGFR L858R to its gene, to agents that target
it, and to a disease concept.

```json
[
  {"id": "variant", "tool": "evs_search_concepts", "arguments": {"term": "EGFR L858R", "limit": 5, "release": "$ncit"},
   "expect": {"has": {"code": ["C98515"]}, "paged": true}},
  {"id": "variant-gene", "tool": "evs_get_relationships", "arguments": {"code": "C98515", "kinds": ["roles"], "release": "$ncit"},
   "expect": {"has": {"code": ["C17757", "C98357"], "type": ["Molecular_Abnormality_Involves_Gene"]}}},
  {"id": "agents", "tool": "evs_find_concepts", "arguments": {"criteria": [{"kind": "association", "name": "Has_Target", "targetCode": "C98515"}], "limit": 100, "release": "$ncit"},
   "expect": {"has": {"code": ["C116377", "C148147"]}, "count": {"at": "concepts", "min": 5}, "complete": true}},
  {"id": "gene", "tool": "evs_get_concept", "arguments": {"code": "C17757", "include": ["properties", "definitions"], "release": "$ncit"},
   "expect": {"has": {"code": ["C17757"], "source": ["NCI"]}}},
  {"id": "mutation-diseases", "tool": "evs_get_relationships", "arguments": {"code": "C98357", "kinds": ["inverseRoles"], "names": ["Disease_Has_Molecular_Abnormality"], "release": "$ncit"},
   "expect": {"has": {"type": ["Disease_Has_Molecular_Abnormality"]}, "count": {"min": 1}}},
  {"id": "disease-path", "tool": "evs_get_paths", "arguments": {"code": "C227199", "release": "$ncit"},
   "expect": {"has": {"code": ["C202131"]}}}
]
```

**What's checked:** search finds the variant (and pages); its roles reach the gene and the
gene-mutation concept; a reverse `Has_Target` search lists the targeting agents, including
osimertinib and lazertinib, on one page; disease concepts link to the gene mutation; and
*Lung Non-Small Cell Carcinoma with EGFR Mutation* sits under *EGFR-Positive Lung NSCLC*.

**Limits:** These are terminology relationships, not evidence of approval, effectiveness,
eligibility or a treatment recommendation.

## EVS-08 Adverse-event terminology and CTCAE grade definitions

**Goal / who:** A safety abstractor retrieves versioned nausea definitions and the grade
descriptions for qualified clinical review. Nothing here assigns a grade.

```json
[
  {"id": "v5-search", "tool": "evs_search_concepts", "arguments": {"terminology": "ctcae5", "term": "Nausea", "limit": 5, "release": "$ctcae5"},
   "expect": {"has": {"code": ["C146764"]}, "release": "$ctcae5"}},
  {"id": "v5-term", "tool": "evs_get_concept", "arguments": {"terminology": "ctcae5", "code": "C146764", "include": ["definitions", "properties"], "release": "$ctcae5"},
   "expect": {"has": {"code": ["C146764"]}, "count": {"at": "definitions", "min": 1}}},
  {"id": "v5-grades", "tool": "evs_get_hierarchy_neighbors", "arguments": {"terminology": "ctcae5", "direction": "children", "code": "C146764", "release": "$ctcae5"},
   "expect": {"has": {"code": ["C57213", "C57336", "C57467"]}}},
  {"id": "v5-grade3", "tool": "evs_get_concept", "arguments": {"terminology": "ctcae5", "code": "C57467", "include": ["definitions"], "release": "$ctcae5"},
   "expect": {"count": {"at": "definitions", "min": 1}}},
  {"id": "v5-paths", "tool": "evs_get_paths", "arguments": {"terminology": "ctcae5", "code": "C146764", "release": "$ctcae5"},
   "expect": {"has": {"code": ["C146630"]}}},
  {"id": "v6-search", "tool": "evs_search_concepts", "arguments": {"terminology": "ctcae6", "term": "Nausea", "limit": 5, "release": "$ctcae6"},
   "expect": {"has": {"code": ["C220681"]}, "release": "$ctcae6"}},
  {"id": "v6-grades", "tool": "evs_get_hierarchy_neighbors", "arguments": {"terminology": "ctcae6", "direction": "children", "code": "C220681", "release": "$ctcae6"},
   "expect": {"has": {"code": ["C220716", "C220717", "C220718"]}}},
  {"id": "lay-term", "tool": "evs_lookup_concept", "arguments": {"identifier": "vomiting", "release": "$ncit"},
   "expect": {"has": {"code": ["C3442"]}}},
  {"id": "lay-phrase", "tool": "evs_lookup_concept", "arguments": {"identifier": "throwing up", "release": "$ncit"},
   "expect": {"count": {"max": 0}},
   "note": "Exact lookup does not guess: a phrase that is not an NCIt name or synonym returns nothing rather than a near match."}
]
```

**What's checked:** each CTCAE version is read at its own release; grade children and the
grade 3 definition come from the right version; and lay wording resolves only when it is a
published name or synonym.

**Limits:** A clinical reviewer selects the grade. There is no automatic CTCAE 5.0 to 6.0
crosswalk; the codes differ between versions.

## EVS-09 Term dictionary for text mining

**Goal / who:** An NLP developer collects names and synonyms for a bounded lung-carcinoma
branch, keeping each term's code and release.

```json
[
  {"id": "root", "tool": "evs_search_concepts", "arguments": {"term": "Lung Carcinoma", "type": "match", "limit": 5, "release": "$ncit"},
   "expect": {"has": {"code": ["C4878"]}}},
  {"id": "branch", "tool": "evs_get_descendants", "arguments": {"code": "C4878", "maxLevel": 2, "limit": 500, "release": "$ncit"},
   "expect": {"has": {"code": ["C2926"]}, "count": {"min": 50}, "complete": true}},
  {"id": "terms", "tool": "evs_get_concepts", "arguments": {"include": ["synonyms"], "release": "$ncit"},
   "codesFrom": {"step": "branch", "root": "C4878"},
   "expect": {"count": {"at": "concepts", "min": 50}, "has": {"code": ["C4878", "C2926"]}, "release": "$ncit"}},
  {"id": "subtree", "tool": "evs_get_subtree", "arguments": {"code": "C4878", "depth": 2, "criteria": [{"kind": "semanticType", "value": "Neoplastic Process"}], "release": "$ncit"},
   "expect": {"truncated": "maxDepth", "has": {"matches": ["true"]}}}
]
```

**What's checked:** the root resolves; the two-level branch is complete at that depth; one
batch call returns synonyms for the root and every returned code; and the depth-capped
sub-tree flags matching nodes and reports that it stopped at `maxDepth`.

**Limits:** This is a two-level dictionary seed, not the whole branch. Ambiguous terms,
negation and term-pair extraction belong to the consumer.

## Shared limits

- A passing step shows the server returned what the scenario needs. It does not make the
  content medical advice; returned text is upstream data.
- Live EVS content changes monthly. Expectations check stable codes and relationships, not
  exact counts.
- Public context: [CDISC terminology](https://www.cdisc.org/standards/terminology),
  [GDC dictionary](https://docs.gdc.cancer.gov/Data_Dictionary/),
  [EVS API](https://api-evsrest.nci.nih.gov/v3/api-docs).
