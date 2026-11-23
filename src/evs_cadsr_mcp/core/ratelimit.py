"""Per-client token-bucket rate limiter (proposal 10.1, 10.4 'abuse of shared APIs')."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class _Bucket:
    tokens: float
    updated: float


@dataclass
class RateLimiter:
    per_minute: int
    burst: int
    _buckets: dict[str, _Bucket] = field(default_factory=dict)
    rejected: int = 0

    @property
    def enabled(self) -> bool:
        return self.per_minute > 0

    def allow(self, key: str, *, now: float | None = None) -> tuple[bool, float]:
        """Return (allowed, retry_after_seconds)."""
        if not self.enabled:
            return True, 0.0
        now = time.monotonic() if now is None else now
        rate = self.per_minute / 60.0
        b = self._buckets.get(key)
        if b is None:
            b = _Bucket(tokens=float(self.burst), updated=now)
            self._buckets[key] = b
        b.tokens = min(float(self.burst), b.tokens + (now - b.updated) * rate)
        b.updated = now
        if b.tokens >= 1.0:
            b.tokens -= 1.0
            return True, 0.0
        self.rejected += 1
        return False, round((1.0 - b.tokens) / rate, 2)

    def prune(self, *, max_idle_s: float = 3600.0) -> None:
        cutoff = time.monotonic() - max_idle_s
        for k in [k for k, b in self._buckets.items() if b.updated < cutoff]:
            del self._buckets[k]
