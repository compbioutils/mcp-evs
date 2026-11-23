"""Shared (second-tier) cache behind the in-process tier (proposal 10.2, 11).

:class:`ReleaseCache` stays the single entry point: ``aget``/``aput`` consult the local
TTL cache first, then the shared tier, and back-fill the local tier on a shared hit. The
shared tier is Redis-compatible (``redis.asyncio``) and optional; :class:`MemorySharedCache`
is a process-local stand-in used by tests and single-node deployments. Entries carry
``retrieved_at`` so provenance can report the original fetch time, and keys embed the
release (see ``cache_key``), so a release rollover never serves stale content.

Credentialed results never reach the shared tier (callers pass ``shared=False``).
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Protocol

import structlog

from .cache import CacheClass, CacheEntry, ReleaseCache

log = structlog.get_logger(__name__)


class SharedCache(Protocol):
    async def get(self, key: str) -> tuple[Any, float] | None:
        """Return (value, retrieved_at_epoch) or None."""

    async def set(self, key: str, value: Any, retrieved_at: float, ttl_s: int) -> None: ...
    async def ping(self) -> bool: ...
    async def aclose(self) -> None: ...


class MemorySharedCache:
    """Process-local stand-in with TTL semantics identical to the Redis tier."""

    def __init__(self) -> None:
        self._d: dict[str, tuple[str, float, float]] = {}  # key -> (json, retrieved_at, expires_at)
        self.hits = 0
        self.misses = 0

    async def get(self, key: str) -> tuple[Any, float] | None:
        item = self._d.get(key)
        if item is None or item[2] < time.time():
            self._d.pop(key, None)
            self.misses += 1
            return None
        self.hits += 1
        return json.loads(item[0]), item[1]

    async def set(self, key: str, value: Any, retrieved_at: float, ttl_s: int) -> None:
        self._d[key] = (json.dumps(value, default=str), retrieved_at, time.time() + ttl_s)

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None


class RedisSharedCache:
    """Redis-compatible tier. Values are JSON documents {v, t} (value, retrieved_at epoch)."""

    def __init__(self, url: str, *, prefix: str) -> None:
        try:
            import redis.asyncio as redis  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on the environment
            raise RuntimeError("ECM_CACHE_URL is set but the 'redis' package is not installed (pip install redis)") from exc
        self._r = redis.from_url(url, decode_responses=True)
        self._prefix = prefix

    def _k(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    async def get(self, key: str) -> tuple[Any, float] | None:
        raw = await self._r.get(self._k(key))
        if raw is None:
            return None
        doc = json.loads(raw)
        return doc.get("v"), float(doc.get("t", 0))

    async def set(self, key: str, value: Any, retrieved_at: float, ttl_s: int) -> None:
        await self._r.set(self._k(key), json.dumps({"v": value, "t": retrieved_at}, default=str), ex=ttl_s)

    async def ping(self) -> bool:
        try:
            return bool(await self._r.ping())
        except Exception:  # noqa: BLE001 - readiness probe
            return False

    async def aclose(self) -> None:
        await self._r.aclose()


class TieredCache:
    """Composes the in-process :class:`ReleaseCache` with an optional shared tier."""

    def __init__(self, local: ReleaseCache, shared: SharedCache | None, *, shared_ttls: dict[CacheClass, int]) -> None:
        self.local = local
        self.shared = shared
        self.shared_ttls = shared_ttls
        self.shared_hits = 0
        self.shared_misses = 0
        self.shared_errors = 0

    # sync local-only access keeps working for callers that do not need the shared tier
    def get(self, cls: CacheClass, key: str) -> CacheEntry | None:
        return self.local.get(cls, key)

    def put(self, cls: CacheClass, key: str, value: Any, *, retrieved_at: datetime | None = None) -> CacheEntry:
        return self.local.put(cls, key, value, retrieved_at=retrieved_at)

    async def aget(self, cls: CacheClass, key: str, *, shared: bool = True) -> CacheEntry | None:
        entry = self.local.get(cls, key)
        if entry is not None or self.shared is None or not shared:
            return entry
        try:
            hit = await self.shared.get(key)
        except Exception as exc:  # noqa: BLE001 - a broken shared tier must not break requests
            self.shared_errors += 1
            log.warning("cache.shared_error", op="get", error=type(exc).__name__)
            return None
        if hit is None:
            self.shared_misses += 1
            return None
        self.shared_hits += 1
        value, retrieved_epoch = hit
        retrieved_at = datetime.fromtimestamp(retrieved_epoch, tz=_UTC) if retrieved_epoch else None
        return self.local.put(cls, key, value, retrieved_at=retrieved_at)

    async def aput(self, cls: CacheClass, key: str, value: Any, *, retrieved_at: datetime | None = None, shared: bool = True) -> CacheEntry:
        entry = self.local.put(cls, key, value, retrieved_at=retrieved_at)
        if self.shared is not None and shared and value is not None:
            try:
                await self.shared.set(key, value, entry.retrieved_at.timestamp(), self.shared_ttls.get(cls, 3600))
            except Exception as exc:  # noqa: BLE001
                self.shared_errors += 1
                log.warning("cache.shared_error", op="set", error=type(exc).__name__)
        return entry

    def clear(self) -> None:
        self.local.clear()

    def stats(self) -> dict[str, Any]:
        s = self.local.stats()
        s["shared"] = None if self.shared is None else {"hits": self.shared_hits, "misses": self.shared_misses, "errors": self.shared_errors}
        return s

    async def ready(self) -> bool:
        if self.shared is None:
            return True
        try:
            return await self.shared.ping()
        except Exception:  # noqa: BLE001
            return False

    async def aclose(self) -> None:
        if self.shared is not None:
            await self.shared.aclose()


from datetime import UTC  # noqa: E402

_UTC = UTC


def build_shared_cache(url: str | None, *, prefix: str) -> SharedCache | None:
    if not url:
        return None
    if url.startswith("memory://"):
        return MemorySharedCache()
    return RedisSharedCache(url, prefix=prefix)
