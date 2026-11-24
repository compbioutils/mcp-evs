---
name: add-mcp-tool
description: Add or change an MCP tool in evs-cadsr-mcp (an evs_*, cadsr_* or map_* tool). Use when registering a new tool, adding a parameter, or changing what a tool returns, so it follows the repo's envelope, release-pinning, validation, error-hint, testing and documentation conventions.
---

# Add or change an MCP tool

A tool is three thin layers. Keep logic out of the `tools/` package.

| Layer | File | Job |
|---|---|---|
| Client | `src/evs_cadsr_mcp/<domain>/client.py` | One method per upstream call, via `self._get(inv, ctx, path, params=...)`. It counts the budget, caches, and records provenance. |
| Service | `src/evs_cadsr_mcp/<domain>/service.py` | Shapes upstream JSON into models, adds warnings (`inv.warn`), returns `inv.envelope(result, truncation=..., page=...)`. |
| Tool | `src/evs_cadsr_mcp/<domain>/tools/<tool_name>.py` | One module per tool with `register(mcp, service, run)`: typed, validated parameters, a docstring, and a call through `run`. |

## Steps

1. **Model the result** in `<domain>/models.py` with pydantic. Optional fields default to `None`:
   absent upstream data stays absent. If the model is recursive (a tree), pass an explicit
   `output_schema` to `tool(...)`, as `evs_list_subsets` and `evs_get_subtree` do.
2. **Client method.** Build the path only from validated values. Pass `ctx` (the
   `ReleaseContext`) so EVS calls are pinned to the release. Upstream failures already become
   `EvsMcpError`s; don't catch and re-word them.
3. **Service method** `async def x(self, inv, ctx, ...) -> Envelope[T]`. Raise `EvsMcpError(code,
   message, details=..., hint=...)` with a code from `core/errors.py`. Give a `hint` when the
   caller has a concrete next step (another tool, an allowed value from `details`).
4. **Register the tool** in a new module `<domain>/tools/<tool_name>.py`, copying an existing
   one such as `evs/tools/evs_get_concept_history.py`:

   ```python
   def register(mcp: FastMCP, service: EvsService, run: Runner) -> None:
       @tool(mcp, name="evs_get_concept_history", title="evs.get_concept_history", tags={"evs", "history"})
       async def evs_get_concept_history(code: Code, terminology: TerminologyArg = "ncit", release: ReleaseArg = None) -> Envelope[list[HistoryEvent]]:
           """One-line summary the model reads, then when to use it."""
           async def go(inv: Invocation):
               ctx = await service.release_context(terminology, release)
               return await service.get_concept_history(inv, ctx, code)
           return await run("evs_get_concept_history", go)
   ```

   Then import the module in `<domain>/tools/__init__.py` and add it to `TOOLS`; its position
   there is its position in `tools/list`. Shared argument types live in `<domain>/tools/_args.py`.

   - Every string that reaches a URL or query needs a `pattern` (reuse `Code`, `PublicId`,
     `VERSION_PATTERN`) or a `Literal`. Bound numbers with `ge`/`le`.
   - `tool()` marks every tool read-only; don't add write behaviour.
   - Name: `<domain>_<verb>_<noun>`. If it fits a workflow, mention it in `INSTRUCTIONS` in
     `server/mcp_app.py`.
5. **Tests.** Add contract tests in `tests/contract/test_<domain>_*.py` using the `services` or
   `unified_services` fixture and `FakeEvs` (`tests/conftest.py`). Add any fixture JSON under
   `tests/fixtures/`. Assert on the requests sent (`fake_evs.requests`) when parameters matter,
   and cover the main error path. For behaviour over MCP (validation, error JSON), add a
   conformance test in `tests/conformance/test_mcp.py`.
6. **Docs.** Add the tool to `docs/tools/<domain>-tools.md` (inputs table, two short use
   cases, "Good to know") and update the tool count in `README.md`.
7. **Verify.**

   ```bash
   uv run --no-sync ruff check .
   uv run --no-sync pytest -m "not live" -p no:cacheprovider -q
   uv run --no-sync python scripts/call_tool.py --mode live <tool_name> key=value   # real EVS
   ```

   For caDSR tools, use the `run-live-tests` skill (stage only).

## Checklist

- [ ] Inputs validated by pattern, Literal or bounds; nothing unvalidated reaches a URL or query.
- [ ] EVS calls pinned with `ctx`; provenance comes from the client, not built by hand.
- [ ] Errors use the closed code set; a specific `hint` where there's a clear next step.
- [ ] No upstream error text, secrets or full upstream responses in errors or logs.
- [ ] Contract tests for the success path and the main error; lint and offline tests pass.
- [ ] `docs/tools/` and the README tool count updated.
