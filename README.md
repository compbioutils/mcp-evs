# evs-cadsr-mcp 

<!-- mcp-name: io.github.compbioutils/evs-cadsr-mcp -->

An MCP server over NCI EVS (NCI Thesaurus) and caDSR, built with
[FastMCP](https://github.com/jlowin/fastmcp) and hosted in FastAPI. It implements all three
increments of [`docs/evs-cadsr-mcp-proposal.md`](docs/evs-cadsr-mcp-proposal.md) except the
local NCIt retrieval index: the shared `core` platform (envelopes, release resolver, cache,
resilient HTTP client, budgets, cursors), twenty-one read-only `evs_*` tools over the live
EVS REST API, sixteen `cadsr_*` tools over the caDSR II APIs, and eleven `map_*` tools that
compose the two for the primary use case, mapping between CDE content and NCIt concepts
starting with the GDC data dictionary (Phases 0–2, 4 and 5 of the delivery plan).

**New here?** [QUICKSTART.md](QUICKSTART.md) gets you from clone to asking NCIt questions in
VS Code, Claude Code or Claude Desktop in about five minutes.
Working with a coding agent? [AGENTS.md](AGENTS.md) holds the repo rules, and
[.github/skills/](.github/skills/) the add-a-tool and live-test workflows.

## Layout

```
src/evs_cadsr_mcp/
  core/     config.py envelopes.py errors.py release.py cache.py shared_cache.py http_client.py budget.py cursor.py
            context.py toolkit.py auth.py ratelimit.py audit.py metrics.py
  evs/      client.py models.py content.py service.py traversal.py find_concepts.py tools/
  cadsr/    client.py models.py normalise.py search.py service.py tools/
  map/      capability.py models.py resolve.py align.py analysis.py icdo_map.py icdo_sync.py service.py tools/ fragments/
            (each tools/ package: one module per tool, _args.py, resources.py, prompts.py, __init__.py)
  server/   mcp_app.py (FastMCP + wiring)  middleware.py (platform chain)  app.py (FastAPI host)  cli.py
deploy/     Dockerfile docker-compose.yml cdk/ (AWS reference stack)
docs/       deployment.md runbook.md change-control.md user-guide.md traceability.md
            retrieval-evaluation-protocol.md upstream-requirements-package.md acceptance-report-template.md
eval/       ncit-retrieval-eval-v1.jsonl (SOW-D5 evaluation set, pending SME validation)
spec/       interface-baseline/v1.0/ (SOW-S16 contract: generated schemas + authored transport/security contract)
tests/      unit/ contract/ conformance/ live/ fixtures/evs/
scripts/    record_fixtures.py
```

`service.py` holds transport-independent handlers; the `tools/` modules only validate arguments,
wraps each call in an `Envelope`, and converts domain errors into MCP tool errors whose
message is a JSON error envelope with a closed `code` set.

## Install and run

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/) (pip works too). The repo-root
[`.mcp.json`](.mcp.json) registers the stdio server for VS Code (Copilot) and Claude Code.

```bash
uv venv && source .venv/bin/activate
uv pip install -e '.[dev]'

# stdio, for Claude Desktop / IDE clients
evs-cadsr-mcp serve --transport stdio

# Streamable HTTP inside FastAPI: MCP at http://127.0.0.1:8000/mcp, plus /healthz and /readyz
evs-cadsr-mcp serve --transport http --port 8000

# quick checks
evs-cadsr-mcp tools      # tool catalog
evs-cadsr-mcp releases   # live NCIt releases and the active one
```

Claude Desktop entry (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "evs": { "command": "/path/to/repo/.venv/bin/evs-cadsr-mcp", "args": ["serve", "--transport", "stdio"] }
  }
}
```

Configuration is environment-driven with the `ECM_` prefix (see `.env.example` and
`core/config.py`): `ECM_PROFILE`, `ECM_EVS_BASE_URL`, `ECM_RELEASE_PIN`,
`ECM_BUDGET_MAX_REQUESTS`, `ECM_LICENSE_KEY`, `ECM_LICENSE_GATED_TERMINOLOGIES`, cache TTLs,
timeouts and retry counts.

### Checking the server without an agent

`scripts/check_server.py` runs the simplest use case from the spec (UC-11 term resolution:
"non-small cell lung carcinoma" → C2926, the synonym "NSCLC" → C2926, its paths to root, and a
negative control) through the MCP client, the same way an agent would. `scripts/call_tool.py`
calls any single tool. Both default to spawning the server over stdio; `--mode fixtures` runs
offline over the test fakes, `--mode live` in-process against EVS, `--mode http --url ...`
against a running server.

```bash
python scripts/check_server.py                       # exit 0 = server works
python scripts/check_server.py --mode fixtures -v    # offline, prints each envelope
python scripts/call_tool.py --list
python scripts/call_tool.py evs_lookup_concept identifier=NSCLC
```

If the check passes and an agent run fails, look at the client side; if it fails, fix the server first.

## Tools

For a plain-language guide to every tool, with two simple examples each, see
[`docs/tools/`](docs/tools/README.md).

| Tool | Purpose |
|---|---|
| `evs_list_terminologies`, `evs_list_releases` | discovery; the only tools that run without a release context |
| `evs_get_terminology_metadata` | roles, associations, properties, qualifiers, term types, sources, statuses |
| `evs_get_concept`, `evs_get_concepts` | one concept; many concepts via the batch `?list=` endpoint (no fan-out) |
| `evs_lookup_concept` | exact code, preferred name or synonym with `matchKind` |
| `evs_search_concepts`, `evs_suggest_concepts` | upstream full-text with EVS filters, paged by cursor; typeahead |
| `evs_get_hierarchy_neighbors`, `evs_get_descendants`, `evs_get_paths` | parents/children/roots; flat paged descendants; paths to/from root or to an ancestor |
| `evs_get_relationships` | roles, associations, inverses, disjointness, with `polarity` for exclusion roles |
| `evs_list_subsets`, `evs_get_subset_members` | value sets and paged members |
| `evs_get_concept_maps`, `evs_list_mapsets`, `evs_get_mapset_entries` | cross-maps with a license gate for key-gated targets (MedDRA by default) |
| `evs_get_concept_history` | history events and replacements for retired codes |
| `evs_traverse` | bounded multi-hop walk over hierarchy, roles and associations with an explicit budget, fair scheduling across kinds, exclusion polarity, and per-hop provenance |
| `evs_get_subtree` | depth-capped sub-tree with nodes flagged (or pruned) against property / status / semantic-type criteria |
| `evs_find_concepts` | concept sets by criteria; a planner picks native routes (search, inverse roles/associations, terminology-wide associations, subset members) and reports `plan.path` |

### caDSR tools (profiles `cadsr-only` and `unified`)

| Tool | Purpose |
|---|---|
| `cadsr_get_data_element`, `cadsr_get_data_elements` | a CDE with NCIt concept annotations by role (object class, property, representation term, value meanings); up to 20 CDEs, one upstream call each (no batch endpoint) |
| `cadsr_get_data_element_versions` | version lineage |
| `cadsr_get_permissible_values`, `cadsr_get_value_domain`, `cadsr_get_data_element_concept` | derived views from the one cached expanded CDE; PVs paged server-side |
| `cadsr_find_data_elements_by_concept` | native NCIt → CDE reverse lookup (`DataElements/Concept`), paged, with role filter |
| `cadsr_find_data_elements` | declared fan-out over alternate name, question text, classification, context, with a `coverage` record |
| `cadsr_get_form`, `cadsr_get_forms_for_data_element` | Form API 2.0; forms-by-CDE via the legacy query DSL (the only route) |
| `cadsr_list_contexts` | LOV API (requires `ECM_CADSR_USERNAME` + `ECM_CADSR_PASSWORD`, or `ECM_CADSR_CREDENTIAL`) |
| `cadsr_list_match_backends`, `cadsr_match_data_elements`, `cadsr_match_value_meanings` | CDE Match 2.0 (credentialed), CDE AI Match API (if configured), VM Match; candidates are resolved against NCI API 1.0 before being cited |
| `cadsr_get_crdc_code_map`, `cadsr_get_registry_status` | CRDC harmonized CDE list; registry state (`published: false`, export date if a listing is configured) |

Resources: `cadsr://data-element/{publicId}`, `cadsr://data-element/{publicId}/{version}`,
`cadsr://crosswalk/crdc`. Prompts: `find_cde_for_question`, `map_columns_to_cdes`.

### Mapping tools (profile `unified`)

| Tool | Purpose |
|---|---|
| `map_resolve_cde_concepts` | CDE → NCIt at a pinned release: every annotation's name, status (active / retired / not_found), replacement, name agreement |
| `map_find_data_elements_for_concept` | NCIt → CDEs grouped by concept, optional bounded descendant expansion |
| `map_explain_permissible_value` | PV → value meaning → NCIt concept, definition, synonyms, status |
| `map_align_value_sets` | value-by-value alignment (exact / synonym / retired / unmapped / ambiguous) between CDE PVs, plain values, GDC `enumDef`, MDF enums and NCIt subsets, with evidence |
| `map_resolve_model_property` | GDC JSON/YAML or MDF YAML fragment → CDE → NCIt → enum/PV alignment (UC-1) |
| `map_suggest_cdes_for_term` | candidate CDEs with an evidence chain; caDSR matcher when configured, else term → concepts → annotated CDEs → PV overlap (UC-2) |
| `map_validate_model_fragment` | lint: stale/missing/unknown CDEs, invalid or retired NCIt codes at the release, enum/PV mismatches (UC-8) |
| `map_assess_release_impact` | retired / merged / renamed / missing concepts between two live releases and the CDEs they touch (UC-5) |
| `map_crosswalk_properties` | same CDE / same concepts / partial / none between two model properties (UC-6) |
| `map_map_icdo_to_ncit` | ICD-O-3 code or term → NCIt from EVS's ICD-O-3.1 mapping files (downloaded to a local cache and re-checked daily; `evs-cadsr-mcp icdo sync`), with concept status checked live (UC-9; group roll-up needs the ICD-O group table) |
| `map_resolve_stored_value` | the GDC stored string for a concept via `NCIt_Maps_To_GDC` |

Prompts: `ground_gdc_property`, `align_enum_to_cde`, `harmonize_data_dictionary`,
`release_impact_review`. Model fragments are **client-supplied** (parsed, never fetched or
stored); the mapping module talks to the EVS and caDSR modules only through the capability
interfaces in `map/capability.py`, so a split deployment can swap in a remote EVS adapter.
Capabilities caDSR lacks (alignment verdicts, lint findings, suggestion ranking) are declared
exceptions and are labelled in `meta.exception`.

Tool names use underscores because several clients restrict tool names to
`[A-Za-z0-9_-]`; the proposal's dotted name is carried in each tool's `title`.

Every result is `{result, provenance[], page?, truncation?, warnings[], meta}`. Provenance
carries the pinned NCIt release, the source URI, `servedBy` (live or cache) and license
status. Errors use the closed set from proposal Section 9 (`not_found`,
`release_not_available`, `release_mismatch`, `cursor_expired`, `bound_exceeded`,
`license_required`, `upstream_unavailable`, ...).

Resources: `evs://terminologies`, `evs://ncit/releases`, `evs://ncit/{release}/concept/{code}`.
Prompts: `resolve_term_with_provenance`, `walk_to_root`, `expand_value_set`, `map_across_terminologies`, `expand_cohort_terms`.

## Design points carried from the proposal

- **Release pinning (6.1).** A registry polls `/metadata/terminologies`; the active release
  is the latest live monthly release (or `ECM_RELEASE_PIN`). Every EVS call uses
  `ncit_<release>` in the path; releases EVS no longer serves fail with
  `release_not_available`; an upstream `version` that differs from the pinned release
  fails with `release_mismatch`; cursors and cache keys embed the release.
- **Bounded and batched (6.2, 6.4).** Per-invocation outbound budget that counts retries;
  batch retrieval chunked under the URL limit; all list results paged. The traversal engine
  expands each depth level in batches of 50 codes (10 when inverse relations are requested),
  admits edges round-robin across relationship kinds, keeps `Disease_Excludes_*` roles as
  `polarity: negative` edges without expanding them, and reports the first bound hit in
  `truncation` (with `perKind` reached/omitted counts and `exact: false` for lower bounds).
- **Concept sets without SPARQL (6.5).** `evs_find_concepts` combines native routes: EVS
  search for property values, text and subsets (one of each per query), inverse lookups for
  role/association targets, the terminology-wide associations endpoint for an association
  type. OR unions enumerated sets; AND intersects them. Combinations only SPARQL can answer
  return `capability_unavailable` with `plan.path = sparql_required` — SPARQL is an
  NCI-approved fallback not enabled here.
- **Good citizen (10.3).** Bounded concurrency, retries with backoff and jitter on 429/5xx
  and connection errors only, `Retry-After` honoured, 10 MiB response guard, in-process
  TTL cache per content class with negative caching.
- **License gate (6.6).** Key-gated map targets are withheld (or count-only for mapsets),
  including maps returned through `include=maps` on any concept tool, unless `ECM_LICENSE_KEY` is set; the key is sent only to gated requests and never
  appears in logs or provenance URIs.
- **caDSR realities (7.1).** Errors arrive as HTTP 200 with `apiResponse.type = "E"` and are
  mapped to `invalid_request` / `not_found`; field-name drift (`publicID`,
  `latesetVersionIndicator`, "Superceded") is normalised in one place; a 45 s deadline with
  retries on connection errors and 5xx only; one 6–10 s CDE fetch is cached by
  `publicId + version` and serves every derived view; there is no keyword search, so
  `cadsr_find_data_elements` is a declared fan-out that reports what ran; credentialed
  services return `capability_unavailable` with the reason when no credential is configured,
  and credentialed results are never cached. Provenance pins caDSR items with
  `registry {publicId, version, retrievedAt}` because caDSR publishes no release identity.
- **Platform chain (10.1, 10.4, 10.6).** Every tool call passes through one middleware:
  correlation id (minted or taken from `_meta`, propagated upstream as `X-Correlation-ID`),
  authentication binding (OAuth 2.1 resource-server mode via `ECM_AUTH_MODE=jwt`, with issuer
  and **audience** validation), per-namespace scope check (`evs:read`, `cadsr:read`,
  `cadsr:match`, `map:read`, intersected with the profile), per-client token-bucket rate limit,
  then an append-only audit record (free-text parameters hashed) and Prometheus metrics at
  `/metrics`. The FastAPI host enforces Host and Origin allow-lists (421) and a 4 MiB body cap
  (counted as the body streams in). It refuses to serve HTTP on a non-loopback address without
  JWT auth unless `ECM_ALLOW_UNAUTHENTICATED=true`, or `ECM_AUTH_MODE=databricks` inside a
  Databricks App ([`app.yaml`](app.yaml), whose proxy authenticates callers); `/metrics` and detailed `/readyz` need
  `ECM_ADMIN_TOKEN` off loopback. See [SECURITY.md](SECURITY.md).
  A Redis-compatible shared cache tier (`ECM_CACHE_URL`) sits behind the in-process tier;
  credentialed and negative results never reach it. See `docs/deployment.md` and `docs/runbook.md`.
- **Interface baseline (13, SOW-S16).** `evs-cadsr-mcp baseline export` freezes every tool's
  input/output schema, resources, prompts, envelope and error schemas and a fixture manifest
  under `spec/interface-baseline/v<INTERFACE_VERSION>/`; `baseline check` and the T-IFACE test
  classify drift as non-breaking (additions, text) or breaking (removals, re-typed or new
  required fields, annotation changes) and fail CI on the latter. Procedure: `docs/change-control.md`.
- **Acceptance package (14, D4–D9).** `tests/acceptance/` runs the same SOW-T1..T8 / UC
  scenarios over the MCP client in fixture and live modes; `scripts/run_acceptance.py` writes
  the results package; `docs/traceability.md` maps every SOW item to tools and tests;
  `docs/upstream-requirements-package.md` is the D7 package; `docs/user-guide.md` the D9 guide.
- **No synthesis.** Absent fields stay absent; upstream error text is never echoed.

## Keeping secrets out of git

Real credentials go in `.env` (git-ignored; copy `.env.example`) or the secrets manager, never
in tracked files. `.gitignore` also ignores `.env.*`, key and certificate files and
`*credentials*.json`. Three checks use the rules in `.gitleaks.toml` (gitleaks defaults plus
this server's `ECM_CADSR_PASSWORD` / `ECM_CADSR_CREDENTIAL` / `ECM_LICENSE_KEY` settings):

```bash
pre-commit install          # once per clone: scans staged changes before every commit
gitleaks dir . --redact     # on demand: working tree, including untracked files
gitleaks git . --redact     # on demand: full history
```

CI (`.github/workflows/secret-scan.yml`) scans the full history on every push and pull
request, so `git commit --no-verify` cannot bypass it. A deliberate dummy test value can be
marked with a trailing `# gitleaks:allow` comment; a real secret that was committed must be
rotated, not just deleted.

## Tests

```bash
pytest                      # unit + contract + conformance + acceptance (fixture mode), offline
ECM_LIVE=1 pytest -m live   # live smoke + acceptance scenarios against the live upstreams
python scripts/run_acceptance.py [--live]   # all tiers -> reports/<stamp>/{summary.md,junit-*.xml,benchmark.md}
python scripts/evaluate_retrieval.py --retriever upstream_contains --mode live   # SOW-D5 scorer (pre-index baseline)
python scripts/generate_tool_reference.py   # docs/tool-reference.md from the registered tools
python scripts/record_fixtures.py          # refresh tests/fixtures/evs from the live API
python scripts/record_fixtures.py --cadsr  # refresh tests/fixtures/cadsr (slow; no credentials needed)
ruff check .                # lint (long lines are not enforced yet; see pyproject.toml)
```

CI (`.github/workflows/ci.yml`) runs `ruff check` and the offline tests on Python 3.11 and
3.12 on every push and pull request, and checks that `uv.lock` and `deploy/requirements.lock`
match `pyproject.toml`. One contract test is marked `xfail(strict=True)` for a known open
issue (what to return for an absent code with replacement history); CI fails when it starts
passing, so the marker gets removed.

The fixtures currently in `tests/fixtures/evs` and `tests/fixtures/cadsr` are **hand-authored from the documented
EVS payload shapes** (`graph_small.json` is a synthetic graph used by the traversal and
planner tests and is meant to stay synthetic) (each file says so in `_note`), because the environment used to write
this pass had no network egress. Run `scripts/record_fixtures.py` (and `--cadsr`) once to replace them
with live recordings. caDSR query-parameter names marked `[verify]` in `cadsr/client.py`
(alternate-name, reference-document, context and classification lookups; the LOV path) were
taken from the API summaries, not a live call, and should be checked against the recording; the fake transport in `tests/conftest.py` derives the release from the
recorded terminologies fixture so the suite keeps working.

## License

[Apache License 2.0](LICENSE).

## Not in this pass (next increments)

`evs_semantic_search` and the NCIt index (Phase 3); the SPARQL fallback for
`evs_find_concepts`; the remote EVS adapter that would enable `map_*` in the `cadsr-only`
profile; server-side GDC dictionary fetch (`map://models/gdc/...`, needs egress approval);
the ICD-O diagnosis-group table; Form API `Form/query`; OpenTelemetry spans (metrics and
structured logs are in place); a per-upstream circuit breaker (retries, budgets and
concurrency limits are in place); the SOW acceptance package (Phase 7).
