"""Per-invocation context: correlation id, budget, timer, provenance collector.

Handlers are transport-independent: they receive an :class:`Invocation` and return a
result plus provenance; the tool layer wraps it in an :class:`Envelope`.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from .budget import Budget
from .envelopes import Envelope, Meta, Page, Provenance, Truncation, dedupe_provenance


@dataclass
class Invocation:
    tool: str
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    budget: Budget = field(default_factory=lambda: Budget(max_requests=50))
    started: float = field(default_factory=time.perf_counter)
    provenance: list[Provenance] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    served_by_cache: int = 0
    served_by_live: int = 0
    exception: str | None = None  # label for declared exceptions (map.* capabilities caDSR lacks)

    def add_provenance(self, *records: Provenance) -> None:
        for r in records:
            if r.correlationId is None:
                r.correlationId = self.correlation_id
            if r.servedBy == "cache":
                self.served_by_cache += 1
            elif r.servedBy == "live":
                self.served_by_live += 1
            self.provenance.append(r)

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def envelope(self, result, *, truncation: Truncation | None = None, page: Page | None = None) -> Envelope:
        if self.served_by_live:
            served = "live"
        elif self.served_by_cache:
            served = "cache"
        else:
            served = "live"
        meta = Meta(
            correlationId=self.correlation_id,
            tool=self.tool,
            elapsedMs=int((time.perf_counter() - self.started) * 1000),
            outboundRequests=self.budget.used,
            servedBy=served,
            exception=self.exception,
        )
        return Envelope(
            result=result,
            provenance=dedupe_provenance(self.provenance),
            truncation=truncation,
            page=page,
            warnings=list(self.warnings),
            meta=meta,
        )
