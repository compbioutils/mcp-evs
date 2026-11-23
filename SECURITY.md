# Security

`evs-cadsr-mcp` is a read-only MCP server over the public NCI EVS REST API and the caDSR APIs.
It holds two kinds of secret: caDSR Basic credentials (`ECM_CADSR_USERNAME`/`ECM_CADSR_PASSWORD`)
and an optional EVS license key (`ECM_LICENSE_KEY`, for MedDRA). Most of the controls below exist
to keep callers from borrowing those secrets, and to keep the server's answers trustworthy.

## Deployment rules

| Rule | Enforced by |
|---|---|
| HTTP on a non-loopback address needs JWT auth (`ECM_AUTH_MODE=jwt` with `ECM_AUTH_JWKS_URI`, `ECM_AUTH_ISSUER`, `ECM_AUTH_AUDIENCE`). The server refuses to start otherwise, unless `ECM_ALLOW_UNAUTHENTICATED=true` is set deliberately behind a trusted, authenticating gateway. | `Settings.check_http_exposure`, called by `create_app` |
| With JWT, issuer and audience are both required, and per-namespace scopes (`evs:read`, `cadsr:read`, `cadsr:match`, `map:read`) are enforced unless `ECM_SCOPE_ENFORCEMENT=false`. | `core/config.py`, `core/auth.py` |
| `/metrics` and the detailed `/readyz` need `Authorization: Bearer $ECM_ADMIN_TOKEN` unless the server listens on loopback only. Without it, `/readyz` returns status and active release only. | `server/app.py` |
| The shared cache (Redis) must not be reachable by anyone but the server: private network, a password, and `rediss://` off-host. Cached content is served as authoritative. `ECM_CACHE_URL` is a secret setting. | `deploy/docker-compose.yml`, `deploy/cdk/app.py` |
| In stdio mode, stdout carries the MCP protocol: logs go to stderr, and `ECM_AUDIT_SINK=stdout` is rejected. | `server/mcp_app.py`, `server/cli.py` |
| Put a reverse proxy or gateway in front for TLS. Without a token, rate limits are keyed by client IP, which is the proxy's IP behind a proxy; use JWT so limits apply per client. | `server/middleware.py` |

The local `docker compose` setup publishes ports on `127.0.0.1` only, requires
`ECM_REDIS_PASSWORD`, and sets `ECM_ALLOW_UNAUTHENTICATED=true` for local use. Remove that line
and configure JWT for any shared deployment. The CDK stack already uses JWT, scope enforcement,
TLS to the cache and Secrets Manager.

## Input and outbound controls

- Tool arguments are validated by pattern before use: NCIt codes `^C[1-9][0-9]*$`, caDSR public
  IDs and versions numeric, mapset names `^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$`.
- Every outbound path is checked again in the HTTP client: no `..`, query or fragment
  characters, so a tool argument can't reach another endpoint on the upstream host.
- Requests that carry the caDSR credential or the license key never follow redirects. (httpx
  drops `Authorization` on cross-origin redirects but not custom headers.)
- The license key is sent only to license-gated mapsets and never appears in provenance URIs.
  Without a key, gated map targets are withheld from every tool.
- Credentialed upstream responses are never cached. Upstream error text is never echoed.
- Request bodies are capped at 4 MiB while streaming; responses at 10 MiB. Each tool call has
  an outbound-request budget, and traversals have node and depth bounds.
- The daily ICD-O-3.1 file download (`map/icdo_sync.py`) fetches four fixed file names from an
  operator-set HTTPS location, never follows redirects, caps each file at 25 MiB, and installs a
  new version only after the mapping files parse with the documented columns and the mapping
  count hasn't fallen by half. The previous version stays active on any failure, and the
  `.xls` and `About.html` are stored, never parsed.

## Supply chain

- Runtime dependencies are locked with hashes in `deploy/requirements.lock` (from `uv.lock`)
  and installed with `pip --require-hashes`. Base images are pinned by digest.
- `.github/workflows/dependency-audit.yml` runs `pip-audit` on the lock file on every push and
  weekly. `.github/workflows/secret-scan.yml` and the pre-commit hook run gitleaks.
- GitHub Actions are pinned by commit SHA with read-only permissions.

Regenerate the lock after any dependency change:

```bash
uv lock
uv export --frozen --no-emit-project --extra redis --format requirements-txt -o deploy/requirements.lock
```

### Advisory history

No advisories are ignored. FastMCP 3.4.11 (from 2.14.7) resolved the earlier ones: three FastMCP
advisories (GHSA-vv7q-7jx5-f767 OpenAPI provider SSRF, GHSA-rww4-4w9c-7733 OAuth proxy consent,
GHSA-m8x7-r2rg-vh5g `fastmcp install` command injection) and DiskCache's unsafe pickle
deserialization (GHSA-w8v5-vhqr-4h9v), which left the tree with FastMCP 2's dependencies.

## Reporting a problem

Report suspected vulnerabilities privately to the repository maintainers (bensonml@nih.gov) rather than
in a public issue. Rotate any credential that may have been exposed; deleting it is not enough.
