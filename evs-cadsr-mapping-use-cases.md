# Seven use cases for mapping between EVS and caDSR

NCI describes cancer data with two linked resources.  First, the **caDSR** registry holds Common Data
Elements (CDEs): standard questions with defined answers, such as *Race Category Text* (public
ID 2192199). It holds more than 60,000 of them, and every NCI-sponsored clinical trial collects
data with them [^1][^2].  Second, the **NCI Thesaurus (NCIt)**, served by NCI's Enterprise Vocabulary
Services (EVS), supplies the meaning behind each CDE. Data models such as the Genomic Data
Commons (GDC) dictionary then point each of their fields at a CDE, and each allowed value at an
NCIt concept [^3].

A CDE is linked to NCIt at two levels. This is CDE 2192199 as it appears in the project's test
data:

```
CDE 2192199 v1.0  Race Category Text
├── Object class (the thing described):    Person    C25190
├── Property (the attribute collected):    Race      C17049
├── Representation (the kind of value):    Category  C25372
└── Allowed values and their NCIt concepts:
      White → C41261    Asian → C41260    Black or African American → C16352   …
```

The three resources change on different schedules. NCIt publishes every month, caDSR versions
each CDE separately and has no release numbers, and each data commons revises its own
dictionary. Keeping them aligned is the mapping problem.

The EVS MCP server's 11 mapping tools (`map_*`), with the `cadsr_*` and `evs_*` tools, follow
these links in both directions. They check every NCIt code against a pinned NCIt release, and
every answer cites the caDSR public ID and version, the NCIt release, and when the data was
retrieved. Where the server itself computes a verdict, such as an alignment, a ranking or a
list of problems, the answer says so in `meta.exception`. Those results are suggestions, not
official NCI content. The mapping tools are available only in the server's `unified` profile.

**How to read the evidence.** Unlike the EVS use cases, the results below do not come from a
live run. The mapping tools are built and covered by the project's automated tests. Those tests
use test data modelled on the documented caDSR and EVS responses, and some of it is planted on
purpose to exercise a code path. Each example separates real-world facts, which are cited, from
test-data results, which are labelled. The appendix gives the commands to repeat each example
against caDSR stage and live EVS.

| # | Use case | The question it answers | Main tools | Evidence today |
|---|---|---|---|---|
| 1 | Ground a data-model property | What exactly does this field mean, and do its values still match the standard? | `map_resolve_model_property`, `map_resolve_cde_concepts` | Test data; live smoke test written for caDSR stage |
| 2 | Harmonize submitted values | Which of a site's values map cleanly, which need recoding, and which must go back? | `map_align_value_sets`, `map_explain_permissible_value` | Test data |
| 3 | Check a model before release | What will break, or is already out of date, in this model version? | `map_validate_model_fragment` | Test data |
| 4 | Assess the impact of a policy change | Which CDEs, forms and models collect this concept? | `map_find_data_elements_for_concept`, `cadsr_get_forms_for_data_element` | Test data; one open issue |
| 5 | Remediate after an NCIt release | Which CDEs use concepts that were retired or merged this month? | `map_assess_release_impact` | Test data |
| 6 | Crosswalk two data models | Do two fields from two data commons mean the same thing? | `map_crosswalk_properties`, `cadsr_get_crdc_code_map` | Test data |
| 7 | Find a CDE for a new column | Is there already a standard for this field? | `map_suggest_cdes_for_term`, `cadsr_match_data_elements` | Test data |

---

## 1. Ground a data-model property end to end

**The scenario.** A GDC curator, or a bioinformatician joining GDC data with their own, needs
to know exactly what `demographic.race` means and whether its nine allowed values still match
the standard behind it. The GDC dictionary assigns each property a caDSR CDE, and each allowed
value an NCIt concept [3]. For `race` that CDE is 2192199 version 1.0; the Proteomic Data
Commons (PDC) dictionary points `race` at the same CDE [4]. Checking this by hand means opening
the dictionary file, the caDSR browser and the EVS browser, then comparing them by eye.

**How the server handles it.** The user pastes the property's dictionary entry, and one call to
`map_resolve_model_property` does the rest:

| Step | What happens | Tool doing the work |
|---|---|---|
| 1 | Read the CDE reference (`cde_id`, `cde_version`) from the pasted fragment | `map_resolve_model_property` |
| 2 | Fetch CDE 2192199 v1.0 from caDSR | caDSR client |
| 3 | Resolve the CDE's object class, property, representation term and every value meaning against EVS, in one batch call at the pinned release | `map_resolve_cde_concepts` |
| 4 | Compare GDC's allowed values, and their NCIt codes, with the CDE's allowed values | `map_align_value_sets` |

Each property comes back with a status (`resolved`, `missing_cde_id`, `cde_not_found`,
`cde_superseded` or `skipped`). It also gets the CDE header, each NCIt concept with its current
name, status, replacement if retired, and whether caDSR's name for it still agrees with NCIt's,
plus a value-by-value comparison.

**What the tests show (test data).** The server checked 11 NCIt concepts: 3 for the CDE's
meaning and 8 for its allowed values. It did so in 2 upstream requests (one to caDSR, one EVS
batch call), and the answer carries provenance from both. GDC's nine values came back as
7 exact matches, 1 retired and 1 unmapped. The unmapped value, *not allowed to collect*, is a
real GDC and PDC value [4] that the test CDE doesn't list, so a live run will show whether the
current caDSR CDE agrees with GDC. The retired value is planted: the test data marks *Other*
(C17649) as retired in favour of *Unknown* (C17998) to exercise that path. It is not a real
NCIt retirement.

**Why it matters.** NCI's own description of the Cancer Research Data Commons (CRDC) names
"the wide variety of models and ontologies used to describe data" as one of the two biggest
hurdles to finding and using cancer data. Each data commons uses a different model by design,
and clashes in vocabulary hinder cross-commons search [5]. The GDC portal alone serves data on
50,571 cases [6], so a definition mismatch on one demographic field reaches every cohort built
on it.

**For administrators.** Each property gets a citable grounding record: which CDE version,
which NCIt release, checked when. That replaces "the curator looked at it once".

---

## 2. Harmonize submitted values to a standard

**The scenario.** A site submits a race column containing `White`, `caucasian`, `other` and a
test value, `Martian`. Before the data can be loaded, a data manager has to decide which values
map cleanly, which need recoding, and which go back to the site. Today that decision usually
lives in a spreadsheet that nobody else can audit.

**How the server handles it.** `map_align_value_sets` compares the site's list with the CDE's
allowed values, one value at a time. Each value is marked `exact`, `synonym`, `retired`,
`unmapped` or `ambiguous`, and each verdict lists its evidence: a shared NCIt concept, matching
labels, an NCIt synonym, or a retirement with its replacement. The same tool compares any two
value sources: a plain list, a CDE, a GDC enumeration, an MDF enumeration or an NCIt subset.
`map_explain_permissible_value` then shows a reviewer what a standard value means, with its
NCIt definition and synonyms. caDSR's own value-meaning matcher is available through
`cadsr_match_value_meanings`.

**What the tests show (test data).** The four values came back as 2 exact (`White`, matched
to C41261, and `other`), 1 synonym (`caucasian`, recoded to *White* because *Caucasian* is an
NCIt synonym of C41261), and 1 unmapped (`Martian`). The result also lists the 6 CDE values the
site didn't use, and is labelled as server-computed. Asking the server to explain *White*
returns C41261 with its NCI definition and the synonym *Caucasian*. Asking it to explain
*Martian* returns an error that lists the CDE's valid values, rather than a guess.

**Why it matters.** The `caucasian` → `White` recode is a small decision repeated thousands of
times across studies. When each one carries its evidence, a reviewer can check it in seconds
and a later analyst can trust the merged column. A European Commission study put the cost of
research data that isn't findable, interoperable and reusable at no less than €10.2 billion a
year, with time spent searching for usable data among the largest parts [7][8]. NIH's 2023 Data
Management and Sharing Policy encourages CDEs to improve consistency and interoperability
across datasets [9]; mapping submitted values onto them is where that consistency is won or
lost.

**Status and limits.** Synonym matches rely on the synonyms NCIt publishes. Values that could
match more than one allowed value are reported as `ambiguous`, not resolved silently. The tool
never invents a mapping.

**For administrators.** Harmonization decisions become auditable records rather than
spreadsheet edits, and the same check can be rerun on the next submission.

---

## 3. Check a data model before release

**The scenario.** A CRDC data-model team is about to publish a new model version. The Cancer
Data Service (CDS) and the Childhood Cancer Data Initiative (CCDI) describe their models in the
MDF format, and GDC uses its own dictionary. The team wants a pre-flight check that works like
a spell-checker for standards references.

**How the server handles it.** `map_validate_model_fragment` reads a model fragment and reports
each problem with a severity (`error`, `warning` or `info`) and a suggested fix. It looks for
three groups of problems:

- **CDE references:** a property with no CDE, a CDE that doesn't exist, or a CDE version that
  has been superseded.
- **NCIt codes:** a code that isn't valid, or a concept behind the CDE that is retired or
  missing at the pinned release.
- **Allowed values:** a value the CDE doesn't allow, a value whose NCIt code contradicts the
  CDE, a value whose concept was retired, a label that differs from the CDE's, or CDE values
  the model leaves out.

In `report` mode the tool adds counts and the NCIt release. In `findings` mode it returns a flat
list that an automated build job can check.

**What the tests show (test data).** A three-property GDC fragment produced 5 findings: 1 error
and 4 warnings. On `race`, the tool flagged the retired concept behind the CDE, the retired
enumeration value `other` (suggesting C17998 as its replacement), and `not allowed to collect`
as a value the CDE doesn't allow. It flagged `days_to_birth` for having no CDE reference. It
reported `vital_status`'s CDE as not found because the test data leaves that CDE out on
purpose; the real dictionaries point `vital_status` at CDE 5 [4].

**Why it matters.** Models and terminologies keep moving. GDC recently replaced its Gender
property with Sex at Birth throughout its portal [10]. NCIt adds more than 500 concepts every
month [11], and EVS publishes a monthly file of concepts it retired or merged [12]. A stale
reference found after release means corrected submissions, re-indexing and confused users; found
before release, it is a one-line fix. NCI's CRDC authors point to "relatively weak content
controls on incoming descriptive data" as one reason cross-commons harmonization is hard [5].

**For administrators.** A model release gets a repeatable quality gate with an evidence trail,
instead of relying on reviewers to spot stale references.

---

## 4. Assess the impact of a policy change

**The scenario.** In March 2024, OMB revised its federal standard for race and ethnicity data
(SPD 15). The revision requires a single combined race and ethnicity question and adds Middle
Eastern or North African as a minimum category, separate from White [13]. Agencies must submit
action plans by March 28, 2027 and comply by March 28, 2029 [14]. NCI program staff need an
inventory of every CDE, form and data model that collects race the old way.

**How the server handles it.** The search starts from the meaning, not the name:

| Step | Question | Tool |
|---|---|---|
| 1 | Which CDEs are annotated with Race (C17049), optionally including narrower concepts? | `map_find_data_elements_for_concept` |
| 2 | In which of those is Race the attribute being collected, rather than a passing mention? | `cadsr_find_data_elements_by_concept` with `itemType: "Property"` |
| 3 | Which case report forms ask a question using each CDE version? | `cadsr_get_forms_for_data_element` |
| 4 | Which CRDC models use each CDE? | `cadsr_get_crdc_code_map` |
| 5 | Which CDEs offer *White* (C41261) as an allowed value, and so must change when MENA is split out? | `map_find_data_elements_for_concept` with `itemType: "ValueMeaning"` |

Results are grouped by concept. When a search is cut short by its limits (`maxConcepts`), the
answer says so in `truncation` rather than presenting a partial list as complete.

**What the tests show (test data).** C17049 returned 3 CDEs from 3 owning contexts, one of
them superseded. Restricting the search to Race as the property returned 1 CDE (2192199). The
form search found 2 questions on 2 forms that use it. The names differ (*Race Category Text*,
*Person Race Category Text*, *Patient Race Category*), which is why a name search alone would
miss some of them.

**Status and limits.** One behaviour is still an open decision. When asked about a code NCIt no
longer contains, the tool currently returns zero CDEs with a warning instead of a not-found
error; a strict expected-failure test tracks it. Each concept checked is a separate caDSR
request, so wide searches should keep `maxConcepts` small.

**Why it matters.** With more than 60,000 CDEs in caDSR [1], and NCI's standard CDEs embedded
in every NCI clinical trial [2], an inventory built from name searches will be incomplete.
Searching by NCIt concept finds CDEs by what they mean, and the form and model lookups show
where each one is actually used.

**For administrators.** The compliance action plan starts from a cited, repeatable inventory
that can be rerun as remediation progresses.

---

## 5. Remediate after a monthly NCIt release

**The scenario.** Every month NCIt retires some concepts and merges duplicates into survivors,
and EVS publishes the list [12]. CDEs and data dictionaries that use those concepts are now out
of date, but nothing tells their owners. EVS also keeps only a few recent releases online, so a
comparison that isn't done soon can't be done at all.

**How the server handles it.** `map_assess_release_impact` compares two releases that are still
online. It can check a list of up to 200 concepts, all the concepts behind one CDE, or the
members of an NCIt subset. Each concept is marked `retired`, `merged` (with its replacement),
`renamed`, `not_in_target` or `unchanged`, and the tool lists up to 20 CDEs that use each changed
concept. Curators can then use `map_explain_permissible_value` to plan the fix and
`cadsr_get_forms_for_data_element` to find the forms that will inherit it.

**What the tests show (test data).** Checking CDE 2192199 between the previous and current
test releases covered 11 concepts and found 1 change: *Other* (C17649) retired, replaced by
*Unknown* (C17998), with CDE 2192199 listed as affected. As in example 1, this retirement is
planted in the test data. Comparing a release with itself is rejected as an invalid request.
Asking for a release EVS no longer serves, such as 20.01d, returns `release_not_available`
rather than quietly answering from today's data.

**Why it matters.** NCIt adds more than 500 concepts a month and revises many more [11], so
drift between caDSR and NCIt accumulates quietly. Because every answer is tied to a release, a
bioinformatician who reruns an analysis months later with the same release pin gets the same
concept set. A curator who runs this check each month catches retirements while both releases
can still be compared.

**For administrators.** Terminology maintenance becomes a scheduled monthly report with named
owners, instead of problems that surface when a submission fails.

---

## 6. Crosswalk two data models

**The scenario.** A researcher wants to pool race data from a GDC project with a CDS or CCDI
study described in MDF. Both have a field called `race`. The question is whether the two fields
mean the same thing and accept the same answers.

**How the server handles it.** `map_crosswalk_properties` takes one property from each model and
reports a `basis`: `same_cde`, `same_cde_different_version`, `same_concepts`, `partial` or
`none`. It lists the NCIt concepts the two share and those unique to each, and compares their
allowed values. `cadsr_get_crdc_code_map` shows which CRDC models are recorded as using a
CDE.

**What the tests show (test data).** GDC `race` and an MDF `race` came back as `same_cde`,
sharing Race (C17049), Person (C25190) and Category (C25372). Their allowed values overlapped on
only 2 entries, *White* and *Asian*; the MDF list also contained *Caucasian* and *Martian*,
which GDC doesn't allow. Comparing GDC `race` with an unrelated MDF field, `sample_count`,
returned `none`.

**Why it matters.** Pooling data across data commons is the point of the CRDC, which now
includes six data commons, each with its own model [5][15]. Real models do share CDEs: the GDC
and PDC dictionaries both point `race` at CDE 2192199 [4]. But the test result shows why a
shared CDE ID isn't the end of the check. Two models can cite the same CDE and still accept
different values, and pooling them unchecked silently mixes categories. The crosswalk shows the
shared meaning and the value gap in one answer.

**For administrators.** Decisions to pool data rest on documented evidence of equivalence,
rather than on two fields happening to share a name.

---

## 7. Find a CDE for a new column, or show that none exists

**The scenario.** A new study's spreadsheet has a column `Race` with values *White* and
*Asian*. The team should reuse an existing CDE rather than invent a new field, and NIH data
management plans ask which CDEs a project will use [9]. They need to know quickly whether a good
match exists.

**How the server handles it.** `map_suggest_cdes_for_term` takes a column name, an optional
description and sample values, and returns ranked suggestions. Each comes with a score, the
evidence behind it, and the method that produced it. If an operator has configured one of
caDSR's matching services, the server uses it: CDE Match, which is rule-based and needs a caDSR
login, or CDE AI Match, which uses embeddings. Otherwise it uses a native route. It finds NCIt
concepts for the term, finds CDEs annotated with those concepts, and ranks them by how many
sample values each CDE allows. `cadsr_match_data_elements` calls caDSR's matchers directly, and
`cadsr_list_match_backends` shows which are available and why.

**What the tests show (test data).** *Race* with *White* and *Asian* returned CDE 2192199
first, with a score of 1.0. The evidence was that Race is the CDE's property concept and that
2 of 2 sample values are allowed values. The ranking came from the native route and is labelled
as server-computed. The query *quarterly budget variance* returned an empty list: the server
does not make up a CDE when none fits.

**Why it matters.** Reuse is achievable. In a registry case example from the Agency for
Healthcare Research and Quality, 87 of 100 clinical data elements came straight from caDSR,
and the other 13 were created with NCI [16]. Failing to find an existing CDE has a cost too: an
earlier analysis of 11,400 caDSR CDEs found that 1,963 of them (17.2%) shared the same concept
and value-domain pair with another CDE [17]. The NIH CDE Repository holds more than 23,000 CDEs
of its own [18], so the search space is too large to browse.

**Status and limits.** The server is read-only. It suggests candidates; a curator decides, and
registers any new CDE through caDSR's normal process.

**For administrators.** Fewer duplicate CDEs, faster data management plans, and a record of why
each field was chosen.

---

## Reading the evidence

The real-world facts in this document are cited: which CDE each dictionary field points to, the
policy dates, the registry sizes and the published studies. Results labelled *test data* come
from the project's automated tests, which run the real server code against recorded-style
responses from caDSR and EVS. Some of those responses are planted to exercise a code path, most
notably the retirement of *Other* (C17649) and the missing CDE behind `vital_status`. Those are
not facts about NCIt or caDSR. A live run against caDSR stage will replace the test-data
numbers, and real results will change as NCIt and caDSR change, which is why every answer
carries its release, CDE version and retrieval time.

## Appendix: repeat the examples live

Run these from the repository root after `uv sync --frozen --extra dev`. Live caDSR calls must
go to **caDSR stage**: set `ECM_CADSR_BASE_URL=https://cadsrapi-stage.cancer.gov` in `.env`
first, because the default is production. Arguments are passed as JSON so that versions such as
`"1.0"` stay strings.

```bash
t() { uv run --no-sync python scripts/call_tool.py --mode live --profile unified "$@"; }
frag() { python3 -c 'import json,sys; f={"format":"mdf_yaml","content":open(sys.argv[1]).read()}
if len(sys.argv)>2: f["property"]=sys.argv[2]
print(json.dumps({"fragment":f}))' "$@"; }

# 1. Ground a CDE, then a model property
t map_resolve_cde_concepts '{"publicId":"2192199","version":"1.0","includePermissibleValues":true}'
t map_resolve_model_property "$(frag tests/fixtures/map/mdf_participant.yaml race)"

# 2. Harmonize values
t map_align_value_sets '{"left":{"values":["White","caucasian","other","Martian"]},"right":{"cde":{"publicId":"2192199","version":"1.0"}}}'
t map_explain_permissible_value '{"publicId":"2192199","value":"White"}'

# 3. Check a model fragment
t map_validate_model_fragment "$(frag tests/fixtures/map/mdf_participant.yaml)"

# 4. Policy impact
t map_find_data_elements_for_concept '{"conceptCode":"C17049"}'
t cadsr_find_data_elements_by_concept '{"conceptCode":"C17049","itemType":"Property"}'
t cadsr_get_forms_for_data_element '{"publicId":"2192199","version":"1.0"}'

# 5. Release remediation (pick fromRelease from: t evs_list_releases '{}')
t map_assess_release_impact '{"fromRelease":"<earlier live release>","cdePublicId":"2192199","cdeVersion":"1.0"}'

# 6. Crosswalk: which CRDC models record this CDE
t cadsr_get_crdc_code_map '{"dataElementId":"2192199"}'

# 7. Suggest a CDE
t map_suggest_cdes_for_term '{"term":"race","sampleValues":["White","Asian"]}'
```

The `t` and `frag` helpers work in both zsh and bash. `frag` wraps an MDF file from the test
data as a model fragment; point it at your own model file to check that instead.

## Sources

1. CEDAR, *CEDAR Offers Support for CDEs from caDSR* (more than 60,000 caDSR CDEs): https://metadatacenter.org/happenings/news/cedar-offers-cde-support/
2. NCI CBIIT, *Data Elements for Cancer Research* (all NCI-sponsored trials rely on caDSR CDEs; CDEs annotated with NCIt concepts): https://www.cancer.gov/about-nci/organization/cbiit/data-standards/data-elements-for-cancer-research
3. GDC Docs, *GDC Data Dictionary* (each property is assigned a caDSR CDE; NCIt concepts at the permissible-value level): https://docs.gdc.cancer.gov/Data_Dictionary/
4. Proteomic Data Commons, `demographic.yaml` data dictionary (race: CDE 2192199 v1.0, including *not allowed to collect*; vital_status: CDE 5): https://proteomic.datacommons.cancer.gov/data-dictionary/yaml/demographic.yaml
5. *NCI Cancer Research Data Commons: Core Standards and Services.* Cancer Research (AACR). https://doi.org/10.1158/0008-5472.CAN-23-2655
6. GDC Data Portal home page (50,571 cases): https://portal.gdc.cancer.gov/
7. PwC for the European Commission, *Cost of not having FAIR research data* (2018; at least €10.2 billion per year): https://publications.europa.eu/resource/cellar/d375368c-1a0a-11e9-8d04-01aa75ed71a1.0001.01/DOC_1
8. California Life Sciences, *FAIR Data Principles, Explained for Life Sciences Startups* (summary of the cost components in [7]): https://www.califesciences.org/insights/fair-data-principles-life-sciences/
9. NLM, *NLM and Common Data Elements* (NIH Data Management and Sharing Policy encourages CDEs): https://www.nlm.nih.gov/oet/ed/cde/tutorial/04-100.html
10. GDC Docs, *Data Portal Release Notes* (Gender replaced with Sex at Birth): https://docs.gdc.cancer.gov/Data_Portal/Release_Notes/Data_Portal_Release_Notes/
11. NCI EVS Wiki, *EVS Resources* (more than 500 NCIt concepts added each month): https://wiki.nci.nih.gov/spaces/EVS/pages/50694975/EVS+Resources
12. NCI EVS, *Monthly NCIt Retires & Merges*: https://evs.nci.nih.gov/ftp1/NCI_Thesaurus/Monthly_RetiresMerges/About.html
13. Federal Register, *Revisions to OMB's Statistical Policy Directive No. 15* (March 29, 2024): https://www.federalregister.gov/documents/2024/03/29/2024-06469/revisions-to-ombs-statistical-policy-directive-no-15-standards-for-maintaining-collecting-and
14. Congressional Research Service, *Revisions to Statistical Policy Directive No. 15* (IN12304; action plans by March 28, 2027, compliance by March 28, 2029): https://www.congress.gov/crs-product/IN12304
15. *NCI Cancer Research Data Commons: Resources to Share Key Cancer Data.* Cancer Research 2024;84(9):1388. https://aacrjournals.org/cancerres/article/84/9/1388/745077/NCI-Cancer-Research-Data-Commons-Resources-to
16. AHRQ, *Registries for Evaluating Patient Outcomes*, Chapter 4, Case Example 7 (87 of 100 data elements from caDSR): https://www.ncbi.nlm.nih.gov/books/NBK208639/
17. *The Common Data Elements for Cancer Research: Remarks on Functions and Structure* (1,963 of 11,400 CDEs with a non-unique concept and value-domain pair): https://pmc.ncbi.nlm.nih.gov/articles/PMC2980785/
18. *Common Data Elements Repository* (more than 23,000 CDEs and 1,700 forms in the NIH CDE Repository): https://pmc.ncbi.nlm.nih.gov/articles/PMC11095837/
