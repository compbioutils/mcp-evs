# Agent guide: evs-cadsr-mcp

Read-only MCP server over NCI EVS (NCI Thesaurus) and caDSR. FastMCP 3.x tools, hosted in
FastAPI for HTTP; stdio for desktop clients. Humans start with [README.md](README.md) and
[QUICKSTART.md](QUICKSTART.md); this file is the short version for coding agents.

## Commands

```bash
uv sync --frozen --extra dev                                    # install from the lock file
uv run --no-sync ruff check .                                   # lint (must pass; CI runs it)
uv run --no-sync pytest -m "not live" -p no:cacheprovider -q    # offline tests (must pass)
uv run --no-sync python scripts/run_live_tests.py               # live tests: EVS + caDSR stage, reads .env
uv run --no-sync python scripts/call_tool.py --mode live evs_lookup_concept identifier=melanoma
uv run --no-sync evs-cadsr-mcp serve --transport http --port 8000   # http://127.0.0.1:8000/mcp
```

Contract tests marked `xfail(strict=True)` track known open issues; when one starts passing, remove
its marker. Skills in [.github/skills/](.github/skills/) cover adding a tool and running live tests.

## Layout

- `src/evs_cadsr_mcp/core/`: platform shared by every tool: settings (`config.py`, prefix
  `ECM_`), envelope and provenance (`envelopes.py`), closed error set with hints (`errors.py`),
  release resolver, budgets, cursors, caches, the resilient HTTP client, auth, audit, metrics.
- `evs/`, `cadsr/`, `map/`: each has `client.py` (upstream calls), `service.py` (logic, returns
  envelopes), `models.py`, and a `tools/` package (MCP registration only): one module per tool,
  shared argument types in `tools/_args.py`, and `TOOLS` in `tools/__init__.py` setting the order.
- `server/`: FastMCP assembly (`mcp_app.py`, including the server instructions), FastAPI host
  (`app.py`), middleware chain, CLI.
- `tests/`: `unit`, `contract` (services against the fake upstreams in `tests/conftest.py`),
  `conformance` (over an MCP client), `acceptance` (use-case scenarios), `live` (`-m live`).

## Rules that keep answers trustworthy

- **Never synthesize.** Fields the upstream didn't return stay absent. Don't echo upstream error
  text; raise `EvsMcpError` with a code from the closed set in `core/errors.py`, and pass a
  specific `hint` when you know what the caller should try next.
- **Release pinning fails closed.** EVS content is fetched at a resolved release
  (`ReleaseContext`) and every result carries provenance with that release. A release EVS no
  longer serves is `release_not_available`, never a silent fallback to today's data.
- **Bounded work.** Every upstream request is counted against the invocation budget; traversals
  report what they cut in `truncation`. Page with release-bound cursors (`core/cursor.py`).
- **License gate.** Map targets in `ECM_LICENSE_GATED_TERMINOLOGIES` (MedDRA) are withheld without
  `ECM_LICENSE_KEY`, in every tool that returns maps.
- **caDSR stage only** for live work and tests: `ECM_CADSR_BASE_URL=https://cadsrapi-stage.cancer.gov`.
  The default URL is production; don't run anything against it.

## Security rules

- Validate tool arguments with a `pattern` on the parameter (see `Code` in `evs/tools/_args.py`,
  `PublicId` and `VERSION_PATTERN` in `cadsr/tools/_args.py`). Never build an upstream URL or query
  from an unvalidated string; the HTTP client rejects unsafe paths as a second line of defence.
- Secrets are `SecretStr` settings, sent only where needed, never logged, cached or put in
  provenance URIs. Real values live in `.env` (git-ignored) or a secrets manager.
- Logs go to stderr: stdout is the MCP stream in stdio mode. Don't `print` in server code.
- Don't weaken the startup checks: HTTP off loopback needs JWT auth, JWT needs issuer and
  audience. See [SECURITY.md](SECURITY.md).
- After changing dependencies: `uv lock`, then regenerate `deploy/requirements.lock` (command in
  `deploy/Dockerfile`). CI checks both are in sync.

## Tests

- New behaviour gets contract tests with the fake upstreams (`FakeEvs` in `tests/conftest.py`,
  fixtures under `tests/fixtures/`), asserting on the requests sent where that matters.
- Build settings with `Settings(_env_file=None, ...)` so a developer's `.env` can't leak in.
- Never `source .env` in a shell: it mangles the JSON-list settings. Use `run_live_tests.py`.

## Docs to keep in step

Tool behaviour and inputs: `docs/tools/` (`evs-tools.md`, `cadsr-tools.md`, `map-tools.md`).
Settings: `.env.example` and `docs/deployment.md`. Security posture: `SECURITY.md`. Tool counts
and design notes: `README.md`.

## Commits

Free-form, sentence-case imperative subject (≤ 72 characters), with a body explaining why.
The pre-commit hook runs secret scanning; never bypass it with `--no-verify`.
