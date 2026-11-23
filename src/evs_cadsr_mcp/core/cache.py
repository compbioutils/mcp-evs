"""In-process TTL cache keyed by release (proposal Section 10.2).

Only the in-process tier is implemented in this prototype. The interface is async and
value-opaque so a Redis-compatible shared tier can be added behind the same calls.
Cache entries record ``cached_at`` so provenance can report ``servedBy: cache``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from cachetools import TTLCache

from .envelopes import utcnow

CacheClass = Literal["metadata", "content", "search", "negative", "cadsr"]


@dataclass(frozen=True)
class CacheEntry:
    value: Any
    cached_at: datetime
    retrieved_at: datetime


def cache_key(namespace: str, release: str | None, **args: Any) -> str:
    """Stable key: namespace + release + canonical JSON of the arguments."""
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(canonical.encode()).hexdigest()[:32]
    return f"{namespace}|{release or '-'}|{digest}"


class ReleaseCache:
    def __init__(self, *, maxsize: int, ttls: dict[CacheClass, int]) -> None:
        self._caches: dict[CacheClass, TTLCache] = {
            cls: TTLCache(maxsize=maxsize, ttl=ttl) for cls, ttl in ttls.items()
        }
        self.hits = 0
        self.misses = 0

    def get(self, cls: CacheClass, key: str) -> CacheEntry | None:
        entry = self._caches[cls].get(key)
        if entry is None:
            self.misses += 1
        else:
            self.hits += 1
        return entry

    def put(self, cls: CacheClass, key: str, value: Any, *, retrieved_at: datetime | None = None) -> CacheEntry:
        now = utcnow()
        entry = CacheEntry(value=value, cached_at=now, retrieved_at=retrieved_at or now)
        self._caches[cls][key] = entry
        return entry

    def clear(self) -> None:
        for c in self._caches.values():
            c.clear()

    def stats(self) -> dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "sizes": {cls: len(c) for cls, c in self._caches.items()},
        }
