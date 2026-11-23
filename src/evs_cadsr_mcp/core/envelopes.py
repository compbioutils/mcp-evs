"""Result envelope, provenance, truncation and meta records (proposal Section 9).

Every tool returns ``Envelope[T]``. Field names are camelCase on the wire to match the
proposal's data contracts; Python code uses the same names to avoid alias confusion.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

ProvenanceSource = Literal[
    "evs_rest",
    "evs_fhir",
    "evs_mapset_export",
    "evs_download",
    "ncit_index",
    "cadsr_nciapi",
    "cadsr_formapi",
    "cadsr_legacy",
    "cadsr_match",
    "cadsr_vmmatch",
    "cadsr_cde_ai",
    "client_fragment",
]
# snapshot: read from a local export of upstream content shipped with the deployment.
ServedBy = Literal["live", "cache", "index", "snapshot"]


def utcnow() -> datetime:
    return datetime.now(UTC)


class License(BaseModel):
    terminology: str
    status: Literal["open", "display_obligation", "key_required"] = "open"
    text: str | None = None


class Registry(BaseModel):
    """Identity of a caDSR item. caDSR publishes no release identity, so items are pinned by
    publicId + version + retrievedAt (proposal 7.1, 'Registry state')."""

    system: Literal["caDSR"] = "caDSR"
    publicId: str
    version: str | None = None
    retrievedAt: datetime | None = None


class Provenance(BaseModel):
    """One record per upstream source consulted. ``release`` is required for NCIt items."""

    source: ProvenanceSource
    servedBy: ServedBy
    terminology: str | None = None
    release: str | None = None
    registry: Registry | None = None
    code: str | None = None
    sourceUri: str | None = None
    retrievedAt: datetime | None = None
    cachedAt: datetime | None = None
    correlationId: str | None = None
    license: License | None = None
    attribution: str | None = None


class Truncation(BaseModel):
    occurred: bool = False
    bound: str | None = None  # which bound tripped first: limit | maxDepth | maxNodes | maxRequests ...
    limit: int | None = None
    reached: int | None = None
    omitted: int | None = None
    exact: bool = True  # False when `omitted` is a lower bound
    perKind: dict[str, dict[str, int]] | None = None


class Meta(BaseModel):
    correlationId: str
    tool: str
    toolVersion: str = "1"
    elapsedMs: int = 0
    outboundRequests: int = 0
    servedBy: ServedBy = "live"
    exception: str | None = None  # label for declared exceptions (map.* only)


class Page(BaseModel):
    """Pagination block. ``nextCursor`` is opaque and embeds the release (see core/cursor.py)."""

    limit: int
    offset: int = 0
    total: int | None = None
    returned: int = 0
    nextCursor: str | None = None


class Envelope(BaseModel, Generic[T]):
    result: T
    provenance: list[Provenance] = Field(default_factory=list)
    truncation: Truncation | None = None
    page: Page | None = None
    warnings: list[str] = Field(default_factory=list)
    meta: Meta


def dedupe_provenance(records: list[Provenance]) -> list[Provenance]:
    seen: set[tuple[Any, ...]] = set()
    out: list[Provenance] = []
    for r in records:
        key = (r.source, r.servedBy, r.terminology, r.release, r.code, r.sourceUri,
               (r.registry.publicId, r.registry.version) if r.registry else None)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out
