# Deployment guide

This document covers the two supported ways to run `evs-cadsr-mcp` (proposal Section 10.5):
locally over stdio beside a desktop client, and remotely as a stateless Streamable-HTTP
service behind a load balancer. Both run the same code; configuration is environment-driven
with the `ECM_` prefix (see `.env.example` and `src/evs_cadsr_mcp/core/config.py`).

## Profiles

| Profile | Namespaces | Needs |
|---|---|---|
| `evs-only` | `evs_*` | nothing (EVS is public) |
| `cadsr-only` | `cadsr_*` | optional `ECM_CADSR_USERNAME` + `ECM_CADSR_PASSWORD` for LOV / CDE Match |
| `unified` | `evs_*`, `cadsr_*`, `map_*` | as above |

The `evs-only` profile is the SOW deliverable and hides the other namespaces.

## Local (trusted-local mode)

```bash
uv venv && uv pip install -e .
evs-cadsr-mcp serve --transport stdio --profile unified
```

No authentication, in-process cache only, audit off unless `ECM_AUDIT_SINK` is set. Add to a
desktop client as a stdio server (see README).

## Remote (resource-server mode)

The request path is: client → ALB (TLS, WAF) → uvicorn/FastAPI → middleware chain
(correlation id → token verification → scope check → rate limit → audit) → tool handler →
release context → cache (in-process, then shared) → upstream.

Required settings for a remote deployment:

| Setting | Purpose |
|---|---|
| `ECM_PUBLIC_HOST`, `ECM_TRUSTED_HOSTS` | Host allow-list; other `Host` values get 400/421 |
| `ECM_ALLOWED_ORIGINS` | Origin allow-list; disallowed `Origin` headers get 421 (DNS-rebinding defence) |
| `ECM_AUTH_MODE=jwt` + `ECM_AUTH_JWKS_URI` (or `ECM_AUTH_PUBLIC_KEY`), `ECM_AUTH_ISSUER`, `ECM_AUTH_AUDIENCE` | OAuth 2.1 resource server: signature, issuer and **audience** validation so tokens for other servers are rejected; RFC 9728 protected-resource metadata is served by the SDK |
| `ECM_SCOPE_ENFORCEMENT` | per-namespace scopes `evs:read`, `cadsr:read`, `cadsr:match`, `map:read` (intersected with the profile); on by default with `jwt` |
| `ECM_ALLOW_UNAUTHENTICATED` | the server refuses to serve HTTP on a non-loopback address without `jwt`; set `true` only behind a trusted, authenticating gateway |
| `ECM_ADMIN_TOKEN` | Bearer token for `/metrics` and detailed `/readyz` when not bound to loopback |
| `ECM_RATE_LIMIT_PER_MINUTE`, `ECM_RATE_LIMIT_BURST` | per-client token bucket (client id from the token, else the client IP; `anonymous` on stdio) |
| `ECM_AUDIT_SINK` | `stdout` (HTTP only; ship with the log driver), `stderr`, or a file path; one JSON record per invocation, free-text parameters hashed |
| `ECM_CACHE_URL` | Redis-compatible shared cache (`rediss://` with a password, private network only, in production); `memory://` for single-node testing. Treated as a secret |
| `ECM_CADSR_USERNAME` + `ECM_CADSR_PASSWORD` (or the combined `ECM_CADSR_CREDENTIAL=user:password`, not both), `ECM_LICENSE_KEY` | from the secrets manager; never logged, never in provenance URIs; a username without a password (or both forms at once) stops the server at startup |

Egress should be limited to `api-evsrest.nci.nih.gov`, `cadsrapi.cancer.gov`,
`cadsr.nci.nih.gov`, the CDE AI Match host (if used), the identity provider, the secrets
manager and the shared cache. Server-side GDC dictionary fetch is not implemented and would
be a separately approved egress.

### Containers

`deploy/Dockerfile` builds a non-root image; `deploy/docker-compose.yml` runs the server
with a Redis-compatible cache for local integration. Build on an NCI-approved base image
with hash-locked requirements for production.

### AWS reference (CDK, Python)

`deploy/cdk/app.py` is a reference stack: ALB → ECS Fargate (ARM, ≥ 2 tasks, CPU-based
autoscaling, health check on `/readyz`) → ElastiCache (TLS, encrypted at rest) with Secrets
Manager entries for the caDSR credential and EVS license key, CloudWatch logs and VPC
endpoints. It has **not** been synthesised or deployed from this repository; the identity
provider, certificate, WAF rules and egress allow-list are NCI decisions passed as context
(`cdk synth -c publicHost=... -c certificateArn=... -c idpJwksUri=... -c idpIssuer=...`).

Modern MCP clients are sessionless over Streamable HTTP, so no sticky routing is needed.
Lambda remains an option for low-traffic `evs-only` deployments.

## Health, readiness, metrics

* `GET /healthz` — process liveness.
* `GET /readyz` — 200 when the release registry answered and the shared cache (if any) pings,
  with the status and active NCIt release. Use it as the load-balancer health check. With
  `Authorization: Bearer $ECM_ADMIN_TOKEN` (or on a loopback-only listener) it also reports live
  releases, auth mode, caDSR/credential/AI-match state and cache statistics.
* `GET /metrics` — Prometheus text: `ecm_tool_calls_total{tool,profile,status}`,
  `ecm_tool_latency_ms` histogram, `ecm_outbound_requests_total`, `ecm_truncations_total{bound}`,
  `ecm_rate_limit_rejections_total`, `ecm_scope_denials_total`, `ecm_cache_hits_total`,
  `ecm_active_release_info{release}`. Needs `Authorization: Bearer $ECM_ADMIN_TOKEN` unless the
  listener is loopback-only (otherwise 404). Disable with `ECM_METRICS_ENABLED=false`.

Logs are structured (`ECM_LOG_JSON=true`) and carry the correlation id, which is also sent
upstream as `X-Correlation-ID` and returned in every envelope's `meta.correlationId`.

## Platform port and registry metadata

Hosts that inject a `PORT` (cloud.gov, IBM Code Engine, Heroku-style buildpacks) are honoured:
without `ECM_HTTP_PORT` or `--port`, the HTTP listener uses `PORT`. `PORT` never changes the bind
address. Set `ECM_HTTP_HOST=0.0.0.0` together with JWT auth (or `ECM_ALLOW_UNAUTHENTICATED=true`
behind an authenticating gateway); otherwise the server stays on loopback or refuses to start.

`server.json` describes the server for the [MCP Registry](https://registry.modelcontextprotocol.io)
as the PyPI package `evs-cadsr-mcp`, run with `uvx evs-cadsr-mcp serve`. It is not published yet.
To publish: release the package to PyPI (its README carries the required
`mcp-name: io.github.compbioutils/evs-cadsr-mcp` marker), keep `version` in `server.json` equal to the
`pyproject.toml` version (a unit test checks this), then run `mcp-publisher login github` as a
member of the compbioutils organization and `mcp-publisher publish`.

## Release rollover

EVS publishes a new monthly NCIt release and keeps only the most recent few live. The release
registry polls `/metadata/terminologies` every `ECM_RELEASE_POLL_SECONDS` (default 600) and
moves the active release forward automatically; `ECM_RELEASE_PIN` freezes it. Cache keys,
cursors and provenance embed the release, so a rollover never mixes releases: cursors from
the old release fail with `cursor_expired`, and an upstream `version` that differs from the
pinned one fails with `release_mismatch`. See `docs/runbook.md`.

The ICD-O-3 map used by `map_map_icdo_to_ncit` comes from EVS's ICD-O-3.1 mapping files,
downloaded at runtime into `ECM_ICDO_CACHE_DIR` and re-checked every `ECM_ICDO_SYNC_INTERVAL_S`
(runbook, "ICD-O-3 mapping files"). Deployments need HTTPS egress to `evs.nci.nih.gov` (or set
`ECM_ICDO_SOURCE_URL` to an internal HTTPS mirror). The cache must be writable; mount a volume to
keep it across restarts, or share one between replicas (syncs are serialised with a file lock).
Air-gapped hosts set `ECM_ICDO_SYNC_INTERVAL_S=0` and install copies with
`evs-cadsr-mcp icdo sync --from-dir`.
