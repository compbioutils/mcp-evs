# EVS tools (`evs_*`)

These tools read the **NCI Thesaurus (NCIt)** through NCI's EVS service. NCIt is a large
dictionary of cancer and biomedical concepts. Each concept has a code (such as `C3224`), a
preferred name (*Melanoma*), synonyms, a definition, a place in a hierarchy, and links to
other concepts.

They are available in the `evs-only` and `unified` profiles. Unless noted, every tool also
accepts the shared `terminology` and `release` inputs described in the [tool guide](README.md#inputs-that-many-tools-share).

## Pick a tool

| I want to… | Use |
|---|---|
| See which terminologies or releases exist | [`evs_list_terminologies`](#evs_list_terminologies), [`evs_list_releases`](#evs_list_releases) |
| Learn the valid relationship or property names | [`evs_get_terminology_metadata`](#evs_get_terminology_metadata) |
| Look up a concept I have a code for | [`evs_get_concept`](#evs_get_concept), [`evs_get_concepts`](#evs_get_concepts) |
| Turn a name or abbreviation into a code | [`evs_lookup_concept`](#evs_lookup_concept) |
| Search by words, or autocomplete | [`evs_search_concepts`](#evs_search_concepts), [`evs_suggest_concepts`](#evs_suggest_concepts) |
| Move up or down the hierarchy | [`evs_get_hierarchy_neighbors`](#evs_get_hierarchy_neighbors), [`evs_get_descendants`](#evs_get_descendants), [`evs_get_paths`](#evs_get_paths), [`evs_get_subtree`](#evs_get_subtree) |
| See how a concept relates to others | [`evs_get_relationships`](#evs_get_relationships), [`evs_traverse`](#evs_traverse) |
| Work with value sets (subsets) | [`evs_list_subsets`](#evs_list_subsets), [`evs_get_subset_members`](#evs_get_subset_members) |
| Map to other code systems (GDC, ICD-10, …) | [`evs_get_concept_maps`](#evs_get_concept_maps), [`evs_list_mapsets`](#evs_list_mapsets), [`evs_get_mapset_entries`](#evs_get_mapset_entries) |
| Check whether a code was retired | [`evs_get_concept_history`](#evs_get_concept_history) |
| Find every concept matching a rule | [`evs_find_concepts`](#evs_find_concepts) |

---

## `evs_list_terminologies`

**List the terminologies EVS offers.**

Returns each terminology with its latest version and whether it needs a license.

**Use cases**

1. **See what is available.** *"Which vocabularies can I search?"*
   ```json
   {}
   ```
2. **Check licensing before you start.** *"Does MedDRA need a license here?"* Ask for the
   list, then read the license status on the MedDRA entry.
   ```json
   {}
   ```

**Inputs:** none.

---

## `evs_list_releases`

**List the NCIt releases EVS currently serves, and which one this server uses.**

**Use cases**

1. **Find the release to cite.** *"Which NCIt release are my answers based on?"*
   ```json
   {}
   ```
2. **Check a release before pinning to it.** *"Is 26.09d still available?"*
   ```json
   { "terminology": "ncit" }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `terminology` | No | Terminology ID. Default `ncit`. |

**Good to know:** EVS keeps only a few recent releases online, including weekly ones. The
server uses the latest **monthly** release unless the operator pins another.

---

## `evs_get_terminology_metadata`

**List the vocabulary of the vocabulary:** relationship names, property names, term types and
sources.

Use it to learn the exact names other tools expect, such as `Disease_Has_Finding`.

**Use cases**

1. **Learn the relationship names.** *"What kinds of links can a disease have?"*
   ```json
   { "kinds": ["roles"] }
   ```
2. **Learn the term types used for synonyms.** *"What does a term type of `AB` mean?"*
   ```json
   { "kinds": ["termTypes"] }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `kinds` | Yes | One or more of `roles`, `associations`, `properties`, `qualifiers`, `termTypes`, `synonymSources`, `definitionSources`, `conceptStatuses`, `synonymTypes`, `definitionTypes`. |

**Good to know:** `conceptStatuses` currently fails against live EVS (see
[known issues](README.md#known-issues-checked-19-november-2026)).

---

## `evs_get_concept`

**Get the details of one concept from its code.**

By default you get the name, synonyms, definitions and properties.

**Use cases**

1. **Find out what a code means.** *"What is C3224?"*
   ```json
   { "code": "C3224" }
   ```
2. **See its parents and children too.** *"Show Melanoma and where it sits."*
   ```json
   { "code": "C3224", "include": ["summary", "parents", "children"] }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `code` | Yes | An NCIt code such as `C3224`. |
| `include` | No | How much detail. `minimal`, `summary` (default) or `full`, or add specific parts: `parents`, `children`, `roles`, `inverseRoles`, `associations`, `inverseAssociations`, `maps`, `history`, `disjointWith`, `subsetLink`. |

**Good to know:** `full` is large and slow. Ask for only the parts you need. With `maps`, targets
that need a license key (MedDRA by default) are removed and listed in `mapsWithheld`.

---

## `evs_get_concepts`

**Get many concepts at once** (up to 1,000 codes) in a single efficient call.

Codes that don't exist are listed in `result.missing`.

**Use cases**

1. **Name a list of codes.** *"What are C3224, C2926 and C4872?"*
   ```json
   { "codes": ["C3224", "C2926", "C4872"], "include": ["minimal"] }
   ```
2. **Check a list for bad codes.** *"Which codes in my spreadsheet don't exist?"* Read
   `result.missing`.
   ```json
   { "codes": ["C3224", "C999999999"], "include": ["minimal"] }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `codes` | Yes | 1 to 1,000 NCIt codes. |
| `include` | No | Same options as [`evs_get_concept`](#evs_get_concept). Use `minimal` for big lists. |

---

## `evs_lookup_concept`

**Turn a code, name or synonym into a concept,** using exact matching.

Each match says whether it matched the `code`, the preferred `name` or a `synonym`.

**Use cases**

1. **Decode an abbreviation.** *"What is NSCLC?"* Returns C2926, *Lung Non-Small Cell
   Carcinoma*, matched by synonym.
   ```json
   { "identifier": "NSCLC" }
   ```
2. **Confirm an exact name exists.** *"Is 'Melanoma' an NCIt term?"*
   ```json
   { "identifier": "Melanoma", "match": "exact" }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `identifier` | Yes | A code, a preferred name or a synonym. |
| `match` | No | `normalized` (default) ignores case, spaces and punctuation; `exact` ignores only case. |
| `synonymSource` | No | Only match synonyms from this source, such as `NCI`, `CDISC` or `GDC`. |
| `termType` | No | Only match synonyms of this type, such as `PT`, `SY` or `AB`. |
| `include` | No | Detail level for each match. Default `summary`. |
| `limit` | No | 1–50. Default 10. |

**Good to know:** this tool doesn't do partial matches. For those, use
[`evs_search_concepts`](#evs_search_concepts).

---

## `evs_search_concepts`

**Search NCIt by words,** with optional filters. Results come a page at a time.

**Use cases**

1. **Find concepts by everyday words.** *"Find concepts about breast cancer."* The top result
   is C4872, *Breast Carcinoma*.
   ```json
   { "term": "breast cancer", "limit": 5 }
   ```
2. **Find retired concepts.** *"Which lung cancer codes have been retired?"*
   ```json
   { "term": "lung cancer", "conceptStatus": "Retired_Concept", "limit": 5 }
   ```

You can also search by a filter alone. For example, `{"property": "ICD-O-3_Code", "value":
"8140/3"}` finds C2852, *Adenocarcinoma*.

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `term` | Unless a filter is given | The words to search for. With filters, results must match the term **and** every filter. |
| `type` | No | How to match: `contains` (default), `match`, `startsWith`, `phrase`, `AND`, `OR` or `fuzzy`. |
| `limit` | No | 1–100. Default 20. |
| `cursor` | No | `nextCursor` from the previous page. |
| `conceptStatus` | No | Such as `Retired_Concept`. |
| `semanticType` | No | Such as `Neoplastic Process`. Sent to EVS as the `Semantic_Type` property, so it can't be combined with `property`/`value`. |
| `subset` | No | Only concepts in this subset, such as `C66731`. |
| `synonymSource`, `synonymTermType`, `definitionSource` | No | Narrow by where the synonym or definition comes from. |
| `property`, `value` | No | A property filter, such as `property: "ICD-O-3_Code"` with `value: "8140/3"`. |
| `include` | No | Detail per result. Default is small (`minimal`). |

---

## `evs_suggest_concepts`

**Autocomplete:** concepts whose name or synonym starts with what you've typed.

**Use cases**

1. **Finish a half-typed word.** *"What starts with 'melan'?"*
   ```json
   { "prefix": "melan" }
   ```
2. **Offer quick choices in a form.** *"Give me five terms starting with 'lung'."*
   ```json
   { "prefix": "lung", "limit": 5 }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `prefix` | Yes | The beginning of a word or name. |
| `limit` | No | 1–20. Default 10. |

---

## `evs_get_hierarchy_neighbors`

**Get a concept's immediate parents or children,** or the top-level roots of NCIt.

**Use cases**

1. **Go one level up.** *"What is Melanoma a kind of?"* Returns parents such as *Malignant
   Neoplasm* (C9305).
   ```json
   { "direction": "parents", "code": "C3224" }
   ```
2. **Go one level down.** *"What are the types of Melanoma?"*
   ```json
   { "direction": "children", "code": "C3224" }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `direction` | Yes | `parents`, `children` or `roots`. |
| `code` | Yes, unless `roots` | The concept to start from. |

**Good to know:** `{"direction": "roots"}` lists NCIt's top-level branches.

---

## `evs_get_descendants`

**List everything below a concept,** as a flat, paged list with each item's level.

**Use cases**

1. **Get the direct subtypes only.** *"List the first level under Melanoma."*
   ```json
   { "code": "C3224", "maxLevel": 1, "limit": 20 }
   ```
2. **Collect a whole branch.** *"Give me all kinds of Breast Carcinoma."* Follow
   `page.nextCursor` for more.
   ```json
   { "code": "C4872", "limit": 50 }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `code` | Yes | The top concept. |
| `maxLevel` | No | How deep to go. `1` means children only. Up to 50. |
| `limit` | No | 1–1,000 per page. Default 200. |
| `cursor` | No | `nextCursor` from the previous page. |

---

## `evs_get_paths`

**Show the path from a concept up to the top of NCIt,** or to a specific ancestor. This is how
you get a concept's ancestors.

**Use cases**

1. **See the full lineage.** *"How does Melanoma connect to the root?"*
   ```json
   { "code": "C3224" }
   ```
2. **Check that one concept falls under another.** *"Is Cutaneous Melanoma a kind of
   Neoplasm?"* If paths come back, the answer is yes.
   ```json
   { "code": "C3510", "kind": "toAncestor", "ancestorCode": "C3262" }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `code` | Yes | The starting concept. |
| `kind` | No | `toRoot` (default), `fromRoot` or `toAncestor`. |
| `ancestorCode` | For `toAncestor` | The ancestor to stop at. |

**Good to know:** a concept can have more than one path, because NCIt concepts can have
several parents.

---

## `evs_get_relationships`

**List how a concept is linked to other concepts,** such as the findings a disease has or the
body site it affects.

Each link has a `polarity`. `negative` means an exclusion, such as `Disease_Excludes_Finding`.

**Use cases**

1. **See all links for a concept.** *"How is Melanoma related to other concepts?"*
   ```json
   { "code": "C3224" }
   ```
2. **See one kind of link.** *"What findings does Melanoma have?"*
   ```json
   { "code": "C3224", "kinds": ["roles"], "names": ["Disease_Has_Finding"] }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `code` | Yes | The concept. |
| `kinds` | No | Any of `roles`, `inverseRoles`, `associations`, `inverseAssociations`, `disjointWith`. Default `roles` and `associations`. |
| `names` | No | Only these relationship names. Get valid names from [`evs_get_terminology_metadata`](#evs_get_terminology_metadata). |

---

## `evs_list_subsets`

**List NCIt subsets (value sets),** or describe one.

**Use cases**

1. **Browse the available value sets.** *"What value sets does NCIt publish?"*
   ```json
   {}
   ```
2. **Describe one value set.** *"What is subset C66731?"* It's *CDISC SDTM Sex of Individual
   Terminology*.
   ```json
   { "code": "C66731" }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `code` | No | A subset code. Omit it to list the top-level subsets. |

**Good to know:** EVS serves subset lists only for its current release, so asking for an
older `release` returns `release_mismatch`. A code that isn't a subset returns `not_found`. To
list a subset's concepts, use [`evs_get_subset_members`](#evs_get_subset_members).

---

## `evs_get_subset_members`

**List the concepts in a subset (value set),** one page at a time.

**Use cases**

1. **Get the allowed values of a standard list.** *"What are the CDISC SDTM sex values?"*
   ```json
   { "code": "C66731" }
   ```
2. **Page through a large value set.** *"Show the first 10 GDC values."*
   ```json
   { "code": "C177537", "limit": 10 }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `code` | Yes | The subset code. |
| `include` | No | Detail per member. Default is small (`minimal`). |
| `limit` | No | 1–1,000 per page. Default 100. |
| `cursor` | No | `nextCursor` from the previous page. |

---

## `evs_get_concept_maps`

**Show how an NCIt concept maps to other code systems,** such as GDC or ICD-O.

Maps that need a license key are hidden and listed in `result.withheld`.

**Use cases**

1. **See all mappings for a concept.** *"What does Melanoma map to?"*
   ```json
   { "code": "C3224" }
   ```
2. **Map to one system only.** *"What is Melanoma's GDC value?"*
   ```json
   { "code": "C3224", "targetTerminology": "GDC" }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `code` | Yes | The NCIt concept. |
| `targetTerminology` | No | Only maps to this system, such as `GDC`, `ICD10CM` or `MedDRA`. |

**Good to know:** MedDRA needs a license key. Without one, its maps appear only in
`withheld`.

---

## `evs_list_mapsets`

**List the mapping tables EVS publishes,** such as `NCIt_Maps_To_GDC` or
`NCIt_Maps_To_ICD10CM`.

**Use cases**

1. **See which mapping tables exist.** *"Which systems can NCIt be mapped to?"*
   ```json
   {}
   ```
2. **Find the exact name of a mapping table.** *"What's the GDC mapset called?"* Use the code
   you find with [`evs_get_mapset_entries`](#evs_get_mapset_entries).
   ```json
   {}
   ```

**Inputs:** none. This tool doesn't take `terminology` or `release`.

---

## `evs_get_mapset_entries`

**Read the rows of one mapping table,** one page at a time, optionally filtered by text.

**Use cases**

1. **Browse a mapping table.** *"Show the first 10 NCIt-to-GDC mappings."*
   ```json
   { "mapset": "NCIt_Maps_To_GDC", "limit": 10 }
   ```
2. **Find mappings for a word.** *"Which GDC mappings mention melanoma?"*
   ```json
   { "mapset": "NCIt_Maps_To_GDC", "term": "melanoma", "limit": 10 }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `mapset` | Yes | The mapset code from [`evs_list_mapsets`](#evs_list_mapsets). |
| `term` | No | Text to filter source or target names and codes. |
| `limit` | No | 1–1,000 per page. Default 100. |
| `cursor` | No | `nextCursor` from the previous page. |

**Good to know:** for license-gated tables without a key, you get only the row count, with
`licenseRequired: true`. This tool doesn't take `terminology` or `release`.

---

## `evs_get_concept_history`

**Show a concept's change history:** when it was created, changed, merged or retired, and
what replaced it.

**Use cases**

1. **Check whether an old code is still valid.** *"Was C9424 retired, and what replaced
   it?"* Look for a `retire` action and `replacementCode`.
   ```json
   { "code": "C9424" }
   ```
2. **See how a concept changed over time.** *"When was Melanoma created and last modified?"*
   ```json
   { "code": "C3224" }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `code` | Yes | The concept code. |

---

## `evs_traverse`

**Walk outward from one or more concepts** across several steps, following the kinds of links
you choose, within safe limits.

It stops at the first limit it reaches and says which one in `truncation`. Exclusion links
(such as `Disease_Excludes_Finding`) are listed separately in `result.exclusions` and are not
followed unless you ask.

**Use cases**

1. **Collect subtypes two levels down.** *"Get Melanoma and its subtypes, two levels deep."*
   ```json
   { "start": ["C3224"], "selectors": [{ "kind": "children" }], "budget": { "maxDepth": 2 } }
   ```
2. **Follow one kind of link.** *"What findings does Melanoma lead to?"*
   ```json
   {
     "start": ["C3224"],
     "selectors": [{ "kind": "roles", "names": ["Disease_Has_Finding"] }],
     "budget": { "maxDepth": 1 }
   }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `start` | Yes | 1 to 20 starting codes. |
| `selectors` | Yes | Links to follow. Each has a `kind`: `parents`, `children`, `roles`, `inverseRoles`, `associations` or `inverseAssociations`. You can add `names` to limit roles or associations. |
| `budget` | No | Limits: `maxDepth` (default 2, max 4), `maxNodes` (200, max 1,000), `maxEdges` (1,000, max 5,000), `maxRequests` (50, max 200), and optional `perKind`. |
| `includeExclusions` | No | `true` to follow exclusion links too. Default `false`. |

---

## `evs_get_subtree`

**Get a nested tree under a concept,** with each node marked when it meets your criteria.

**Use cases**

1. **Draw a small tree.** *"Show Melanoma's tree, two levels deep."*
   ```json
   { "code": "C3224", "depth": 2 }
   ```
2. **Keep only matching branches.** *"Under Melanoma, show only nodes that are neoplastic
   processes."*
   ```json
   {
     "code": "C3224",
     "depth": 2,
     "criteria": [{ "kind": "semanticType", "value": "Neoplastic Process" }],
     "prune": true
   }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `code` | Yes | The root of the tree. |
| `depth` | No | 0–4 levels below the root. Default 2. |
| `criteria` | No | Rules that mark matches: `{kind: "property", name, value}`, `{kind: "conceptStatus", value}` or `{kind: "semanticType", value}`. |
| `prune` | No | `true` drops branches with no match. Needs `criteria`. |
| `budget` | No | Same limits as [`evs_traverse`](#evs_traverse). |

**Good to know:** a concept with several parents appears only under the first one reached.

---

## `evs_find_concepts`

**Find every concept that meets one or more rules,** such as "has this ICD-O code" or "has
this finding".

The answer includes `result.plan`, which explains how the server found the concepts.

**Use cases**

1. **Find concepts by a property value.** *"Which concept has ICD-O-3 code 8720/3?"* Returns
   C3224, *Melanoma*.
   ```json
   { "criteria": [{ "kind": "property", "name": "ICD-O-3_Code", "value": "8720/3" }] }
   ```
2. **Find diseases with a given finding.** *"Which diseases have Malignant Cellular
   Infiltrate (C36115) as a finding?"*
   ```json
   {
     "criteria": [{ "kind": "role", "name": "Disease_Has_Finding", "targetCode": "C36115" }],
     "limit": 5
   }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `criteria` | Yes | One or more rules: `property` (name, value), `term` (value), `subset` (value is a subset code), `role` or `association` (name, targetCode), `associationType` (name), or `conceptStatus` / `semanticType` (value; only to narrow other rules with `AND`). |
| `combinator` | No | `AND` (default) or `OR`. |
| `limit` | No | 1–1,000. Default 100. |
| `cursor` | No | `nextCursor` from the previous page. |

**Good to know:** some combinations, such as two different property values joined with
`AND`, can't be answered with EVS's standard API. They return `capability_unavailable` with
`plan.path = "sparql_required"`. A `semanticType` rule counts as a property here, because it
is sent as the `Semantic_Type` property.
