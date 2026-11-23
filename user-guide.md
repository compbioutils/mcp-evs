# User and developer guide (SOW D9)

This guide is for people who connect an agent to `evs-cadsr-mcp`, write prompts against it,
or extend it. For a plain-language guide to each tool with simple examples, start with
[`docs/tools/`](tools/README.md). The generated tool-by-tool reference is `docs/tool-reference.md`
(`python scripts/generate_tool_reference.py`); the frozen contract is
`spec/interface-baseline/`; deployment and operations are in `docs/deployment.md` and
`docs/runbook.md`.

## What the server is

A read-only, release-grounded, provenance-carrying view of two NCI systems for LLM agents:
EVS (the NCI Thesaurus, NCIt) through `evs_*` tools, caDSR (Common Data Elements) through
`cadsr_*` tools, and the joins between them through `map_*` tools. It never writes to either
system and never invents content: when something cannot be answered from the sources it says
so with a closed error code (`not_found`, `capability_unavailable`, …) rather than guessing.

## Connecting

Local (stdio) and remote (Streamable HTTP at `/mcp`) run the same code; see the README for
the Claude Desktop snippet and `docs/deployment.md` for remote mode with OAuth. Pick a profile:
`evs-only` (NCIt only), `cadsr-only`, or `unified` (all three namespaces).

## Reading a result

Every tool returns an envelope:

```json
{
  "result": …,
  "provenance": [{"source": "evs_rest", "servedBy": "live", "terminology": "ncit", "release": "26.10d",
                  "code": "C3224", "sourceUri": "https://api-evsrest.nci.nih.gov/api/v1/concept/ncit_26.10d/C3224?include=summary",
                  "retrievedAt": "2026-10-30T14:02:11Z", "license": {"terminology": "ncit", "status": "open"}}],
  "page": {"limit": 20, "offset": 0, "total": 412, "returned": 20, "nextCursor": "…"},
  "truncation": {"occurred": true, "bound": "maxEdges", "limit": 1000, "reached": 1000, "omitted": 37, "exact": true},
  "warnings": ["include=full is expensive; prefer summary plus itemised flags"],
  "meta": {"correlationId": "…", "tool": "evs_get_concept", "elapsedMs": 212, "outboundRequests": 1, "servedBy": "live", "exception": null}
}
```

What to cite: `provenance[].release` (NCIt release), `sourceUri`, and for caDSR items
`provenance[].registry {publicId, version, retrievedAt}` — caDSR publishes no release
identity, so the retrieval time is part of the citation. `servedBy` tells you whether the
item came live or from cache (cache entries keep the original `retrievedAt`).

Pagination is by opaque cursor (`page.nextCursor`); cursors are bound to the release or the
caDSR item they were minted for and expire with `cursor_expired` otherwise. Bounded tools
(traversal, sub-tree, descendant expansion) report the first bound they hit in `truncation`
rather than silently cutting results; `exact: false` means the omitted count is a lower bound.

`meta.exception` is set when the server, not an upstream, computed a verdict or ranking
(value-set alignment, lint findings, CDE suggestions). Treat those as the server's opinion
with evidence, not as caDSR or EVS content.

## Release pinning

Omit `release` to use the server's active NCIt release (the latest monthly release EVS serves
live); pass `release: "26.09d"` to pin. Only the few most recent releases are live
(`evs_list_releases`); older ones return `release_not_available`. Every NCIt-derived item
carries its release; if EVS ever answers with a different release than the one pinned, the
call fails closed with `release_mismatch`.

## Example prompts

The server ships prompt templates (see `docs/tool-reference.md`); these are the patterns they
encode, usable directly in chat:

* *"What is NCIt code C3224, where does it sit in the hierarchy, and which GDC value does it
  map to?"* → `evs_get_concept` → `evs_get_paths` (toRoot) → `evs_get_concept_maps`
  (targetTerminology GDC) or `map_resolve_stored_value`.
* *"Resolve 'NSCLC' to a concept and cite the source."* → `evs_lookup_concept` (synonym
  match) → if ambiguous, `evs_search_concepts` → cite `provenance`.
* *"Which CDEs use the Race concept?"* → `cadsr_find_data_elements_by_concept` (C17049) or
  `map_find_data_elements_for_concept` with `expandDescendants` for a disease branch.
* *"Ground GDC demographic.race: CDE, concepts, and whether the enum matches the permissible
  values."* → paste the property JSON from the GDC dictionary → `map_resolve_model_property`
  (`format: gdc_json`) → read `cde`, `alignment.summary`, `notes`.
* *"Lint this MDF node before submission."* → `map_validate_model_fragment` (`format: mdf_yaml`,
  `mode: report`) → fix `error`s, review `warning`s.
* *"What changed for CDE 2192199 between 26.09d and 26.10d?"* → `map_assess_release_impact`
  (`cdePublicId`, `fromRelease`).
* *"Map ICD-O 8140/3 to NCIt."* → `map_map_icdo_to_ncit`.
* *"Expand melanoma into cohort terms but keep exclusions separate."* → `evs_traverse` with
  `children` + `roles`; inclusion terms from `result.edges`, exclusions from `result.exclusions`.

Prompting advice for agents: ask for `include` flags explicitly (`summary` is the default;
`full` is expensive); keep `limit`s small and follow cursors; when a tool returns
`truncation.occurred`, say so to the user; never fabricate a code or CDE id — if the server
returns nothing, report that.

## Known limitations

* No local NCIt index yet: `evs_semantic_search` (vector/hybrid) is absent; full-text search
  is EVS's own Elasticsearch via `evs_search_concepts`. The retrieval evaluation set and
  protocol (`docs/retrieval-evaluation-protocol.md`) are in place for when the NCI-approved
  embedding model is chosen.
* `evs_find_concepts` cannot combine two different property values under AND without the
  SPARQL fallback, which needs NCI approval (`capability_unavailable`, `plan.path = sparql_required`).
* caDSR has no keyword search: `cadsr_find_data_elements` is a declared fan-out and reports
  `coverage`; treat its results as "found by these routes", not "all CDEs matching".
* Credentialed caDSR services (contexts, CDE Match) and the CDE AI Match engine are available
  only when configured; the server says exactly which setting is missing.
* License-gated map targets (MedDRA by default) are withheld without a key; mapset entries
  return counts only.
* ICD-O diagnosis-group roll-up needs the ICD-O group table (not configured); `group` is null.
* `map_map_icdo_to_ncit` uses EVS's published ICD-O-3.1 mapping files, which the server
  downloads and re-checks daily (EVS's REST API offers no complete ICD-O lookup); concept status
  is still checked live. ICD-O-3.2 is not covered by these files.
* Model fragments are client-supplied; the server does not fetch the GDC dictionary.
* The documented upstream gaps that shape these limitations are in
  `docs/upstream-requirements-package.md`.

## Extending the server (developers)

Layout and conventions (see README for the tree):

* `core/` is shared platform; nothing in it imports a module.
* A module is `client.py` (typed, cached, release-pinned upstream calls that add provenance
  to the `Invocation`), `models.py` (compact records), `service.py` (transport-independent
  handlers returning `Envelope`s), `tools/` (thin MCP layer, one module per tool: argument
  schema, docstring, `run(...)`; shared argument types in `tools/_args.py`). Raise `EvsMcpError(code, message, details=…)`; never return partial results
  silently — use `truncation`, `warnings`, `page`.
* `map/` talks to the other modules only through `map/capability.py`.
* Add a tool: write the handler in `service.py`, create `tools/<tool_name>.py` with a
  `register(mcp, service, run)` function, list it in `TOOLS` in `tools/__init__.py`, use
  `@tool(mcp, name="ns_verb_object", title="ns.verb_object", tags={…})`, add a fixture route
  to `tests/conftest.py`, a contract test, the name to `tests/conformance/test_mcp.py`, and
  run `evs-cadsr-mcp baseline check` (additions are non-breaking; anything else needs
  `docs/change-control.md`).
* Fixtures are recorded with `scripts/record_fixtures.py`; keep hand-authored ones labelled.
