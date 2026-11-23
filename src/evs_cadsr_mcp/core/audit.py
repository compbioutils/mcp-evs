"""Audit records (proposal 10.4): one JSON line per invocation to an append-only sink.

Free-text parameters are hashed (SHA-256, truncated) so the audit trail proves *what kind*
of request was made without retaining query text; identifiers (codes, public ids, releases,
booleans, small ints) are kept in clear because they are the thing audited.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, TextIO

import structlog

log = structlog.get_logger(__name__)

CLEAR_KEYS = {
    "code", "codes", "conceptCode", "conceptCodes", "publicId", "version", "release", "fromRelease", "toRelease", "terminology",
    "include", "limit", "cursor", "kind", "kinds", "direction", "type", "itemType", "backend", "mode", "axis", "icdoCode", "mapset",
    "subset", "commons", "combinator", "exact", "prune", "depth", "maxLevel", "expandDescendants", "includeExclusions", "includePermissibleValues",
    "lookupDataElements", "includeModules", "matchLimit", "by", "start", "selectors", "budget", "ids", "dataElementId", "cdePublicId", "cdeVersion",
}


def redact(args: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in (args or {}).items():
        if k in CLEAR_KEYS and _small(v):
            out[k] = v
        elif isinstance(v, bool) or v is None:
            out[k] = v
        elif isinstance(v, (int, float)):
            out[k] = v
        else:
            s = json.dumps(v, sort_keys=True, default=str) if not isinstance(v, str) else v
            out[k] = {"sha256": hashlib.sha256(s.encode()).hexdigest()[:24], "len": len(s)}
    return out


def _small(v: Any) -> bool:
    try:
        return len(json.dumps(v, default=str)) <= 512
    except (TypeError, ValueError):
        return False


@dataclass
class AuditRecord:
    timestamp: str
    correlationId: str
    tool: str
    status: str  # ok | error
    errorCode: str | None = None
    subject: str | None = None
    clientId: str | None = None
    scopes: list[str] = field(default_factory=list)
    arguments: dict[str, Any] = field(default_factory=dict)
    elapsedMs: int = 0
    outboundRequests: int | None = None
    resultBytes: int | None = None
    truncated: bool | None = None
    servedBy: str | None = None
    terminology: str | None = None
    release: str | None = None
    cadsrIds: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), default=str)


class AuditSink(Protocol):
    def write(self, record: AuditRecord) -> None: ...


class StreamSink:
    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def write(self, record: AuditRecord) -> None:
        self._stream.write(record.to_json() + "\n")
        self._stream.flush()


class FileSink:
    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: AuditRecord) -> None:
        with self._path.open("a", encoding="utf-8") as fh:  # append-only by construction
            fh.write(record.to_json() + "\n")


class MemorySink:
    """For tests."""

    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def write(self, record: AuditRecord) -> None:
        self.records.append(record)


def build_sink(spec: str | None) -> AuditSink | None:
    if not spec:
        return None
    if spec == "stdout":
        return StreamSink(sys.stdout)
    if spec == "stderr":
        return StreamSink(sys.stderr)
    if spec == "memory":
        return MemorySink()
    return FileSink(spec)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
