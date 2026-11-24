# Interface change control (SOW-S16)

The interface baseline under `spec/interface-baseline/v<MAJOR.MINOR>/` is the contract
clients build against. This procedure governs every change to it (proposal Section 13).

## What counts as a change

Anything a client could observe: tool names, titles, annotations, input or output JSON
Schema, resource URIs and templates, prompt names and arguments, the envelope / provenance /
truncation / page / error schemas, the error-code set, the transport and security contract
(`transport-security.md`), deployment profiles, and the conformance-mock manifest.

`evs-cadsr-mcp baseline check` (and the `T-IFACE` test) classify drift between the running
server and the frozen baseline:

| Drift | Class | Version bump |
|---|---|---|
| new tool, resource, template, prompt, error code | non-breaking | MINOR |
| new **optional** argument or result field | non-breaking | MINOR |
| description / title text change | non-breaking | PATCH (documented in CHANGELOG) |
| removed tool / resource / prompt / error code | breaking | MAJOR |
| removed or re-typed argument or result field; new **required** argument | breaking | MAJOR |
| changed tool annotations (read-only, idempotent, destructive, open-world) | breaking | MAJOR |
| changed scope requirements, endpoint, header or token rules | breaking | MAJOR |

## Non-breaking change

1. Implement; run `pytest` (T-IFACE reports the additions as non-breaking).
2. Bump `INTERFACE_VERSION` MINOR, re-export the baseline into the new directory, add a
   CHANGELOG entry, and include a test proving an N−1 client is unaffected (the previous
   baseline's tool schemas must still validate the new server's behaviour).
3. Ship.

## Breaking change

1. Open a **versioned change request** (CR-`<n>`): what changes, why, which clients are
   affected, the migration path, and whether the previous version will be served in parallel
   or through a compatibility adapter.
2. Attach an **impact assessment** produced from the drift report
   (`evs-cadsr-mcp baseline check > drift.txt`) and the affected use cases (proposal §4).
3. Update schemas and **both** contract test sets: N (new baseline) and N−1 (the previous
   baseline, exercised through the compatibility adapter or the parallel endpoint).
4. Obtain **written NCI approval** and record the CR id and date in `CHANGELOG.md`.
5. Bump `INTERFACE_VERSION` MAJOR; export `spec/interface-baseline/v<new>/`; keep the previous
   directory intact.
6. Serve the previous version in parallel (separate mount, e.g. `/v1/mcp`) or through an
   adapter that maps old tool names/arguments onto new handlers, until all registered clients
   have migrated; then retire it with a further CHANGELOG entry.

## Upstream-driven changes

If EVS or caDSR change in a way that forces a contract change (for example a payload field
disappears), record the upstream change in the upstream-gap register (proposal Appendix B)
and in the CR; fixture refresh (`scripts/record_fixtures.py`) is the detection mechanism and
should run on every monthly NCIt release.

## Freezing a baseline

See `spec/interface-baseline/v1.0/README.md`. A baseline is frozen when the generated files
are committed with a passing `baseline check`, and the CHANGELOG entry is marked frozen with
the review date.
