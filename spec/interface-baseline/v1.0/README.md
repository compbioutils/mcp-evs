# Interface baseline v1.0 (draft, not yet frozen)

This directory is the Shared Interface Baseline required by SOW-S16 (proposal Section 13):
the contract between `evs-cadsr-mcp` and its clients, versioned independently of the server
build (`evs_cadsr_mcp.INTERFACE_VERSION`). It has two kinds of content.

**Generated** by `evs-cadsr-mcp baseline export` from the running code (do not edit by hand):

| Path | Content |
|---|---|
| `tools/<profile>/<tool>.schema.json` | MCP `Tool` object: name, title, description, annotations, `inputSchema`, `outputSchema` |
| `profiles/<profile>.json` | tool, resource, template and prompt names visible in that deployment profile |
| `resources/<profile>.json`, `prompts/<profile>.json` | resource, resource-template and prompt definitions |
| `envelopes/*.schema.json` | `Envelope`, `Provenance`, `Truncation`, `Page`, `Meta`, `ErrorEnvelope` |
| `error-codes.json` | the closed error-code set with `retryable` flags |
| `conformance-mock.json` | fixture ids, SHA-256 checksums and whether each fixture is a live recording |
| `manifest.json` | interface version, server version, generation time, per-file checksums |

**Authored** (reviewed at the architecture review, changed only through change control):

| Path | Content |
|---|---|
| `transport-security.md` | endpoint, transports, headers, token requirements, scopes, host/origin policy |
| `CHANGELOG.md` | versioned change history |
| `README.md` | this file |

## Status

The generated files are **absent** until `evs-cadsr-mcp baseline export` has been run in an
environment with the dependencies installed; the environment this repository was authored in
had no package access. Freezing procedure:

1. `uv pip install -e '.[dev]' && pytest` green.
2. `python scripts/record_fixtures.py && python scripts/record_fixtures.py --cadsr` so
   `conformance-mock.json` records live fixtures, not hand-authored ones.
3. `evs-cadsr-mcp baseline export` and commit `spec/interface-baseline/v1.0/`.
4. From then on `evs-cadsr-mcp baseline check` (and the `T-IFACE` test
   `tests/contract/test_interface_baseline.py::test_running_server_matches_frozen_baseline`)
   fail CI on breaking drift; see `docs/change-control.md`.

The SOW requires the baseline to be frozen no later than twenty business days after award.
