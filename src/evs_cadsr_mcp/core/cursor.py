"""Opaque pagination cursors that embed the release they were minted for.

A cursor presented against a different release fails closed with ``cursor_expired``
(proposal Sections 6.1 and 9).
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from .errors import EvsMcpError

_CURSOR_VERSION = 1


def encode_cursor(*, release: str | None, offset: int, extra: dict[str, Any] | None = None) -> str:
    payload = {"v": _CURSOR_VERSION, "r": release, "o": offset}
    if extra:
        payload["x"] = extra
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str, *, release: str | None) -> tuple[int, dict[str, Any]]:
    """Return ``(offset, extra)`` or raise ``cursor_expired``/``invalid_request``."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise EvsMcpError("invalid_request", "cursor is malformed",
                          hint="Pass nextCursor exactly as returned, or omit `cursor` to start over.") from exc
    if not isinstance(payload, dict) or payload.get("v") != _CURSOR_VERSION:
        raise EvsMcpError("cursor_expired", "cursor was issued by an incompatible server version")
    if payload.get("r") != release:
        raise EvsMcpError(
            "cursor_expired",
            "cursor was issued for a different release",
            details={"cursorRelease": payload.get("r"), "requestedRelease": release},
        )
    offset = payload.get("o")
    if not isinstance(offset, int) or offset < 0:
        raise EvsMcpError("invalid_request", "cursor offset is invalid")
    return offset, dict(payload.get("x") or {})
