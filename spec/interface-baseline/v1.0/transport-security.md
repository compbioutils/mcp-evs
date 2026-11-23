# Transport and security contract (interface baseline v1.0)

## Endpoints

| Mode | Transport | Endpoint | Notes |
|---|---|---|---|
| Local | MCP over stdio | `evs-cadsr-mcp serve --transport stdio` | trusted-local; no token |
| Remote | MCP Streamable HTTP | `https://<public-host>/mcp` | sessionless for current clients; legacy (2025) clients served from the same endpoint by the SDK |
| Admin | HTTPS | `/healthz`, `/readyz`, `/metrics` | not part of the MCP contract; restrict to the monitoring network |

Protected-resource metadata (RFC 9728) is published by the SDK when `ECM_AUTH_MODE=jwt`.

## Request headers (remote)

| Header | Requirement |
|---|---|
| `Authorization: Bearer <JWT>` | required when the server runs as a resource server; `aud` must equal the server's `ECM_AUTH_AUDIENCE`; `iss` must equal `ECM_AUTH_ISSUER`; signature verified against `ECM_AUTH_JWKS_URI` |
| `Host` | must match `ECM_TRUSTED_HOSTS` / `ECM_PUBLIC_HOST`; otherwise 400 |
| `Origin` | if present, must be in `ECM_ALLOWED_ORIGINS`; otherwise **421** |
| `Content-Length` | ≤ 4 MiB; otherwise 413 |
| MCP `_meta.correlationId` or `_meta.traceparent` | optional; echoed as `meta.correlationId` in every envelope and sent upstream as `X-Correlation-ID` |

## Scopes

| Scope | Grants |
|---|---|
| `evs:read` | all `evs_*` tools, `evs://` resources |
| `cadsr:read` | all `cadsr_*` tools except the matchers, `cadsr://` resources |
| `cadsr:match` | `cadsr_match_data_elements`, `cadsr_match_value_meanings`, `cadsr_list_match_backends` (with `cadsr:read`) |
| `map:read` | all `map_*` tools |
| `admin` | reserved for index administration (Phase 3) |

Scopes are intersected with the deployment profile: an `evs-only` deployment never grants
`cadsr:*` or `map:*`. A missing scope yields a tool error with `code = permission_denied` and
`details.missing`. Service-to-service callers use client-credentials tokens.

## Rate limiting and budgets

Per-client token bucket (`ECM_RATE_LIMIT_PER_MINUTE`, `ECM_RATE_LIMIT_BURST`); rejection is a
tool error `rate_limited` with `details.retryAfterSeconds` and `retryable: true`. Every
invocation also has an outbound request budget that counts retries; exhaustion is
`bound_exceeded`.

## Error contract

Validation and policy errors are **tool errors** (model-readable JSON envelope
`{"error": {"code", "message", "details", "retryable", "correlationId"}}` with the closed
code set in `error-codes.json`). Protocol errors are reserved for malformed MCP traffic.
Error messages never echo upstream text.

## Data handling

Read-only toward EVS and caDSR. No patient data. Retrieved text is data, never instructions.
Model fragments are parsed from the request, never fetched by URL. License keys and caDSR
credentials are never logged and never appear in provenance URIs; key-gated content is
withheld (`license_required`, `licenseRequired` markers) when no key is configured.

## Egress

`api-evsrest.nci.nih.gov`, `cadsrapi.cancer.gov`, `cadsr.nci.nih.gov`, the CDE AI Match host
(if configured), the identity provider, the secrets manager, the shared cache. Anything else
(for example `api.gdc.cancer.gov`) requires separate approval and a baseline change.
