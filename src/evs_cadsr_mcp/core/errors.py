"""Error envelope and the closed error-code set (proposal Section 9).

Errors are raised as :class:`EvsMcpError` inside the modules and converted to MCP
tool-execution errors at the tool boundary (see ``core/toolkit.py``). The error message
is a JSON document so the calling model can read ``code``, ``retryable``, ``hint`` and
``correlationId`` rather than free text. ``hint`` says what to try next; raise sites
that know more than the code's default pass a specific one.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

ErrorCode = Literal[
    "invalid_request",
    "permission_denied",
    "not_found",
    "release_not_available",
    "release_mismatch",
    "upstream_unavailable",
    "timeout",
    "bound_exceeded",
    "capability_unavailable",
    "cursor_expired",
    "license_required",
    "rate_limited",
    "internal_error",
]

RETRYABLE: frozenset[str] = frozenset({"upstream_unavailable", "timeout", "rate_limited"})

DEFAULT_HINTS: dict[str, str] = {
    "invalid_request": "Check the arguments against the tool's input schema (NCIt codes look like C3224, "
                       "caDSR public ids are numeric) and retry with corrected values.",
    "permission_denied": "The caller lacks a required scope, or the server's upstream credential was rejected. "
                         "Retrying won't help; ask the operator.",
    "not_found": "Check the identifier. For an NCIt code that may be retired, call evs_get_concept_history; "
                 "to find a concept by name, use evs_lookup_concept or evs_search_concepts.",
    "release_not_available": "Call evs_list_releases and pass one of the live releases as `release`, "
                             "or omit `release` to use the active one.",
    "release_mismatch": "EVS answered from a different release, usually during a monthly rollover. "
                        "Retry once; if it persists, pin `release` to a value from evs_list_releases.",
    "upstream_unavailable": "The upstream service is temporarily unavailable. Retry after a short wait.",
    "timeout": "Retry once. If it persists, narrow the request: a smaller limit, fewer include parts, "
               "or a shallower depth.",
    "bound_exceeded": "Narrow the request: lower limit or depth, ask for fewer include parts, "
                      "or page with nextCursor.",
    "capability_unavailable": "This deployment can't answer this request; see details. "
                              "Try another tool, or ask the operator to enable the capability.",
    "cursor_expired": "Start the listing again without `cursor`. Cursors are bound to one release "
                      "and server version.",
    "license_required": "This content needs a license key the server isn't configured with "
                        "(ECM_LICENSE_KEY). Use targets that aren't license-gated, or ask the operator.",
    "rate_limited": "Wait details.retryAfterSeconds (if present) before retrying.",
    "internal_error": "Unexpected server error. Report the correlationId to the operator.",
}


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False
    hint: str | None = None
    correlationId: str | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorBody


class EvsMcpError(Exception):
    """Domain error carrying a closed-set code. Never echoes raw upstream text."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        retryable: bool | None = None,
        correlation_id: str | None = None,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code: ErrorCode = code
        self.message = message
        self.details = details or {}
        self.retryable = retryable if retryable is not None else code in RETRYABLE
        self.correlation_id = correlation_id
        self.hint = hint or DEFAULT_HINTS.get(code)

    def envelope(self, correlation_id: str | None = None) -> ErrorEnvelope:
        return ErrorEnvelope(
            error=ErrorBody(
                code=self.code,
                message=self.message,
                details=self.details,
                retryable=self.retryable,
                hint=self.hint,
                correlationId=self.correlation_id or correlation_id,
            )
        )

    def to_json(self, correlation_id: str | None = None) -> str:
        return json.dumps(self.envelope(correlation_id).model_dump(exclude_none=True))


def invalid_request(message: str, *, hint: str | None = None, **details: Any) -> EvsMcpError:
    return EvsMcpError("invalid_request", message, details=details, hint=hint)


def not_found(message: str, **details: Any) -> EvsMcpError:
    return EvsMcpError("not_found", message, details=details)
