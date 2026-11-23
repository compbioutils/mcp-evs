# Operations runbook

Symptoms, diagnosis and remediation for `evs-cadsr-mcp`. Every tool error carries a closed
`code` and a `correlationId`; start from those.

## Reading an error

```json
{"error": {"code": "release_not_available", "message": "...", "details": {...}, "retryable": false, "hint": "Pass one of details.live as `release`, ...", "correlationId": "..."}}
```

| Code | Meaning | Action |
|---|---|---|
| `release_not_available` | the requested NCIt release is not served live by EVS (only the most recent few are) | use `evs_list_releases`; pin a live release or omit `release` |
| `release_mismatch` | upstream answered with a different `version` than the pinned release (rollover race or EVS fault) | retry once; if persistent, check `/readyz` active release and EVS status |
| `cursor_expired` | cursor minted for another release / item, or by an older server | restart the paged query without the cursor |
| `bound_exceeded` | budget (`maxRequests`) or size guard hit | narrow `include`, lower depth/limits, or raise the budget within caps |
| `capability_unavailable` | needs a credential or service not configured (LOV, CDE Match, AI Match, SPARQL fallback, ICD-O group table), or the EVS ICD-O-3.1 mapping files not downloaded yet for `map_map_icdo_to_ncit` | configure the secret / approve the fallback / run `evs-cadsr-mcp icdo sync`; the `details` say which |
| `license_required` | key-gated terminology (MedDRA) without `ECM_LICENSE_KEY` | obtain and configure the key (Tier-2 target) |
| `permission_denied` | token lacks a required scope, or upstream rejected configured credentials | check token scopes vs. `details.missing`; rotate the caDSR credential if upstream returned 401/403 |
| `rate_limited` | per-client bucket empty (`details.retryAfterSeconds`) | back off; raise `ECM_RATE_LIMIT_*` if legitimate |
| `upstream_unavailable` / `timeout` | EVS or caDSR unreachable after retries | check upstream status pages; cache keeps serving previously fetched items |
| `invalid_request` | argument problem or caDSR `apiResponse.type=E` parameter error | fix the arguments (message is model-readable) |
| `not_found` | concept / CDE / form absent at the release or in caDSR | verify the id; for retired concepts use `evs_get_concept_history` |

Find the invocation in the audit sink by `correlationId`; the record has the tool, hashed
arguments, outbound call count, result size, truncation, `servedBy`, release and caDSR ids.

## Checks

* **Liveness / readiness**: `curl -s localhost:8000/healthz`, `curl -s localhost:8000/readyz | jq`.
  `not_ready` with `reason` names the exception (EVS metadata unreachable); `sharedCache:
  unreachable` means Redis is down (the server keeps serving from the in-process tier).
* **Active release**: `/readyz .activeRelease` or `evs-cadsr-mcp releases`. Should equal the
  latest monthly release in `liveReleases` unless `ECM_RELEASE_PIN` is set.
* **Metrics**: `curl -s -H "Authorization: Bearer $ECM_ADMIN_TOKEN" localhost:8000/metrics | grep ecm_`
  (the token is not needed when the server listens on loopback only). Watch `ecm_tool_calls_total{status!="ok"}`,
  `ecm_tool_latency_ms` p95 (buckets), `ecm_truncations_total`, `ecm_rate_limit_rejections_total`,
  `ecm_scope_denials_total`.

## Procedures

**Monthly NCIt release rollover.** Nothing to do for live tools: the registry picks the new
release up within `ECM_RELEASE_POLL_SECONDS`. Expect a short burst of `cursor_expired` from
clients holding old cursors. Afterwards run `map_assess_release_impact` for the CDEs curators
care about (prompt `release_impact_review`). When the NCIt index exists (Phase 3) the active
release is held on the index build until the new build is activated.

**Pin or roll back a release.** Set `ECM_RELEASE_PIN=26.09d` and restart; `/readyz` shows the
pin. Only releases still live at EVS can be pinned (`release_not_available` otherwise).

**ICD-O-3 mapping files.** `map_map_icdo_to_ncit` uses EVS's ICD-O-3.1 mapping files
(`About.html`, the `.xls` workbook, and the Morphology and Topography `.txt` files under
`https://evs.nci.nih.gov/ftp1/NCI_Thesaurus/Mappings/ICD-O-3_Mappings/`). The server downloads
them into `ECM_ICDO_CACHE_DIR` (default `~/.cache/evs-cadsr-mcp/icdo`) on first use, then checks
EVS every `ECM_ICDO_SYNC_INTERVAL_S` (default one day) with conditional requests; unchanged files
cost a `304`. New files are installed as a new version only after both mapping files parse and
the mapping count hasn't fallen by half; otherwise the previous version stays in use.

```bash
evs-cadsr-mcp icdo status                     # active version, EVS publication date, last check
evs-cadsr-mcp icdo sync                       # check now (exit 1 on failure); --force re-downloads
evs-cadsr-mcp icdo sync --from-dir /media/icdo   # offline hosts: install files copied by hand
```

A running server picks up a version installed by the CLI on its next call; no restart needed.
With `ECM_ICDO_SYNC_INTERVAL_S=0` nothing downloads automatically; run `icdo sync` from cron.
The detailed `/readyz` (admin) shows the same status under `icdoMappings`. If `lastResult` is
`failed`, `lastError` says why; the tool keeps serving the previous version.

**Rotate the caDSR credential or EVS license key.** Update the secret; restart tasks (the
settings are read at start). Credentialed results are never cached, so no cache flush is needed.
Keys never appear in logs or provenance; if a leak is suspected, rotate upstream first.

**Flush the shared cache.** Only needed after a fixture/schema change in a shared environment:
`redis-cli --scan --pattern 'ecm:*' | xargs redis-cli del` (keys embed the release, so a
rollover does not need a flush).

**Upstream outage.** The circuit is per upstream host: EVS down leaves `cadsr_*` working and
vice versa; `map_*` fails with the upstream's code. Cached items keep serving. Do not raise
retries: budgets already count retries, and shared federal APIs should not be hammered.

**Refresh contract fixtures.** `python scripts/record_fixtures.py` (EVS) and
`--cadsr` (caDSR), then `pytest`; diff the fixtures to catch upstream drift.

**Benchmark before a release.** `python scripts/benchmark.py --mode fixtures` (offline) or
`--mode live`; compare p50/p95 and outbound counts against the previous report and the SLOs in
proposal 10.6 (cached concept tools p95 < 800 ms, live single-concept < 3 s, bounded traversal
< 10 s).

## Security notes

* Remote deployments must run `ECM_AUTH_MODE=jwt` with `ECM_AUTH_AUDIENCE` set to this
  server's identifier and `ECM_AUTH_ISSUER` set (both required; scope enforcement is then on by
  default). The server refuses an unauthenticated non-loopback listener. Set `ECM_ADMIN_TOKEN`
  for `/metrics` and detailed `/readyz`, and keep them reachable only from the monitoring network.
* Retrieved text (EVS definitions, caDSR question text) is data: the server never executes it,
  and prompts carry a data-not-instructions guard. Error messages never echo upstream text.
* Model fragments are parsed from the request body (4 MiB cap), never fetched by URL.
