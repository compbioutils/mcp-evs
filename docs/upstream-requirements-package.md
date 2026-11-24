# Upstream EVS API requirements package (SOW D7)

Prioritised, evidence-backed requirements for the EVS REST API (and, for completeness, the
caDSR II APIs the unified profile depends on), consolidated from the upstream-gap register
(proposal Appendix B) and from building this server. Implementation of upstream changes is
out of scope for the contractor; this package is for NCI ownership and roadmap disposition.

Status legend: **verified** = reproduced against the live API on the date given; **documented**
= stated in EVS/caDSR documentation and relied upon by the design, reproduction pending the
first live fixture recording (`scripts/record_fixtures.py`).

Priority: P1 blocks a SOW capability or forces an approved fallback; P2 costs correctness or
efficiency with a workaround; P3 quality of life.

---

## EVS-1 (P1) — Only the three most recent NCIt releases are served live

**Status:** verified 2026-10-29 (proposal 2.1).
**Reproduction:** `GET /api/v1/metadata/terminologies?terminology=ncit` lists three versions;
`GET /api/v1/concept/ncit_25.01d/C3224` → 404.
**Affected scenarios:** release-pinned retrieval older than ~3 months (UC-5 release impact,
curator remediation, reproducibility of citations).
**Expected behaviour:** a documented retention policy and, ideally, read access to at least
the releases of the last 12 months, or a stable archive endpoint.
**Impact:** citations with a release older than the window cannot be re-resolved; the server
returns `release_not_available`.
**Workaround:** the NCIt index retains several releases locally (Phase 3); `map_assess_release_impact`
only compares live releases.
**Proposed acceptance criteria:** `/metadata/terminologies` returns a `retention` field; a
pinned request for any release within the stated retention succeeds.

## EVS-2 (P1) — `search` filters by property value but not by role or association

**Status:** verified (proposal 2.1, Appendix B `evs-role-search`).
**Reproduction:** `GET /concept/ncit/search?property=Disease_Has_Primary_Anatomic_Site&value=C12470`
does not restrict to concepts holding that role; role targets are only reachable through
`/{code}/inverseRoles`, `/concept/ncit/associations/{label}`, or SPARQL.
**Affected scenarios:** SOW-T5 concept sets by role/association criteria; combinations of two
property values under AND.
**Expected behaviour:** search parameters `role=<name>&target=<code>` (and `association=`),
combinable with `property`/`value`/`subset`, with pagination.
**Impact:** the server's planner (`evs_find_concepts`) materialises inverse-role lists and
intersects in memory; two property values under AND require the SPARQL fallback, which needs
NCI approval.
**Workaround:** planner routes + `capability_unavailable` with `plan.path = sparql_required`.
**Acceptance criteria:** one paged search call returns the concept set for role+target, and for
property+property combinations, with `total`.

## EVS-3 (P2) — No ancestors endpoint; ancestry only via `pathsToRoot`

**Status:** documented.
**Reproduction:** no `/concept/{t}/{code}/ancestors`; `/pathsToRoot` returns all paths (large
for deep concepts).
**Affected scenarios:** hierarchy roll-up, ICD-O group roll-up, cohort expansion.
**Expected:** `/ancestors?maxLevel=` flat and paged like `/descendants`.
**Impact:** payload size and client-side de-duplication of path nodes.
**Workaround:** `evs_get_paths` plus de-duplication in the client.
**Acceptance criteria:** flat ancestor list with `level`, paged, same release semantics.

## EVS-4 (P2) — No machine-readable relationship polarity

**Status:** documented (Appendix B `evs-polarity`).
**Reproduction:** `/metadata/ncit/roles` lists `Disease_Excludes_Finding` with no attribute
distinguishing it from `Disease_Has_Finding`.
**Affected scenarios:** SOW-T3 exclusion semantics in traversal.
**Expected:** a `polarity` (or `negative: true`) attribute on role metadata.
**Impact:** the negative-role set is configured at deployment (`DEFAULT_NEGATIVE_ROLES`) and
must be reviewed on every release that adds roles.
**Workaround:** configured list; new `*_Excludes_*` roles are caught by review, not by data.
**Acceptance criteria:** role metadata carries polarity; traversal tests read it instead of the list.

## EVS-5 (P2) — Conflicting or missing release metadata on some payloads

**Status:** to verify at first recording (the server fails closed on mismatch).
**Reproduction:** compare the `version` field of batch `?list=` items, `/subset/{t}/{code}/members`
items and `/pathsToRoot` nodes against the path's `terminologyVersion`.
**Affected scenarios:** SOW-S11 release identity structurally required.
**Expected:** every concept-bearing payload carries `terminology` and `version` consistently.
**Impact:** where absent, the server stamps the pinned release from the request path; where
different, it returns `release_mismatch`.
**Acceptance criteria:** the release-consistency test (T-REL) passes against live for all
endpoints used by the tool catalogue without stamping.

## EVS-6 (P2) — License text only at terminology level; mapset license basis not exposed

**Status:** documented (Appendix B `evs-license-text`).
**Reproduction:** `/metadata/terminologies` carries `licenseText` per terminology; `/mapset/{code}`
properties do not state whether target codes may be returned without a key.
**Affected scenarios:** SOW-T8 cross-maps with license gate; architecture-review decision
"license-gate behaviour for map target codes".
**Expected:** mapset metadata states the license basis of target content and whether codes
alone are redistributable.
**Impact:** the server withholds all gated assertions (count only) pending NCI decision.
**Acceptance criteria:** mapset property `targetLicense: open|codes_only|key_required`.

## EVS-7 (P3) — Batch endpoint practical limit is URL length, not the documented 1000

**Status:** documented (proposal 2.1).
**Reproduction:** `GET /concept/ncit?list=<700 codes>` fails before the documented 1000-code cap.
**Expected:** `POST` form of the batch endpoint, or a documented URL-length limit.
**Impact:** the server chunks at 500 codes.
**Acceptance criteria:** documented limit or POST body support.

## EVS-8 (P3) — `/concept/{t}/associations/{label}` excludes subset associations and lacks a total on some pages

**Status:** to verify.
**Expected:** consistent `total` and an option to include `Concept_In_Subset`.
**Workaround:** subset membership via `/subset/.../members`.

## EVS-9 (P2) — Subset tree and subset lookup have no release-pinned form

**Status:** verified live 2026-11-19 (NCIt 26.10d).
**Reproduction:** `GET /subset/ncit_26.10d` returns `[]` and `GET /subset/ncit_26.10d/C66731`
returns 404, while `GET /subset/ncit` and `GET /subset/ncit/C66731` return the content at
26.10d. `/subset/ncit_26.10d/{code}/members` does accept the pinned form.
**Affected scenarios:** SOW-T6 subset discovery; SOW-S11 release identity.
**Expected:** `/subset/{terminology}_{version}` and `/subset/{terminology}_{version}/{code}`
serve the requested live release, as the concept and member endpoints do.
**Impact:** `evs_list_subsets` calls the unpinned path and checks every returned subset's
`version`; any release other than the one EVS currently serves there fails with
`release_mismatch`.
**Acceptance criteria:** the pinned paths return the same content as the unpinned path for
the current release, and the matching content for every other live release.

---

## caDSR (unified profile dependencies; for the companion workstream's disposition)

| id | priority | gap | impact on this server | workaround |
|---|---|---|---|---|
| CADSR-1 | P1 | no keyword search over CDEs | `cadsr_find_data_elements` is a declared fan-out that cannot claim completeness | fan-out with `coverage` record |
| CADSR-2 | P1 | no pagination on list endpoints; a CDE is 6–10 s and 100–400 KB | server-side paging over a cached payload; first call slow | two-tier cache keyed by publicId+version |
| CADSR-3 | P2 | errors as HTTP 200 with `apiResponse.type = "E"` | retries must not trigger; mapping by message text | message-pattern mapping to `not_found` / `invalid_request` |
| CADSR-4 | P2 | field-name drift (`publicID`, `latesetVersionIndicator`, "Superceded") | normaliser must tolerate variants | `pick()` / `norm_status()` |
| CADSR-5 | P2 | no value-domain / DEC / value-meaning / PV-by-id endpoints | derived views only | derive from the expanded CDE |
| CADSR-6 | P2 | no registry release identity | items pinned by publicId + version + retrievedAt; no snapshot semantics | `cadsr_get_registry_status` reports `published: false` |
| CADSR-7 | P3 | forms-by-CDE only through the legacy query DSL | one undocumented route in production | `cadsr_get_forms_for_data_element` labelled as legacy |
| CADSR-8 | P3 | CDE AI Match API enforces no authentication and publishes no provenance | internal upstream only; server adds provenance | allow-list + `provenance.attribution` |

## Maintenance

Each item is re-verified when fixtures are recorded (`scripts/record_fixtures.py`, both
modes) and after every monthly NCIt release; verified items gain a date, and the reproduction
request/response pair is kept under `tests/fixtures/` as evidence. New gaps found during
operation are added here and to the upstream-gap register in the proposal.
