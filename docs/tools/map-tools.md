# Mapping tools (`map_*`)

These tools connect **caDSR CDEs** with **NCIt concepts**, and check data models such as the
GDC data dictionary or CRDC MDF models against both.

They are available only in the `unified` profile.

Some of these tools **compute** a verdict, a ranking or a list of problems. NCI doesn't supply
those directly. In those answers, `meta.exception` explains what the server computed. Treat
those results as well-supported suggestions, not official NCI content.

## Pick a tool

| I want to… | Use |
|---|---|
| See the NCIt concepts behind a CDE, and whether they are still current | [`map_resolve_cde_concepts`](#map_resolve_cde_concepts) |
| Find the CDEs that use an NCIt concept | [`map_find_data_elements_for_concept`](#map_find_data_elements_for_concept) |
| Explain one allowed value of a CDE | [`map_explain_permissible_value`](#map_explain_permissible_value) |
| Compare two lists of values | [`map_align_value_sets`](#map_align_value_sets) |
| Check a property in my data model | [`map_resolve_model_property`](#map_resolve_model_property), [`map_validate_model_fragment`](#map_validate_model_fragment) |
| Compare properties from two models | [`map_crosswalk_properties`](#map_crosswalk_properties) |
| Find a CDE for my column name | [`map_suggest_cdes_for_term`](#map_suggest_cdes_for_term) |
| See what changed between NCIt releases | [`map_assess_release_impact`](#map_assess_release_impact) |
| Convert ICD-O codes or find GDC values | [`map_map_icdo_to_ncit`](#map_map_icdo_to_ncit), [`map_resolve_stored_value`](#map_resolve_stored_value) |

## Model fragments

Several tools read a **model fragment**: a piece of a data model that you paste in. The server
reads it but never downloads or stores model files.

A fragment has these fields:

| Field | Required | What to give |
|---|---|---|
| `format` | Yes | `gdc_json`, `gdc_yaml` or `mdf_yaml`. |
| `content` | Yes | The fragment text, as a string. |
| `entity` | No | The node or entity to use, if the fragment has several. |
| `property` | No | One property to check. Omit it to check them all (up to 50). |

The examples below use these two small fragments. Both describe a `race` property that
points to CDE `2192199` version `1.0`.

**MDF YAML** (`mdf_yaml`):

```yaml
PropDefinitions:
  race:
    Desc: Race of the participant
    Term:
      - Origin: caDSR
        Code: "2192199"
        Version: "1.0"
    Enum:
      - White
      - Asian
```

**GDC JSON** (`gdc_json`):

```json
{
  "id": "demographic",
  "properties": {
    "race": {
      "termDef": { "cde_id": 2192199, "cde_version": 1.0 },
      "enum": ["white", "asian"]
    }
  }
}
```

In the examples, `"<MDF fragment>"` and `"<GDC fragment>"` stand for that text, passed as one
string.

---

## `map_resolve_cde_concepts`

**Show the NCIt concepts behind a CDE,** checked against the current NCIt release.

For each concept you get the NCIt name, whether it's `active`, `retired` or `not_found`, a
replacement if it's retired, and whether caDSR's name agrees with NCIt.

**Use cases**

1. **See what a CDE means in NCIt terms.** *"Which NCIt concepts define CDE 2192199?"*
   ```json
   { "publicId": "2192199", "version": "1.0" }
   ```
2. **Check the allowed values too.** *"Are any of CDE 2192199's value concepts retired?"*
   ```json
   { "publicId": "2192199", "version": "1.0", "includePermissibleValues": true }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `publicId` | Yes | The CDE public ID. |
| `version` | No | Default: latest. |
| `includePermissibleValues` | No | `true` also checks each allowed value's concept. Default `false`. |
| `release` | No | NCIt release to check against. Default: current. |

---

## `map_find_data_elements_for_concept`

**Find the CDEs that use an NCIt concept,** grouped by concept. It can include narrower concepts
too.

**Use cases**

1. **Find CDEs for a concept.** *"Which CDEs use the Race concept (C17049)?"*
   ```json
   { "conceptCode": "C17049" }
   ```
2. **Include subtypes.** *"Which CDEs use Melanoma or its direct subtypes?"*
   ```json
   { "conceptCode": "C3224", "expandDescendants": true, "maxLevel": 1, "maxConcepts": 5 }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `conceptCode` | Yes | An NCIt code. |
| `expandDescendants` | No | `true` also checks narrower concepts. Default `false`. |
| `maxLevel` | No | How many levels down to include, 1–10. Default 2. |
| `maxConcepts` | No | Maximum number of concepts checked, 1–100, including the starting one. Default 20. |
| `itemType` | No | `ObjectClass`, `Property`, `RepresentationTerm` or `ValueMeaning`. |
| `release` | No | NCIt release. Default: current. |

**Good to know:** each concept is a separate caDSR request, so keep `maxConcepts` small.
`truncation` tells you whether some concepts were skipped.

---

## `map_explain_permissible_value`

**Explain one allowed value of a CDE:** its meaning, NCIt concept, definition, synonyms and
whether it's still current.

**Use cases**

1. **Understand a value.** *"What does 'White' mean in CDE 2192199?"*
   ```json
   { "publicId": "2192199", "value": "White" }
   ```
2. **Check whether a value is out of date.** *"Is the 'Other' value in CDE 2192199 still
   valid in NCIt?"* Read `conceptStatusAtRelease` and `replacement`.
   ```json
   { "publicId": "2192199", "value": "Other" }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `publicId` | Yes | The CDE public ID. |
| `value` | Yes | The allowed value, such as `White`. Case doesn't matter. |
| `version` | No | Default: latest. |
| `release` | No | NCIt release. Default: current. |

**Good to know:** if the value doesn't exist, the error lists the CDE's valid values.

---

## `map_align_value_sets`

**Compare two lists of values, one value at a time.**

Each value is marked `exact`, `synonym`, `retired`, `unmapped` or `ambiguous`, with the evidence
for the decision. The server computes this result.

**Use cases**

1. **Check your values against a CDE.** *"Do 'White', 'Caucasian' and 'Martian' fit CDE
   2192199?"*
   ```json
   {
     "left": { "values": ["White", "Caucasian", "Martian"] },
     "right": { "cde": { "publicId": "2192199" } }
   }
   ```
2. **Compare a CDE with an NCIt value set.** *"How does CDE 2192199 line up with the GDC value
   set C177537?"*
   ```json
   {
     "left": { "cde": { "publicId": "2192199", "version": "1.0" } },
     "right": { "ncitSubset": "C177537" }
   }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `left` | Yes | Exactly one of: `cde` (`{publicId, version?}`), `values` (a list of strings), `gdcEnumDef` (a GDC enum block) or `mdfEnum` (an MDF Enum list). |
| `right` | Yes | Same options as `left`, plus `ncitSubset` (a subset code). |
| `release` | No | NCIt release. Default: current. |

**Good to know:** `result.summary` counts each verdict, and `result.unmatchedRight` lists values
on the right with no partner.

---

## `map_resolve_model_property`

**Check a data model property from start to finish:** read its CDE reference, fetch the CDE,
check its NCIt concepts, and compare the property's values with the CDE's allowed values.

**Use cases**

1. **Check a GDC property.** *"Ground GDC demographic.race."*
   ```json
   { "fragment": { "format": "gdc_json", "content": "<GDC fragment>", "property": "race" } }
   ```
2. **Check every property in an MDF file.** *"Check all properties in my MDF fragment."*
   ```json
   { "fragment": { "format": "mdf_yaml", "content": "<MDF fragment>" } }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `fragment` | Yes | A [model fragment](#model-fragments). |
| `release` | No | NCIt release. Default: current. |

**Good to know:** for each property, `cdeStatus` is `resolved`, `missing_cde_id`,
`cde_not_found`, `cde_superseded` or `skipped`. Up to 50 properties per call.

---

## `map_suggest_cdes_for_term`

**Suggest CDEs for a column name or phrase,** with the reasons for each suggestion.

If a caDSR matching service is configured, the server uses it. Otherwise it finds matching
NCIt concepts, finds CDEs that use them, and ranks them using your sample values. The server
computes this ranking.

**Use cases**

1. **Find a CDE for a column.** *"Which CDE should my 'race' column use?"*
   ```json
   { "term": "race" }
   ```
2. **Use sample values for a better match.** *"My 'race' column contains White and Asian;
   which CDE fits best?"*
   ```json
   { "term": "race", "sampleValues": ["White", "Asian"], "limit": 3 }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `term` | Yes | A column name or phrase. |
| `description` | No | A longer description of the column. |
| `sampleValues` | No | Up to 50 example values. |
| `contexts` | No | Prefer CDEs from these caDSR contexts. |
| `limit` | No | 1–25 suggestions. Default 5. |
| `backend` | No | `cde_match`, `ai_engine` or `native`. Default: a configured matcher, otherwise `native`. |
| `release` | No | NCIt release. Default: current. |

**Good to know:** each suggestion has a `score`, an `evidence` list and the `backend` that
produced it.

---

## `map_validate_model_fragment`

**Check a data model fragment for problems** before you publish it.

It looks for outdated CDE versions, missing or unknown CDEs, invalid or retired NCIt codes, and
values that don't match the CDE. Each finding has a severity (`error`, `warning` or `info`) and
a suggested fix. The server computes these findings.

**Use cases**

1. **Get a report for an MDF fragment.** *"Is my MDF fragment ready?"*
   ```json
   { "fragment": { "format": "mdf_yaml", "content": "<MDF fragment>" } }
   ```
2. **Get just the list of problems.** *"List the problems in my GDC fragment."*
   ```json
   { "fragment": { "format": "gdc_json", "content": "<GDC fragment>" }, "mode": "findings" }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `fragment` | Yes | A [model fragment](#model-fragments). |
| `mode` | No | `report` (default) adds counts and the release; `findings` returns only the list. |
| `release` | No | NCIt release. Default: current. |

---

## `map_assess_release_impact`

**See what changed between two NCIt releases** for a set of concepts, and which CDEs are
affected.

Each concept is marked `retired`, `merged` (with its replacement), `renamed`, `not_in_target`
or `unchanged`.

**Use cases**

1. **Check specific concepts.** *"Did C17649 or C41261 change since 26.09d?"*
   ```json
   { "fromRelease": "26.09d", "conceptCodes": ["C17649", "C41261"] }
   ```
2. **Check everything a CDE uses.** *"Is CDE 2192199 affected by changes since 26.09d?"*
   ```json
   { "fromRelease": "26.09d", "cdePublicId": "2192199", "cdeVersion": "1.0" }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `fromRelease` | Yes | The earlier release. It must still be online. |
| `toRelease` | No | The later release. Default: current. |
| `conceptCodes` | One of these three | Up to 200 NCIt codes. |
| `cdePublicId` (+ `cdeVersion`) | One of these three | Check the concepts a CDE uses. |
| `subset` | One of these three | Check the members of an NCIt subset. |
| `lookupDataElements` | No | `true` (default) lists up to 20 CDEs for each changed concept. |

**Good to know:** EVS keeps only a few releases online, so you can only compare recent releases.
Use [`evs_list_releases`](evs-tools.md#evs_list_releases) to see which.

---

## `map_crosswalk_properties`

**Compare two data model properties,** possibly from different models.

`result.basis` gives the answer: `same_cde`, `same_cde_different_version`, `same_concepts`,
`partial` or `none`. Shared and unique concepts are listed.

**Use cases**

1. **Compare GDC and MDF properties.** *"Do GDC race and my MDF race mean the same thing?"*
   ```json
   {
     "left": { "format": "gdc_json", "content": "<GDC fragment>", "property": "race" },
     "right": { "format": "mdf_yaml", "content": "<MDF fragment>", "property": "race" }
   }
   ```
2. **Check two versions of your own model.** *"Did 'race' keep its meaning between my old
   and new MDF files?"*
   ```json
   {
     "left": { "format": "mdf_yaml", "content": "<old MDF>", "property": "race" },
     "right": { "format": "mdf_yaml", "content": "<new MDF>", "property": "race" }
   }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `left` | Yes | A [model fragment](#model-fragments) for one property. |
| `right` | Yes | A model fragment for the other property. |
| `release` | No | NCIt release. Default: current. |

**Good to know:** each side must resolve to exactly one property. Set `property` when a
fragment contains several.

---

## `map_map_icdo_to_ncit`

**Convert an ICD-O-3 code or term to NCIt concepts.**

The mappings come from EVS's published [ICD-O-3.1 mapping files](https://evs.nci.nih.gov/ftp1/NCI_Thesaurus/Mappings/ICD-O-3_Mappings/About.html):
NCI Metathesaurus mappings of each ICD-O-3.1 code and term to an NCIt concept. The server keeps
a local copy, checks EVS for new versions once a day, and checks each NCIt concept live to
confirm it's still current.

**Use cases**

1. **Convert a morphology code.** *"What NCIt concept is ICD-O 8140/3?"* Returns C2852,
   *Adenocarcinoma*, with the ICD-O term *Adenocarcinoma, NOS*.
   ```json
   { "icdoCode": "8140/3" }
   ```
2. **Convert by name when you have no code.** *"What is the ICD-O code for adenocarcinoma?"*
   ```json
   { "term": "adenocarcinoma" }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `icdoCode` | One of these two | A morphology code (`8140/3`) or topography code (`C34.1`). |
| `term` | One of these two | An ICD-O term or NCIt name, when you have no code. Exact name matches come first; otherwise names containing the term (up to 20). |
| `axis` | No | `auto` (default), `morphology` or `topography`. With `term`, limits results to that kind of code. |
| `includeGroup` | No | Group roll-up needs an ICD-O group table that isn't configured; `group` stays empty. |
| `release` | No | NCIt release used to check each concept's status. Default: current. |

**What you get back:** one entry per ICD-O code and NCIt concept, with the ICD-O term and term
type (`PT` preferred, `SY` synonym, `RT` related, `HT` hierarchy, or the obsolete `OP`, `IS`,
`ORT`), the NCI Metathesaurus CUI (`ncimCui`), `icdoVersions` (`3.1`), `mapRelease` (the date EVS
published the files) and `conceptStatusAtRelease` (`active`, `retired` or `not_found`).

**Good to know**

- One code can map to several concepts. For example, `C34.1` maps to both *Upper Lobe of the
  Lung* and *Lingula of the Lung*.
- The files cover ICD-O-3.1 only. Rows without an NCIt code (for example *Upper lobe,
  bronchus* under `C34.1`) aren't mappings and are left out.
- Provenance cites the EVS file and when this server downloaded it.
- Before the first download completes (or with no access to `evs.nci.nih.gov`), the tool returns
  `capability_unavailable` instead of guessing; see the [runbook](../runbook.md).

---

## `map_resolve_stored_value`

**Find the exact text GDC stores for an NCIt concept,** using EVS's `NCIt_Maps_To_GDC` table.

**Use cases**

1. **Get the GDC value for a diagnosis.** *"What does GDC store for Breast Carcinoma
   (C4872)?"*
   ```json
   { "conceptCode": "C4872" }
   ```
2. **Prepare data for GDC submission.** *"What GDC values does Melanoma (C3224) map to?"*
   ```json
   { "conceptCode": "C3224" }
   ```

**Inputs**

| Input | Required | What to give |
|---|---|---|
| `conceptCode` | Yes | An NCIt code. |
| `commons` | No | Only `gdc` is supported. Default `gdc`. |
| `release` | No | NCIt release. Default: current. |

**Good to know:** a concept can map to several GDC values, such as a name and an ICD-O code.
An empty `values` list means there is no GDC mapping.
