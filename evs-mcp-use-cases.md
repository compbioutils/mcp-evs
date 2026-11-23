# Four use cases for the EVS MCP server

The EVS MCP server lets an AI assistant look up the NCI Thesaurus (NCIt) and the vocabularies
NCI's Enterprise Vocabulary Services (EVS) publishes, instead of answering from memory. NCIt is
NCI's reference terminology: about 178,000 concepts, with more than 500 new ones added each
month [1][2]. It is the shared language behind NCI data commons, cancer registries, CDISC
regulatory submissions and many clinical systems.

Every answer from the server names the NCIt release it came from and the EVS address that
supplied it. That makes the result checkable by a reviewer and repeatable months later. The
server is read-only: it never changes source data, and when it can't answer it says so rather
than guessing.

The four use cases below were run against live EVS (NCIt release 26.10d, November 2026).
Each one pairs that live evidence with published figures that show why the problem matters.

| # | Use case | What it does | Status | Live evidence |
|---|---|---|---|---|
| 1 | Cohort and eligibility expansion | Disease term → NCIt concept → all subtypes, with exclusions kept apart | Runs | Ewing sarcoma (C4817) has 30 subtypes within 3 levels |
| 2 | Standards value sets (CDISC) | Codelist → NCIt subset → members with submission values | Runs | SDTM Sex codelist C66731 returns 4 members; Female carries F and FEMALE |
| 3 | Cross-terminology coding | ICD-O-3, ICD-10-CM or GDC code → NCIt → other mapped codes | Runs, with workarounds | ICD-O-3 8140/3 → C2852; 23 ICD-10-CM mappings for melanoma; MedDRA withheld without a license key |
| 4 | Grounded terminology Q&A | Plain-language question → concept → cited definition, hierarchy, relationships | Runs for names and synonyms | "NSCLC" → C2926, with definition and 16 paths to the root |

---

## 1. Cohort and eligibility expansion

**The scenario.** A pediatric oncology team wants every patient with Ewing sarcoma in a data
commons, whether for a trial feasibility count or a research cohort. Records are coded at many
levels of detail. One says "Ewing sarcoma", another "Extraskeletal Ewing Sarcoma", another
names a specific bone site. A search for the exact phrase finds only the first kind.

**How the server handles it.** The assistant resolves "Ewing sarcoma" to NCIt C4817
(`evs_lookup_concept`). It then walks the hierarchy below it within set limits (`evs_traverse`
or `evs_get_descendants`) and returns the full list of codes to query. Exclusion relationships,
such as a disease that rules out a finding, are reported separately and not followed
automatically, so the cohort isn't silently widened. The list names the NCIt release, so the
same query gives the same cohort when it's audited later.

**Why it matters.** In the live run, C4817 had 30 subtypes within three levels, so an exact
match finds 1 of 31 relevant concepts. The CCDI example in the project goals deck shows what
that costs: expanding from the exact term to the subtype list raised the patients found from
20 to 50, a 2.5-fold increase. For rare diseases, that difference can decide whether a study
is feasible. Childhood cancers are only 1–3% of US cancer diagnoses, and NCI invests
$50 million a year in the Childhood Cancer Data Initiative to collect and share these
patients' data [3]. Recruitment is already the main bottleneck in oncology research: about 20% of
adult cancer trials fail to complete because they can't enroll enough patients [4]. A
meta-analysis found that only 8.1% of cancer patients enroll in a trial, and that a further
21.5% are ineligible for a trial that is available to them [5]. Better term expansion doesn't change eligibility rules. It
makes sure that patients who do qualify aren't missed because of how their diagnosis was
recorded.

**For administrators.** Feasibility counts and cohort definitions become reproducible,
reviewable artifacts instead of one analyst's search string.

---

## 2. Standards value sets (CDISC)

**The scenario.** A clinical data programmer is building SDTM datasets for an FDA submission
and needs the exact permitted values for the Sex variable, plus the values each one must be
submitted as.

**How the server handles it.** CDISC Controlled Terminology is maintained by NCI EVS and
published as NCIt subsets [6]. The assistant looks up the codelist (`evs_list_subsets` with
C66731, *CDISC SDTM Sex of Individual Terminology*) and lists its members
(`evs_get_subset_members`). Each member comes back with its NCIt code, its definition and its
CDISC submission values, all tied to a release.

**Why it matters.** In the live run, C66731 returned 4 members, and Female carried the
submission values F and FEMALE. Getting that distinction wrong is not cosmetic. CDISC
submission values are a required part of a conformant dataset for both FDA and Japan's PMDA
[7]. For clinical studies started after December 17, 2016 (NDAs, BLAs and ANDAs), or after
December 17, 2017 for commercial INDs, FDA can reject a submission whose study data don't
conform to the required standards [8]. CDISC terminology is revised every quarter; the latest
release is dated 25 September 2026 [6]. EVS maintains more than 550 subsets like this one [2].
A tool that reads the current list, rather than a spreadsheet copied two quarters ago, removes
a common source of validation findings.

**For administrators.** Less rework before submission, fewer surprises at validation, and a
release-stamped record of which terminology version each dataset used.

---

## 3. Cross-terminology coding

**The scenario.** A cancer registry codes tumors in ICD-O-3, the hospital bills in ICD-10-CM,
the Genomic Data Commons (GDC) uses its own values, and research models use NCIt. A data
manager linking these sources needs to know that they describe the same disease.

**How the server handles it.** NCIt acts as the hub. The assistant converts an ICD-O-3 code to
NCIt (`map_map_icdo_to_ncit`), then reads the concept's mappings to other systems
(`evs_get_concept_maps`, `evs_get_mapset_entries`). Every mapping comes from an EVS-published
mapping table, not from the model. Content that needs a license is listed as withheld instead
of silently disappearing.

**Why it matters.** In the live run, ICD-O-3 8140/3 (*Adenocarcinoma, NOS*) mapped to NCIt
C2852, and melanoma returned 23 ICD-10-CM mappings. The ICD-O-3 table behind this has 3,669
mappings covering 1,545 ICD-O codes and 1,747 NCIt concepts. MedDRA mappings were withheld,
correctly: MedDRA is licensed for NCI's own work, and other use needs a separate subscription
[9]. The scale makes manual crosswalks expensive. About 2.1 million new US cancer cases are
projected for 2026 [10]. Registries code each case's histology and behavior in ICD-O-3.2, as
SEER's coding manual requires [11], while billing and research systems use other codes for the
same tumor.

**Status and workarounds.** Two workarounds apply today. EVS's search by ICD-O-3 code doesn't
reliably find the matching concepts, so the server uses EVS's published ICD-O-3.1 mapping
files, which it downloads and re-checks for new versions daily. It checks each concept live. The
ICD-O tool is part of the server's mapping module, so it needs the `unified` profile. MedDRA
content needs a license key configured by the operator.

**For administrators.** Mappings are traceable to a published source, and license limits are
enforced and visible rather than worked around.

---

## 4. Grounded terminology Q&A

**The scenario.** A clinician, scientist or analyst asks a plain question: *"What exactly is
NSCLC, and where does it sit in the disease hierarchy?"*

**How the server handles it.** The assistant resolves the abbreviation to a concept
(`evs_lookup_concept` → C2926, *Lung Non-Small Cell Carcinoma*). It then retrieves the
definition (`evs_get_concept`), its paths to the top of NCIt (`evs_get_paths`) and its
relationships to other concepts (`evs_get_relationships`). The answer is assembled from those
results and cites the NCIt release and source address, so a reader can check every statement.

**Why it matters.** In the live run, "NSCLC" resolved to C2926 with its NCI definition and
16 distinct paths to the root. That count matters because NCIt lets a concept sit under
several parents, so NSCLC rolls up under more than one branch at once. This is also why
reporting categories depend on the hierarchy. Without grounding, language models are
unreliable with codes. In a 2024 NEJM AI benchmark, the best model tested (GPT-4) produced the
exact correct ICD-10-CM code only 33.9% of the time, and its ICD-9-CM and CPT accuracy was also
below 50% [12]. A follow-up preprint gave a model a lookup tool instead, and it matched all 100
codes in its (small) test sample [13]. Grounding answers in the source terminology is the
difference between a plausible answer and a correct one.

**Status and limits.** Lookups work for names, synonyms and abbreviations. Meaning-based search
isn't built yet, so a description such as "cancer that starts in the plasma cells of bone
marrow" won't find Multiple Myeloma (C3242). That index is planned for a later phase and needs
an NCI decision on the embedding model.

**For administrators.** Staff get fast answers they can cite, and the release stamp shows
exactly which version of NCIt an answer reflects.

---

## Reading the evidence

The live results come from this server against live EVS. The CCDI patient counts (20 to 50)
come from the project goals deck, not from a new run. The published figures describe the size
of each problem in general; they are not measurements of this server. Live results will change
as NCIt changes each month, which is why every answer carries its release.

## Sources

1. NCI EVS Wiki, *Shared Terminology Development* (178,080 current NCIt concepts, release 26.08e): https://wiki.nci.nih.gov/spaces/EVS/pages/50235286/Shared+Terminology+Development
2. NCI EVS Wiki, *EVS Resources* (more than 500 concepts added monthly) and NCI EVS home page (more than 550 subsets): https://wiki.nci.nih.gov/spaces/EVS/pages/50694975/EVS+Resources, https://evs.nci.nih.gov/
3. NCI, *About the Childhood Cancer Data Initiative*: https://www.cancer.gov/research/areas/childhood/childhood-cancer-data-initiative/about
4. Stensland KD et al. *Adult Cancer Clinical Trials That Fail to Complete: An Epidemic?* JNCI 2014;106(9):dju229. https://doi.org/10.1093/jnci/dju229 (figure as summarized in https://pmc.ncbi.nlm.nih.gov/articles/PMC8573122/)
5. Unger JM et al. *Systematic Review and Meta-Analysis of the Magnitude of Structural, Clinical, and Physician and Patient Barriers to Cancer Clinical Trial Participation.* JNCI 2019;111(3):245–255. https://pmc.ncbi.nlm.nih.gov/articles/PMC6410951/
6. CDISC, *Controlled Terminology*: https://www.cdisc.org/standards/terminology/controlled-terminology
7. CDISC, *Controlled Terminology: FAQs*: https://www.cdisc.org/kb/articles/controlled-terminology-faqs
8. FDA, *Technical Rejection Criteria for Study Data*: https://www.fda.gov/files/drugs/published/Technical-Rejection-Criteria-for-Study-Data.pdf
9. NCI EVS Explore, *MedDRA* (license terms): https://evsexplore.semantics.cancer.gov/evsexplore/welcome?terminology=mdr
10. Siegel RL et al. *Cancer statistics, 2026.* CA Cancer J Clin 2026;76(1):e70043. https://acsjournals.onlinelibrary.wiley.com/doi/10.3322/caac.70043
11. NCI SEER, *SEER Program Coding and Staging Manual 2026*: https://seer.cancer.gov/manuals/2026/SPCSM_2026_MainDoc.pdf
12. Soroush A et al. *Large Language Models Are Poor Medical Coders — Benchmarking of Medical Code Querying.* NEJM AI 2024;1(5). https://ai.nejm.org/doi/full/10.1056/AIdbp2300040
13. *Large Language Models are good medical coders, if provided with tools* (preprint, 100-code sample). arXiv:2407.12849. https://arxiv.org/html/2407.12849v1
