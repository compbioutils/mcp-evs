"""Shared MCP tool plumbing used by every namespace (evs_*, cadsr_*, later map_*).

* :func:`tool` — ``mcp.tool`` with only the keyword arguments the installed FastMCP
  version supports (``title`` and ``tags`` arrived in different 2.x minors).
* :func:`make_runner` — builds the ``run(tool_name, handler)`` wrapper that creates an
  :class:`Invocation` with a budget, logs the outcome, and converts :class:`EvsMcpError`
  into a :class:`ToolError` whose message is the JSON error envelope.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

import structlog
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from .budget import Budget
from .config import Settings
from .context import Invocation
from .envelopes import Envelope
from .errors import EvsMcpError

log = structlog.get_logger(__name__)

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)

_TOOL_PARAMS = set(inspect.signature(FastMCP.tool).parameters)


def tool(mcp: FastMCP, *, name: str, title: str, tags: set[str], output_schema: dict[str, Any] | None = None):
    kwargs: dict[str, Any] = {"name": name, "annotations": READ_ONLY}
    if "title" in _TOOL_PARAMS:
        kwargs["title"] = title
    if "tags" in _TOOL_PARAMS:
        kwargs["tags"] = tags
    if output_schema is not None:
        kwargs["output_schema"] = output_schema
    return mcp.tool(**kwargs)


Runner = Callable[..., Awaitable[Any]]

# Bound by the middleware chain for the duration of one MCP request (proposal 10.1).
CORRELATION_ID: ContextVar[str | None] = ContextVar("ecm_correlation_id", default=None)
# A mutable holder created by the middleware and filled in place by the runner, so outcome details reach
# the audit step even if the tool runs in a copied context (task) rather than the middleware's own.
LAST_OUTCOME: ContextVar[dict[str, Any] | None] = ContextVar("ecm_last_outcome", default=None)


def _report(outcome: dict[str, Any]) -> None:
    holder = LAST_OUTCOME.get()
    if holder is not None:
        holder.clear()
        holder.update(outcome)


def _outcome_from_envelope(env: Envelope) -> dict[str, Any]:
    releases = {p.release for p in env.provenance if p.release}
    terms = {p.terminology for p in env.provenance if p.terminology}
    cadsr_ids = sorted({f"{p.registry.publicId}:{p.registry.version or 'latest'}" for p in env.provenance if p.registry})
    try:
        size = len(env.model_dump_json(exclude_none=True))
    except Exception:  # noqa: BLE001
        size = None
    return {
        "status": "ok",
        "outboundRequests": env.meta.outboundRequests,
        "servedBy": env.meta.servedBy,
        "truncated": bool(env.truncation and env.truncation.occurred),
        "truncationBound": env.truncation.bound if env.truncation else None,
        "release": next(iter(releases)) if len(releases) == 1 else (",".join(sorted(releases)) or None),
        "terminology": next(iter(terms)) if len(terms) == 1 else (",".join(sorted(terms)) or None),
        "cadsrIds": cadsr_ids[:50],
        "resultBytes": size,
        "elapsedMs": env.meta.elapsedMs,
        "correlationId": env.meta.correlationId,
    }


def make_runner(settings: Settings) -> Runner:
    async def run(tool_name: str, fn: Callable[[Invocation], Awaitable[Envelope]], *, max_requests: int | None = None) -> Any:
        n = min(max_requests or settings.budget_max_requests, settings.budget_max_requests_cap)
        cid = CORRELATION_ID.get()
        inv = Invocation(tool=tool_name, budget=Budget(max_requests=n), **({"correlation_id": cid} if cid else {}))
        try:
            env = await fn(inv)
            log.info("tool.ok", tool=tool_name, correlation_id=inv.correlation_id, elapsed_ms=env.meta.elapsedMs, outbound=env.meta.outboundRequests)
            _report(_outcome_from_envelope(env))
            return env
        except EvsMcpError as exc:
            log.warning("tool.error", tool=tool_name, correlation_id=inv.correlation_id, code=exc.code, message=exc.message)
            _report({"status": "error", "errorCode": exc.code, "outboundRequests": inv.budget.used, "correlationId": inv.correlation_id})
            raise ToolError(exc.to_json(inv.correlation_id)) from exc
        except ToolError:
            raise
        except Exception as exc:  # never leak internals
            log.exception("tool.internal_error", tool=tool_name, correlation_id=inv.correlation_id)
            _report({"status": "error", "errorCode": "internal_error", "outboundRequests": inv.budget.used, "correlationId": inv.correlation_id})
            err = EvsMcpError("internal_error", "internal error; see server logs", correlation_id=inv.correlation_id)
            raise ToolError(err.to_json()) from exc

    return run


def tool_error_payload(err: ToolError) -> dict[str, Any] | None:
    """Parse the JSON error envelope out of a ToolError (used by tests and clients)."""
    try:
        return json.loads(str(err))
    except ValueError:
        return None
