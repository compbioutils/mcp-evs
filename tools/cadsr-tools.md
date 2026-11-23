# caDSR tools (`cadsr_*`)

These tools read **caDSR**, NCI's registry of **Common Data Elements (CDEs)**. A CDE is a
standard data field, such as *Race Category Text* (public ID `2192199`), with a definition,
allowed values and links to NCIt concepts.

A CDE is identified by a **public ID** and a **version** (such as `1.0`). If you leave out the
version, you get the latest one. caDSR has no release numbers, so answers are cited by public
ID, version and retrieval time.

They are available in the `cadsr-only` and `unified` profiles. 🔑 marks tools that need a caDSR
login (`ECM_CADSR_USERNAME` and `ECM_CADSR_PASSWORD`).

## Pick a tool

| I want to… | Use |
|---|---|
| Read a CDE | [`cadsr_get_data_element`](#cadsr_get_data_element), [`cadsr_get_data_elements`](#cadsr_get_data_elements) |
| See a CDE's versions | [`cadsr_get_data_element_versions`](#cadsr_get_data_element_versions) |
| See a CDE's allowed values or data type | [`cadsr_get_permissible_values`](#cadsr_get_permissible_values), [`cadsr_get_value_domain`](#cadsr_get_value_domain) |
| See what a CDE describes | [`cadsr_get_data_element_concept`](#cadsr_get_data_element_concept) |
| Find CDEs | [`cadsr_find_data_elements_by_concept`](#cadsr_find_data_elements_by_concept), [`cadsr_find_data_elements`](#cadsr_find_data_elements) |
| Work with forms | [`cadsr_get_form`](#cadsr_get_form), [`cadsr_get_forms_for_data_element`](#cadsr_get_forms_for_data_element) |
| Match my column names or values to caDSR | [`cadsr_list_match_backends`](#cadsr_list_match_backends), [`cadsr_match_data_elements`](#cadsr_match_data_elements), [`cadsr_match_value_meanings`](#cadsr_match_value_meanings) |
| CRDC crosswalk and registry information | [`cadsr_get_crdc_code_map`](#cadsr_get_crdc_code_map), [`cadsr_list_contexts`](#cadsr_list_contexts), [`cadsr_get_registry_status`](#cadsr_get_registry_status) |

---

## `cadsr_get_data_element`

**Get one CDE:** its name, definition, data type and the NCIt concepts behind it.

**Use cases**

1. **Look up a CDE by its ID.** *"What is CDE 2192199?"* It's *Race Category Text*.
   ```json
   { "publicId": "2192199" }
   ```
2. **Get a specific version with its allowed values.** *"Show version 1.0 of CDE 2192199 and
   its allowed values."*
   ```json
   { "publicId": "2192199", "version": "1.0", "include": ["permissibleValues"] }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `publicId` | Yes | The CDE public ID, digits only. |
| `version` | No | Such as `1.0`. Default: latest. |
| `include` | No | Sections to add: `valueDomain`, `permissibleValues`, `dataElementConcept`, `alternateNames`, `classificationSchemes`, `referenceDocuments`. Default `valueDomain` and `dataElementConcept`. |

**Good to know:** the first request for a CDE can take 6–10 seconds; repeats are fast. For
long value lists, use [`cadsr_get_permissible_values`](#cadsr_get_permissible_values).

---

## `cadsr_get_data_elements`

**Get several CDEs in one request** (up to 20). Unknown IDs are listed in `result.missing`.

**Use cases**

1. **Compare a few CDEs side by side.** *"Show CDEs 2192199 and 2192217."*
   ```json
   { "ids": [{ "publicId": "2192199" }, { "publicId": "2192217" }] }
   ```
2. **Check which IDs in a list are real.** *"Do 2192199 v1.0 and 9999999 exist?"* Read
   `result.missing`.
   ```json
   { "ids": [{ "publicId": "2192199", "version": "1.0" }, { "publicId": "9999999" }] }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `ids` | Yes | 1 to 20 items, each `{ "publicId": "…", "version": "…" }`. `version` is optional. |

**Good to know:** caDSR has no batch endpoint, so this makes one request per CDE.

---

## `cadsr_get_data_element_versions`

**List every version of a CDE,** newest first, with its status and which one is latest.

**Use cases**

1. **Find the latest version.** *"What's the newest version of CDE 2192199?"*
   ```json
   { "publicId": "2192199" }
   ```
2. **Check whether the version you use is outdated.** *"Is version 1.0 of 2192199 still
   current?"* Compare it with the entry marked `latestVersion`.
   ```json
   { "publicId": "2192199" }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `publicId` | Yes | The CDE public ID. |

---

## `cadsr_get_permissible_values`

**List a CDE's allowed values,** with each value's meaning and NCIt concept. Results are paged.

**Use cases**

1. **See what answers a field accepts.** *"What values are allowed for Race (2192199)?"*
   ```json
   { "publicId": "2192199" }
   ```
2. **Page through a long list.** *"Show the first 5 allowed values."*
   ```json
   { "publicId": "2192199", "limit": 5 }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `publicId` | Yes | The CDE public ID. |
| `version` | No | Default: latest. |
| `limit` | No | 1–1,000 per page. Default 100. |
| `cursor` | No | `nextCursor` from the previous page. |

**Good to know:** free-text and numeric fields have no list, so they return an empty result.

---

## `cadsr_get_value_domain`

**Show what kind of data a CDE holds:** text or number, format, minimum and maximum, and how
many allowed values it has.

**Use cases**

1. **Check the data type before loading data.** *"Is CDE 2192199 text or a number?"*
   ```json
   { "publicId": "2192199" }
   ```
2. **Check a specific version's rules.** *"What format did version 1.0 use?"*
   ```json
   { "publicId": "2192199", "version": "1.0" }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `publicId` | Yes | The CDE public ID. |
| `version` | No | Default: latest. |

---

## `cadsr_get_data_element_concept`

**Show what a CDE describes:** its *object* (for example, *Person*) and *property* (for
example, *Race*), each with NCIt concepts.

**Use cases**

1. **Understand a CDE's meaning.** *"What thing and attribute does CDE 2192199 describe?"*
   ```json
   { "publicId": "2192199" }
   ```
2. **Get the NCIt codes behind a CDE.** *"Which NCIt concepts define version 1.0?"*
   ```json
   { "publicId": "2192199", "version": "1.0" }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `publicId` | Yes | The CDE public ID. |
| `version` | No | Default: latest. |

---

## `cadsr_find_data_elements_by_concept`

**Find CDEs that use an NCIt concept.**

**Use cases**

1. **Find all CDEs about a topic.** *"Which CDEs use the Race concept (C17049)?"*
   ```json
   { "conceptCode": "C17049" }
   ```
2. **Find CDEs that use it in one role.** *"Which CDEs use Race as their property?"*
   ```json
   { "conceptCode": "C17049", "itemType": "Property" }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `conceptCode` | Yes | An NCIt code. |
| `itemType` | No | `ObjectClass`, `Property`, `RepresentationTerm` or `ValueMeaning`. |
| `workflowStatus` | No | Such as `RELEASED`, `DRAFT NEW` or `RETIRED ARCHIVED`. |
| `limit` | No | 1–100 per page. Default 50. |
| `cursor` | No | `nextCursor` from the previous page. |

**Good to know:** each result's `matchedRole` is filled only when you set `itemType`.

---

## `cadsr_find_data_elements`

**Find CDEs by name, question text, context or classification.**

caDSR has no general keyword search, so this tool runs several specific lookups and combines
the results. `result.coverage` lists the lookups that ran, so results may be incomplete.

**Use cases**

1. **Search by a word.** *"Find CDEs named or asked as 'race'."*
   ```json
   { "query": "race" }
   ```
2. **Search within a context.** *"Find 'race' CDEs owned by the NCIP context."*
   ```json
   { "query": "race", "by": ["context"], "context": "NCIP" }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `query` | Yes | A name, question text or ID fragment. |
| `by` | No | Lookups to run: `alternateName`, `questionText`, `classification`, `context`. Default the first two. |
| `exact` | No | `true` for exact matches only. Default `false`. |
| `context` | For `context` | A context name such as `NCIP` or `CTEP`. |
| `classificationSchemePublicId`, `classificationSchemeVersion` | For `classification` | The classification scheme to search. |
| `limit` | No | 1–100 per page. Default 50. |
| `cursor` | No | `nextCursor` from the previous page. |

---

## `cadsr_get_form`

**Get a caDSR form (case report form),** with its sections, questions, the CDE behind each
question and the answer choices.

**Use cases**

1. **See a form's questions.** *"What does form 3105395 ask?"*
   ```json
   { "publicId": "3105395" }
   ```
2. **Get only the form header.** *"What is form 3105395? Skip the questions."*
   ```json
   { "publicId": "3105395", "includeModules": false }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `publicId` | Yes | The form public ID. |
| `version` | No | Default: latest. |
| `includeModules` | No | `false` skips the sections and questions. Default `true`. |

---

## `cadsr_get_forms_for_data_element`

**Find the forms that ask a question using a CDE.**

**Use cases**

1. **See where a CDE is used.** *"Which forms collect Race using CDE 2192199 v1.0?"*
   ```json
   { "publicId": "2192199", "version": "1.0" }
   ```
2. **Check the impact before changing a CDE.** *"If CDE 2192199 v1.0 changes, which forms are
   affected?"*
   ```json
   { "publicId": "2192199", "version": "1.0" }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `publicId` | Yes | The CDE public ID. |
| `version` | Yes | Forms use a specific CDE version. |

---

## `cadsr_list_contexts`

🔑 **Needs a caDSR login.**

**List caDSR contexts,** the organizations or programs that own CDEs, such as `NCIP` or `CTEP`.

**Use cases**

1. **Learn the valid context names.** *"Which contexts exist in caDSR?"*
   ```json
   {}
   ```
2. **Pick a context for searching.** *"What name do I use to search within CTEP?"* Use the name
   with [`cadsr_find_data_elements`](#cadsr_find_data_elements).
   ```json
   {}
   ```

**Inputs:** none.

**Good to know:** needs a caDSR login. Without one, it returns `capability_unavailable` with the
setting to configure.

---

## `cadsr_list_match_backends`

**Show which matching services this server can use,** and why any are unavailable.

**Use cases**

1. **Check before matching.** *"Can this server match column names to CDEs?"*
   ```json
   {}
   ```
2. **Troubleshoot matching.** *"Why did my match request fail?"* The `reason` field says what
   is missing.
   ```json
   {}
   ```

**Inputs:** none.

---

## `cadsr_match_data_elements`

🔑 **Needs a caDSR login** for the default backend.

**Suggest CDEs for your column names or survey questions,** optionally using their sample
values.

**Use cases**

1. **Match a spreadsheet column.** *"Which CDE fits my 'Race' column with White and Asian?"*
   ```json
   { "entities": [{ "name": "Race", "permissibleValues": ["White", "Asian"] }] }
   ```
2. **Match several columns at once.** *"Suggest CDEs for 'Gender' and 'Date of Birth'."*
   ```json
   { "entities": [{ "name": "Gender" }, { "name": "Date of Birth" }], "matchLimit": 3 }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `entities` | Yes | 1 to 10 items: `name` (required), `userTip` (a description) and `permissibleValues` (sample values). |
| `backend` | No | `cde_match` (default, needs a login) or `ai_engine` (needs the CDE AI Match service). |
| `matchLimit` | No | 1–25 candidates per item. Default 5. |
| `contexts` | No | Only suggest CDEs from these contexts. |

**Good to know:** check [`cadsr_list_match_backends`](#cadsr_list_match_backends) first. With no
backend, try [`map_suggest_cdes_for_term`](map-tools.md#map_suggest_cdes_for_term).

---

## `cadsr_match_value_meanings`

**Match your values to caDSR value meanings,** each linked to an NCIt concept.

**Use cases**

1. **Standardize answers.** *"What standard meanings do 'White' and 'Caucasian' match?"*
   ```json
   { "values": ["White", "Caucasian"] }
   ```
2. **Match only to NCIt.** *"Match 'Male' and 'Female' to NCIt meanings only."*
   ```json
   { "values": ["Male", "Female"], "terminologyScope": ["NCIt"] }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `values` | Yes | 1 to 10 value strings. |
| `strictness` | No | Such as `exact` or `fuzzy`. |
| `terminologyScope` | No | Restrict to these terminologies, such as `["NCIt"]`. |

---

## `cadsr_get_crdc_code_map`

**Read the CRDC crosswalk:** the CDEs that NCI's Cancer Research Data Commons uses across
data models.

**Use cases**

1. **Browse the crosswalk.** *"Which CDEs does CRDC harmonize?"*
   ```json
   { "limit": 5 }
   ```
2. **Check one CDE.** *"Is CDE 2192199 in the CRDC crosswalk, and for which models?"*
   ```json
   { "dataElementId": "2192199" }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `dataElementId` | No | Only this CDE public ID. |
| `limit` | No | 1–1,000 per page. Default 100. |
| `cursor` | No | `nextCursor` from the previous page. |

---

## `cadsr_get_registry_status`

**Report what is known about caDSR's current state.**

caDSR doesn't publish release numbers, so this always says `published: false`. It adds the
date of the latest daily export when the operator configures an export listing.

**Use cases**

1. **Know how to cite caDSR.** *"Does caDSR have a release number I can cite?"*
   ```json
   {}
   ```
2. **Check how fresh the registry data is.** *"When was caDSR last exported?"* Read
   `exportDate`.
   ```json
   {}
   ```

**Inputs:** none.
